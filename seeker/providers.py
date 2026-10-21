"""Cascata online. Se a resposta ainda não começou, o próximo provedor entra."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Protocol

import httpx

from seeker.config import Config, ProviderConfig
from seeker.skills.research import Evidence, evidence_from_payload, format_research
from seeker.transcript import TOOL_SPECS, Message, ToolCall, to_gemini, to_openai

log = logging.getLogger("seeker.providers")


class ProviderError(Exception):
    def __init__(self, message: str, started: bool = False):
        super().__init__(message)
        self.started = started


class Provider(Protocol):
    name: str

    def available(self) -> bool: ...

    def stream(self, messages: list[Message], tools: list[dict] | None) -> Iterator[dict]: ...


class Cascade:
    def __init__(self, providers: list[Provider]):
        self.providers = providers

    def stream(self, messages: list[Message], tools: list[dict] | None) -> Iterator[dict]:
        enabled = [provider for provider in self.providers if provider.available()]
        if not enabled:
            yield {
                "type": "error",
                "text": "Nenhuma chave no .env. Preencha Gemini, Maritaca ou NVIDIA.",
            }
            return
        failures: list[str] = []
        for index, provider in enumerate(enabled):
            started = False
            try:
                for event in provider.stream(messages, tools):
                    started = True
                    yield event
                return
            except ProviderError as exc:
                if started or exc.started:
                    yield {"type": "error", "text": f"{provider.name} caiu no meio da resposta. {exc}"}
                    return
                failures.append(f"{provider.name}: {exc}")
                log.info("provedor %s falhou antes da resposta: %s", provider.name, exc)
                if index + 1 < len(enabled):
                    nxt = enabled[index + 1]
                    yield {
                        "type": "notice",
                        "text": f"{provider.name} indisponível. Tentando {nxt.name}.",
                    }
        yield {"type": "error", "text": "Os provedores online falharam. " + " | ".join(failures)}


class OpenAIProvider:
    def __init__(self, name: str, base_url: str, model: str, api_key: str, client: httpx.Client):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.client = client

    def available(self) -> bool:
        return bool(self.api_key)

    def stream(self, messages: list[Message], tools: list[dict] | None) -> Iterator[dict]:
        body = to_openai(messages, tools)
        body["model"] = self.model
        body["temperature"] = 0.3
        body["max_tokens"] = 8192
        body["stream"] = True
        produced = False
        try:
            with self.client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=body,
            ) as response:
                if response.status_code >= 400:
                    detail = response.read().decode("utf-8", "replace")[:300]
                    raise ProviderError(f"HTTP {response.status_code} {detail}")
                parser = OpenAIStreamParser()
                raw_json: list[str] = []
                json_mode = False
                for line in response.iter_lines():
                    if not json_mode and not raw_json and line.lstrip().startswith("{"):
                        json_mode = True
                    if json_mode:
                        raw_json.append(line)
                        continue
                    for event in parser.feed(line):
                        produced = True
                        yield event
                if json_mode:
                    for event in events_from_openai_payload(json.loads("\n".join(raw_json))):
                        produced = True
                        yield event
                else:
                    for event in parser.finish():
                        produced = True
                        yield event
        except ProviderError:
            raise
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise ProviderError(str(exc), started=produced) from exc
        if not produced:
            raise ProviderError("resposta vazia")


class GeminiProvider:
    def __init__(self, name: str, base_url: str, model: str, api_key: str, client: httpx.Client):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.client = client

    def available(self) -> bool:
        return bool(self.api_key)

    def stream(self, messages: list[Message], tools: list[dict] | None) -> Iterator[dict]:
        body = to_gemini(messages, tools)
        body["generationConfig"] = {"temperature": 0.3, "maxOutputTokens": 8192}
        produced = False
        calls: list[ToolCall] = []
        try:
            with self.client.stream(
                "POST",
                f"{self.base_url}/models/{self.model}:streamGenerateContent",
                params={"alt": "sse"},
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                json=body,
            ) as response:
                if response.status_code >= 400:
                    detail = response.read().decode("utf-8", "replace")[:300]
                    raise ProviderError(f"HTTP {response.status_code} {detail}")
                for line in response.iter_lines():
                    payload = _sse_json(line)
                    if payload is None:
                        continue
                    if "error" in payload and "candidates" not in payload:
                        message = payload["error"].get("message", "erro")
                        raise ProviderError(str(message)[:300], started=produced)
                    for event in gemini_events(payload):
                        if event["type"] == "tool_calls":
                            calls.extend(event["calls"])
                            continue
                        produced = True
                        yield event
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError(str(exc), started=produced) from exc
        if calls:
            produced = True
            yield {"type": "tool_calls", "calls": calls}
        if not produced:
            raise ProviderError("resposta vazia")


class OpenAIStreamParser:
    def __init__(self):
        self.calls: dict[int, dict] = {}

    def feed(self, line: str) -> list[dict]:
        payload = _sse_json(line)
        if payload is None:
            return []
        if payload.get("done"):
            return []
        choices = payload.get("choices") or []
        if not choices:
            return []
        delta = choices[0].get("delta") or {}
        events = []
        content = delta.get("content")
        if isinstance(content, str) and content:
            events.append({"type": "token", "text": content})
        for tool_call in delta.get("tool_calls") or []:
            index = int(tool_call.get("index", 0))
            slot = self.calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if tool_call.get("id"):
                slot["id"] = tool_call["id"]
            function = tool_call.get("function") or {}
            if function.get("name"):
                slot["name"] += function["name"]
            if function.get("arguments"):
                slot["arguments"] += function["arguments"]
        return events

    def finish(self) -> list[dict]:
        calls = _calls_from_slots(self.calls)
        if not calls:
            return []
        return [{"type": "tool_calls", "calls": calls}]


def events_from_openai_payload(payload: dict) -> list[dict]:
    choices = payload.get("choices") or []
    if not choices:
        return []
    message = choices[0].get("message") or {}
    events = []
    content = message.get("content") or ""
    if content:
        events.append({"type": "token", "text": content})
    calls = []
    for index, tool_call in enumerate(message.get("tool_calls") or []):
        function = tool_call.get("function") or {}
        calls.append(
            _tool_call(
                tool_call.get("id") or f"call_{index}",
                function.get("name") or "",
                function.get("arguments") or "{}",
            )
        )
    calls = [call for call in calls if call is not None]
    if calls:
        events.append({"type": "tool_calls", "calls": calls})
    return events


def gemini_events(payload: dict) -> list[dict]:
    events = []
    calls = []
    for candidate in payload.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            if part.get("thought"):
                continue
            text = part.get("text")
            if text:
                events.append({"type": "token", "text": text})
            call = part.get("functionCall") or part.get("function_call")
            if call and call.get("name"):
                args = call.get("args") or {}
                if not isinstance(args, dict):
                    args = {"_raw": str(args)}
                calls.append(ToolCall(id=f"gem_{call['name']}_{len(calls)}", name=call["name"], arguments=args))
    if calls:
        events.append({"type": "tool_calls", "calls": calls})
    return events


def grounded_evidence(client: httpx.Client, base_url: str, model: str, api_key: str, query: str) -> Evidence:
    if not api_key:
        return Evidence("Busca indisponível: falta a chave do Gemini.", ())
    response = client.post(
        f"{base_url.rstrip('/')}/models/{model}:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={
            "contents": [{"role": "user", "parts": [{"text": query}]}],
            "tools": [{"google_search": {}}],
        },
    )
    if response.status_code >= 400:
        return Evidence(f"A busca falhou (HTTP {response.status_code}).", ())
    return evidence_from_payload(response.json())


def grounded_search(client: httpx.Client, base_url: str, model: str, api_key: str, query: str) -> str:
    return format_research(grounded_evidence(client, base_url, model, api_key, query))


def build_providers(config: Config, env: dict[str, str], client: httpx.Client) -> tuple[list[Provider], callable]:
    providers: list[Provider] = []
    gemini: ProviderConfig | None = None
    for item in config.providers:
        key = env.get(item.env_key, "")
        if item.kind == "gemini":
            providers.append(GeminiProvider(item.name, item.base_url, item.model, key, client))
            if gemini is None:
                gemini = item
        elif item.kind == "openai":
            providers.append(OpenAIProvider(item.name, item.base_url, item.model, key, client))
        else:
            log.warning("provedor %s com tipo desconhecido: %s", item.name, item.kind)

    def evidence(query: str) -> Evidence:
        if gemini is None:
            return Evidence("Busca indisponível: nenhum provedor Gemini no config.toml.", ())
        return grounded_evidence(client, gemini.base_url, gemini.model, env.get(gemini.env_key, ""), query)

    def search(query: str) -> str:
        return format_research(evidence(query))

    return providers, search, evidence


def _sse_json(line: str) -> dict | None:
    text = line.strip()
    if not text or text.startswith(":"):
        return None
    if text.startswith("data:"):
        text = text[5:].strip()
    if not text or text == "[DONE]":
        return {"done": True} if text == "[DONE]" else None
    if not text.startswith("{"):
        return None
    return json.loads(text)


def _calls_from_slots(slots: dict[int, dict]) -> list[ToolCall]:
    calls = []
    for index in sorted(slots):
        slot = slots[index]
        call = _tool_call(slot["id"] or f"call_{index}", slot["name"], slot["arguments"] or "{}")
        if call is not None:
            calls.append(call)
    return calls


def _tool_call(call_id: str, name: str, arguments: str) -> ToolCall | None:
    if not name:
        return None
    try:
        parsed = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        parsed = {"_raw": arguments}
    if not isinstance(parsed, dict):
        parsed = {"_raw": arguments}
    return ToolCall(id=call_id, name=name, arguments=parsed)


__all__ = ["TOOL_SPECS", "Cascade", "ProviderError", "build_providers", "grounded_search"]
