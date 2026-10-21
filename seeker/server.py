"""HTTP só em 127.0.0.1. A janela e a agenda falam com este processo."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from seeker.runtime import Runtime
from seeker.secrets import hide_tokens, known_name
from seeker.speech import SpeechError

UI = Path(__file__).resolve().parent / "ui"
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def make_server(runtime: Runtime, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in FILES:
                name, content_type = FILES[path]
                body = (UI / name).read_bytes()
                self._bytes(200, content_type, body)
                return
            if path == "/api/settings":
                self._json(200, runtime.settings())
                return
            if path == "/api/health":
                self._json(
                    200,
                    {
                        "providers": runtime.provider_status(),
                        "roots": [str(root) for root in runtime.config.roots],
                        "mcp": runtime.mcp.status(),
                    },
                )
                return
            if path == "/api/voice/profile":
                self._json(200, runtime.voice().profile())
                return
            if path == "/api/terminal":
                session = runtime.shell.session
                self._json(200, {"text": session.text(), "cwd": str(session.cwd)})
                return
            if path == "/api/pulse":
                self._json(200, runtime.pulse())
                return
            if path == "/api/chats":
                self._json(200, {"chats": runtime.store.list_chats()})
                return
            chat_id = _chat_id(path)
            if chat_id and path.endswith("/" + chat_id):
                chat = runtime.store.get_chat(chat_id)
                if chat is None:
                    self._json(404, {"error": "Não encontrei a conversa."})
                    return
                self._json(
                    200,
                    {
                        "chat": chat,
                        "messages": [_public_message(item) for item in runtime.store.messages(chat_id)],
                        "events": [_public_event(item) for item in runtime.store.events(chat_id)],
                    },
                )
                return
            self._json(404, {"error": "Não encontrei."})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            limit = 12_000_000 if path.startswith("/api/voice") else 1_000_000
            payload = self._read_json(limit)
            if payload is None:
                return
            if path == "/api/settings":
                keys = payload.get("keys") if isinstance(payload.get("keys"), dict) else {}
                models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
                self._json(200, runtime.update_settings({str(k): str(v) for k, v in keys.items()}, {str(k): str(v) for k, v in models.items()}))
                return
            if path == "/api/secrets":
                self._secret(runtime, payload)
                return
            if path == "/api/chats":
                self._json(200, runtime.store.create_chat())
                return
            if path == "/api/terminal":
                command = str(payload.get("command") or "")
                output = runtime.shell.run(command)
                session = runtime.shell.session
                self._json(200, {"output": output, "text": session.text(), "cwd": str(session.cwd)})
                return
            if path == "/api/stop":
                runtime.control.cancel()
                runtime.broker.cancel_all()
                runtime.agent.gate.cancel_all()
                self._json(200, {"ok": True})
                return
            if path == "/api/voice/profile":
                try:
                    voice = runtime.voice()
                    voice.save_profile(
                        str(payload.get("prompt") or ""),
                        str(payload.get("style") or ""),
                        str(payload.get("gender") or ""),
                    )
                    audio = voice.preview()
                except SpeechError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._bytes(200, "audio/wav", audio)
                return
            if path == "/api/voice/arm":
                runtime.voice().arm()
                self._json(200, {"device": runtime.voice().device})
                return
            if path == "/api/voice/speak":
                try:
                    audio = runtime.voice().speak(str(payload.get("text") or ""))
                except SpeechError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._bytes(200, "audio/wav", audio)
                return
            if path == "/api/voice":
                try:
                    text = runtime.transcribe(str(payload.get("audio_base64") or ""), str(payload.get("mime") or "audio/webm"))
                except RuntimeError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._json(200, {"text": text})
                return
            if path == "/api/notices/ack":
                runtime.store.ack_notices([str(item) for item in payload.get("ids") or []])
                self._json(200, {"ok": True})
                return
            if path == "/api/radar":
                self._json(200, runtime.radar_act(str(payload.get("id") or ""), str(payload.get("action") or "")))
                return
            suggestion = _suggestion_id(path)
            if suggestion:
                status = "accepted" if path.endswith("/accept") else "dismissed"
                row = runtime.store.set_suggestion_status(suggestion, status)
                if row is None:
                    self._json(404, {"error": "Não encontrei a sugestão."})
                    return
                self._json(200, row)
                return
            if path.endswith("/messages"):
                chat_id = _chat_id(path)
                text = " ".join(str(payload.get("text") or "").split())
                if not chat_id or runtime.store.get_chat(chat_id) is None:
                    self._json(404, {"error": "Não encontrei a conversa."})
                    return
                if not text:
                    self._json(400, {"error": "Escreva alguma coisa."})
                    return
                if not runtime.control.start():
                    self._json(409, {"error": "O Seeker ainda está na mensagem anterior."})
                    return
                self._stream(chat_id, text, bool(payload.get("voice")))
                return
            approval = _approval_id(path)
            if approval:
                ok = runtime.broker.resolve(approval, bool(payload.get("allow")))
                self._json(200 if ok else 404, {"ok": ok})
                return
            self._json(404, {"error": "Não encontrei."})

        def _secret(self, runtime: Runtime, payload: dict) -> None:
            name = known_name(str(payload.get("name") or ""))
            secret_id = str(payload.get("id") or "")
            if payload.get("cancel"):
                ok = runtime.agent.gate.finish(secret_id, "cancelled") if secret_id else runtime.agent.gate.finish_name(name, "cancelled")
                self._json(200, {"ok": ok, "name": name, "set": False})
                return
            saved = runtime.update_settings({name: str(payload.get("value") or "")}, {}) if name else {}
            stored = name in saved.get("saved", [])
            if stored:
                if secret_id:
                    runtime.agent.gate.finish(secret_id, "saved")
                else:
                    runtime.agent.gate.finish_name(name, "saved")
            self._json(200 if stored else 400, {"ok": stored, "name": name, "set": stored})

        def _stream(self, chat_id: str, text: str, voice: bool) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            def emit(event: dict) -> None:
                safe = _public_event_live(event)
                raw = json.dumps(safe, ensure_ascii=False).encode("utf-8")
                self.wfile.write(b"data: " + raw + b"\n\n")
                self.wfile.flush()

            try:
                runtime.agent.run(chat_id, text, emit, voice=voice)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                runtime.control.cancel()
                runtime.broker.cancel_all()
                runtime.agent.gate.cancel_all()
            finally:
                runtime.control.finish()

        def _read_json(self, limit: int) -> dict | None:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > limit:
                self._json(413, {"error": "Mensagem grande demais."})
                return None
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._json(400, {"error": "JSON inválido."})
                return None
            if not isinstance(data, dict):
                self._json(400, {"error": "JSON inválido."})
                return None
            return data

        def _json(self, code: int, payload: dict) -> None:
            self._bytes(code, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        def _bytes(self, code: int, content_type: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), Handler)


def _public_message(item: dict) -> dict:
    shown = dict(item)
    shown["content"] = hide_tokens(str(item.get("content") or ""))
    return shown


def _public_event(item: dict) -> dict:
    shown = dict(item)
    shown["detail"] = hide_tokens(str(item.get("detail") or ""))
    return shown


def _public_event_live(event: dict) -> dict:
    safe = dict(event)
    if "text" in safe:
        safe["text"] = hide_tokens(str(safe.get("text") or ""))
    if "detail" in safe:
        safe["detail"] = hide_tokens(str(safe.get("detail") or ""))
    if "command" in safe:
        safe["command"] = hide_tokens(str(safe.get("command") or ""))
    safe.pop("value", None)
    return safe


def _chat_id(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "chats" and _hex(parts[2]):
        return parts[2]
    return None


def _approval_id(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) == 3 and parts[0] == "api" and parts[1] == "approvals" and _hex(parts[2]):
        return parts[2]
    return None


def _suggestion_id(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) == 4 and parts[0] == "api" and parts[1] == "suggestions" and parts[3] in {"accept", "dismiss"}:
        if _hex(parts[2]):
            return parts[2]
    return None


def _hex(value: str) -> bool:
    return len(value) in {8, 32} and all(char in "0123456789abcdef" for char in value)
