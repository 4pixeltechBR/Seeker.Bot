"""Telegram como controle remoto. Só o usuário permitido entra. O cérebro continua no PC."""

from __future__ import annotations

import base64
import io
import os
import subprocess
import threading
import wave
from contextlib import nullcontext

import httpx

from seeker.command_risk import decision
from seeker.secrets import hide_tokens
from seeker.speech import join_wavs

CREATE_NO_WINDOW = 0x08000000


class TelegramBot:
    def __init__(self, token: str, allowed: set[int], runtime, client: httpx.Client | None = None):
        self.token = token.strip()
        self.allowed = allowed
        self.runtime = runtime
        self._client = client or httpx.Client(timeout=httpx.Timeout(40.0, connect=10.0))
        self._owns_client = client is None
        self._offset = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def ready(self) -> bool:
        return bool(self.token and self.allowed)

    def start(self) -> None:
        if not self.ready:
            return
        try:
            self.publish_menu()
        except Exception:
            pass
        self._thread = threading.Thread(target=self._loop, name="seeker-telegram", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._owns_client:
            self._client.close()

    def poll_once(self) -> None:
        if not self.token:
            return
        response = self._client.get(self._url("getUpdates"), params={"offset": self._offset, "timeout": 0})
        response.raise_for_status()
        for update in response.json().get("result") or []:
            self._offset = int(update["update_id"]) + 1
            self._handle(update)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                response = self._client.get(
                    self._url("getUpdates"),
                    params={"offset": self._offset, "timeout": 25},
                )
                response.raise_for_status()
                for update in response.json().get("result") or []:
                    self._offset = int(update["update_id"]) + 1
                    self._handle(update)
            except Exception:
                self._stop.wait(3)

    def _handle(self, update: dict) -> None:
        callback = update.get("callback_query")
        if callback:
            self._answer_button(callback)
            return
        message = update.get("message") or {}
        user_id = int((message.get("from") or {}).get("id") or 0)
        if user_id not in self.allowed:
            return
        chat_id = int((message.get("chat") or {}).get("id") or 0)
        if not chat_id:
            return
        text = (message.get("text") or "").strip()
        voice = message.get("voice") or message.get("audio")
        if voice and not text:
            threading.Thread(target=self._voice_turn, args=(chat_id, voice), daemon=True).start()
            return
        command, _rest = split_command(text)
        if command == "start":
            self.send(chat_id, "Seeker no ar. Escolhe Texto ou Voz aqui embaixo.", reply_markup=mode_keyboard())
            return
        if command in MENU_COMMANDS and command not in {"texto", "voz"}:
            self.send(chat_id, self._menu_reply(command), reply_markup=mode_keyboard())
            return
        if command and command not in MENU_COMMANDS:
            self.send(chat_id, "Esse atalho era do outro agente. Manda /ajuda.", reply_markup=mode_keyboard())
            return
        choice = mode_choice(text)
        if choice:
            self._set_mode(chat_id, choice)
            if choice == "voz":
                try:
                    self.runtime.voice().arm()
                except Exception:
                    pass
            notice = "Respondo por texto e por voz." if choice == "voz" else "Respondo por texto."
            self.send(chat_id, notice, reply_markup=mode_keyboard())
            return
        if not text:
            return
        threading.Thread(target=self._turn, args=(chat_id, text), daemon=True).start()

    def _voice_turn(self, chat_id: int, voice: dict) -> None:
        with TelegramStatus(self, chat_id) as status:
            try:
                text = self._transcribe(str(voice.get("file_id") or ""))
            except Exception:
                self.send(chat_id, "Não consegui ouvir o áudio.")
                return
            if not text.strip():
                self.send(chat_id, "Não consegui ouvir o áudio.")
                return
            self._turn(chat_id, text, status)

    def _transcribe(self, file_id: str) -> str:
        info = self._client.get(self._url("getFile"), params={"file_id": file_id})
        info.raise_for_status()
        path = info.json()["result"]["file_path"]
        audio = self._client.get(f"https://api.telegram.org/file/bot{self.token}/{path}")
        audio.raise_for_status()
        import base64

        return self.runtime.transcribe(base64.b64encode(audio.content).decode("ascii"), "audio/ogg")

    def _turn(self, chat_id: int, text: str, status: TelegramStatus | None = None) -> None:
        choice = decision(text)
        if choice is not None and self.runtime.broker.resolve_latest(choice):
            return
        manager = nullcontext(status) if status is not None else TelegramStatus(self, chat_id)
        with manager as status:
            if not self.runtime.control.start():
                self.send(chat_id, "Ainda estou na mensagem anterior.")
                return
            chunks: list[str] = []
            try:
                seeker_chat = self._chat(chat_id)

                def emit(event: dict) -> None:
                    if event.get("type") == "token":
                        chunks.append(hide_tokens(event.get("text") or ""))
                    elif event.get("type") == "approval":
                        self.ask(chat_id, event["id"], event.get("command") or "")
                    elif event.get("type") == "secret":
                        label = event.get("label") or "a chave"
                        self.send(chat_id, f"Abri o cofre seguro no computador para {label}. Digite a chave lá. Não cole o valor aqui.")
                    elif event.get("type") == "error" and not chunks:
                        chunks.append(event.get("text") or "")

                self.runtime.agent.run(seeker_chat, text, emit, origin="telegram")
            finally:
                self.runtime.control.finish()
            reply = "".join(chunks).strip() or "Pronto."
            reply = reply[:4000]
            self._deliver(chat_id, reply, status)

    def _answer_button(self, callback: dict) -> None:
        user_id = int((callback.get("from") or {}).get("id") or 0)
        data = str(callback.get("data") or "")
        message = callback.get("message") or {}
        chat_id = int((message.get("chat") or {}).get("id") or 0)
        if user_id in self.allowed and data.startswith("rd:") and chat_id:
            parts = data.split(":")
            if len(parts) == 3:
                threading.Thread(target=self._radar, args=(chat_id, parts[1], parts[2]), daemon=True).start()
        elif user_id in self.allowed and ":" in data:
            decision, approval_id = data.split(":", 1)
            self.runtime.broker.resolve(approval_id, decision == "yes")
        try:
            self._client.post(self._url("answerCallbackQuery"), json={"callback_query_id": callback.get("id")})
        except httpx.HTTPError:
            return

    def _radar(self, chat_id: int, code: str, card_id: str) -> None:
        try:
            result = self.runtime.radar_act(card_id, code)
        except Exception:
            self.send(chat_id, "Não consegui mexer nesse cartão.")
            return
        text = result.get("text") or result.get("confirm") or "Pronto."
        if result.get("confirm"):
            self.send(
                chat_id,
                result["confirm"],
                reply_markup={
                    "inline_keyboard": [[
                        {"text": "Sim", "callback_data": f"rd:y:{card_id}"},
                        {"text": "Não", "callback_data": f"rd:n:{card_id}"},
                    ]]
                },
            )
            return
        self.send(chat_id, text)

    def ask(self, chat_id: int, approval_id: str, command: str) -> None:
        self.send(
            chat_id,
            "Posso fazer isto?\n" + command[:3500],
            reply_markup={
                "inline_keyboard": [[
                    {"text": "Sim", "callback_data": f"yes:{approval_id}"},
                    {"text": "Não", "callback_data": f"no:{approval_id}"},
                ]]
            },
        )

    def publish_menu(self) -> None:
        """Troca o menu azul. A lista antiga do outro agente sai inteira."""
        commands = [{"command": name, "description": text} for name, text in MENU]
        for scope in ({"type": "default"}, {"type": "all_private_chats"}):
            self._client.post(self._url("deleteMyCommands"), json={"scope": scope})
        response = self._client.post(self._url("setMyCommands"), json={"commands": commands})
        response.raise_for_status()

    def _menu_reply(self, command: str) -> str:
        if command == "ajuda":
            lines = ["Este Seeker responde daqui do PC.", ""]
            lines.extend(f"/{name} — {text}" for name, text in MENU if name != "start")
            return "\n".join(lines)
        if command == "agenda":
            tasks = self.runtime.store.pending_tasks()
            if not tasks:
                return "Nenhuma tarefa pendente."
            return "\n".join(f"- {task['title']} — {task['due_at']}" for task in tasks[:15])
        if command == "rotinas":
            routines = self.runtime.store.active_routines()
            if not routines:
                return "Nenhuma rotina ativa."
            return "\n".join(f"- {item['instruction']} — {item['due_at']}" for item in routines[:15])
        if command == "memoria":
            memories = self.runtime.store.memories()
            if not memories:
                return "Ainda não guardei nenhuma memória."
            return "\n".join(f"- {item['text']}" for item in memories[:10])
        if command == "cofre":
            return "Manda o link do vídeo ou o tema. Eu mostro a pasta e espero um sim antes de guardar em E:\\Ideias."
        return "Manda /ajuda."

    def _mode(self, chat_id: int) -> str:
        value = self.runtime.store.get_setting(f"telegram_mode_{chat_id}", "texto")
        return value if value in {"texto", "voz"} else "texto"

    def _set_mode(self, chat_id: int, mode: str) -> None:
        self.runtime.store.set_setting(f"telegram_mode_{chat_id}", mode)

    def _deliver(self, chat_id: int, reply: str, status: TelegramStatus | None = None) -> None:
        self.send(chat_id, reply, reply_markup=mode_keyboard())
        if self._mode(chat_id) == "voz":
            if status is not None:
                status.show("record_voice")
            self.send_voice_reply(chat_id, reply)

    def send(self, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
        body: dict = {"chat_id": chat_id, "text": text}
        if reply_markup:
            body["reply_markup"] = reply_markup
        response = self._client.post(self._url("sendMessage"), json=body)
        response.raise_for_status()

    def send_voice_reply(self, chat_id: int, text: str) -> None:
        """Manda a resposta inteira em um áudio. Falha de voz não apaga o texto."""
        try:
            wav = one_wav(self.runtime.voice(), text)
            ogg = wav_to_voice_ogg(wav)
            data = {"chat_id": str(chat_id)}
            duration = wav_duration_seconds(wav)
            if duration is not None:
                data["duration"] = str(duration)
            response = self._client.post(
                self._url("sendVoice"),
                data=data,
                files={"voice": ("seeker.ogg", io.BytesIO(ogg), "audio/ogg")},
            )
            response.raise_for_status()
        except Exception:
            return

    def _chat(self, chat_id: int) -> str:
        key = f"telegram_chat_{chat_id}"
        existing = self.runtime.store.get_setting(key)
        if existing and self.runtime.store.get_chat(existing):
            return existing
        created = self.runtime.store.create_chat("Telegram")
        self.runtime.store.set_setting(key, created["id"])
        return created["id"]

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"


class TelegramStatus:
    """Mantém o 'escrevendo' do Telegram enquanto a resposta não sai. O aviso expira em 5s."""

    def __init__(self, bot: TelegramBot, chat_id: int):
        self._bot = bot
        self.chat_id = chat_id
        self.action = "typing"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> TelegramStatus:
        self._pulse()
        self._thread = threading.Thread(target=self._loop, name="seeker-typing", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.2)
        return False

    def show(self, action: str) -> None:
        self.action = action
        self._pulse()

    def _loop(self) -> None:
        while not self._stop.wait(4):
            self._pulse()

    def _pulse(self) -> None:
        try:
            response = self._bot._client.post(
                self._bot._url("sendChatAction"),
                json={"chat_id": self.chat_id, "action": self.action},
            )
            response.raise_for_status()
        except Exception:
            return


MENU = (
    ("start", "Abre o Seeker e os modos"),
    ("ajuda", "O que este Seeker faz"),
    ("texto", "Responder só por texto"),
    ("voz", "Responder por texto e voz"),
    ("agenda", "Tarefas pendentes"),
    ("rotinas", "Rotinas ativas"),
    ("memoria", "O que eu lembro"),
    ("cofre", "Como guardar um vídeo"),
)
MENU_COMMANDS = {name for name, _text in MENU}


def split_command(text: str) -> tuple[str, str]:
    token, _, rest = (text or "").strip().partition(" ")
    token = token.split("@", 1)[0].casefold()
    if not token.startswith("/"):
        return "", (text or "").strip()
    return token[1:], rest.strip()


def mode_keyboard() -> dict:
    return {
        "keyboard": [[{"text": "Texto"}, {"text": "Voz"}]],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def mode_choice(text: str) -> str | None:
    token = (text or "").strip().casefold()
    if not token or " " in token:
        return None
    token = token.split("@", 1)[0]
    if token in {"texto", "/texto"}:
        return "texto"
    if token in {"voz", "/voz"}:
        return "voz"
    return None


def one_wav(voice, text: str) -> bytes:
    """Junta os trechos do Kokoro num único WAV."""
    parts = getattr(voice, "speak_parts", None)
    if parts is None:
        return voice.speak(text)
    wavs = list(parts(text))
    if not wavs:
        raise RuntimeError("Áudio vazio.")
    if len(wavs) == 1:
        return wavs[0]
    return join_wavs(wavs)


def wav_duration_seconds(wav: bytes) -> int | None:
    try:
        with wave.open(io.BytesIO(wav), "rb") as handle:
            rate = handle.getframerate()
            frames = handle.getnframes()
    except (wave.Error, EOFError):
        return None
    if rate <= 0 or frames <= 0:
        return None
    return max(1, round(frames / rate))


def wav_to_voice_ogg(wav: bytes) -> bytes:
    """Converte o WAV do Kokoro para OGG Opus, o formato que o Telegram toca como voz."""
    if not wav:
        raise RuntimeError("Áudio vazio.")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", "pipe:0",
        "-c:a", "libopus",
        "-b:a", "32k",
        "-ac", "1",
        "-ar", "48000",
        "-application", "voip",
        "-f", "ogg",
        "pipe:1",
    ]
    flags = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
    completed = subprocess.run(
        command,
        input=wav,
        capture_output=True,
        timeout=120,
        check=False,
        **flags,
    )
    if completed.returncode != 0 or not completed.stdout.startswith(b"OggS") or b"OpusHead" not in completed.stdout:
        raise RuntimeError("ffmpeg não gerou OGG Opus.")
    return completed.stdout


def allowed_users(raw: str) -> set[int]:
    found = set()
    for item in (raw or "").replace(";", ",").split(","):
        item = item.strip()
        if item.isdigit():
            found.add(int(item))
    return found
