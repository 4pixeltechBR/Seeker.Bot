"""Cofre seguro. A chave entra num campo mascarado e não volta para o chat nem para o modelo."""

from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path

from seeker.config import KEY_FIELDS

PLACEHOLDER = "Quero guardar uma chave no cofre."
HIDDEN = "[chave ocultada]"

NAMES = {key: label for key, label in KEY_FIELDS}

_ALIASES = {
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
    "maritaca": "MARITACA_API_KEY",
    "sabia": "MARITACA_API_KEY",
    "sabiá": "MARITACA_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "nim": "NVIDIA_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY",
    "hyperbolic": "HYPERBOLIC_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "sambanova": "SAMBANOVA_API_KEY",
    "cohere": "COHERE_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "hf": "HUGGINGFACE_API_KEY",
    "inception": "INCEPTION_API_KEY",
    "mercury": "INCEPTION_API_KEY",
    "reka": "REKA_API_KEY",
    "cloudflare": "CLOUDFLARE_API_TOKEN",
    "zhipu": "ZHIPU_API_KEY",
    "glm": "ZHIPU_API_KEY",
    "stepfun": "STEPFUN_API_KEY",
    "yi": "YI_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "exa": "EXA_API_KEY",
    "jina": "JINA_API_KEY",
    "deepgram": "DEEPGRAM_API_KEY",
    "assemblyai": "ASSEMBLYAI_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "cartesia": "CARTESIA_API_KEY",
    "email": "IMAP_PASSWORD",
    "e-mail": "IMAP_PASSWORD",
    "imap": "IMAP_PASSWORD",
    "telegram": "TELEGRAM_BOT_TOKEN",
}

_FILLER = {
    "guarda", "guardar", "guarde", "salva", "salvar", "salve", "troca", "trocar", "troque",
    "chave", "chaves", "key", "api", "token", "senha", "segredo", "ocultada",
    "da", "do", "de", "a", "o", "as", "os", "um", "uma", "minha", "meu", "me",
    "aqui", "esta", "está", "essa", "esse", "isso", "cola", "cole", "colar",
    "por", "favor", "no", "na", "em", "cofre", "seguro", "nova", "novo", "ai",
    "gemini", "google", "groq", "nvidia", "nim", "maritaca", "sabia", "sabiá",
    "mistral", "openrouter", "deepseek", "siliconflow", "hyperbolic", "fireworks",
    "sambanova", "cohere", "huggingface", "inception", "mercury", "reka", "cloudflare",
    "zhipu", "glm", "stepfun", "tavily", "exa", "jina", "deepgram", "assemblyai",
    "elevenlabs", "cartesia", "telegram", "email", "e-mail", "imap", "bot",
}

_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"AIza[0-9A-Za-z\-_]{20,}"
    r"|gsk_[A-Za-z0-9]{20,}"
    r"|nvapi-[A-Za-z0-9\-_]{16,}"
    r"|sk-(?:proj-)?[A-Za-z0-9]{20,}"
    r"|xai-[A-Za-z0-9]{20,}"
    r"|[0-9]{8,}:[A-Za-z0-9_\-]{30,}"
    r")"
)


def known_name(name: str) -> str:
    text = " ".join(str(name or "").split())
    if text in NAMES:
        return text
    folded = text.casefold()
    for key, label in KEY_FIELDS:
        if folded == label.casefold():
            return key
    return _ALIASES.get(folded, "")


def label_for(name: str) -> str:
    return NAMES.get(known_name(name), "")


def guess_name(text: str) -> str:
    raw = text or ""
    folded = raw.casefold()
    if "AIza" in raw:
        return "GEMINI_API_KEY"
    if "gsk_" in raw:
        return "GROQ_API_KEY"
    if "nvapi-" in folded:
        return "NVIDIA_API_KEY"
    if re.search(r"[0-9]{8,}:[A-Za-z0-9_\-]{30,}", raw):
        return "TELEGRAM_BOT_TOKEN"
    for name, words in (
        ("GEMINI_API_KEY", ("gemini", "google ai")),
        ("GROQ_API_KEY", ("groq",)),
        ("NVIDIA_API_KEY", ("nvidia", "nim")),
        ("MARITACA_API_KEY", ("maritaca", "sabiá", "sabia")),
        ("MISTRAL_API_KEY", ("mistral",)),
        ("OPENROUTER_API_KEY", ("openrouter",)),
        ("DEEPSEEK_API_KEY", ("deepseek",)),
        ("SILICONFLOW_API_KEY", ("siliconflow",)),
        ("HYPERBOLIC_API_KEY", ("hyperbolic",)),
        ("FIREWORKS_API_KEY", ("fireworks",)),
        ("SAMBANOVA_API_KEY", ("sambanova",)),
        ("COHERE_API_KEY", ("cohere",)),
        ("HUGGINGFACE_API_KEY", ("huggingface", "hugging face")),
        ("INCEPTION_API_KEY", ("inception", "mercury")),
        ("REKA_API_KEY", ("reka",)),
        ("CLOUDFLARE_API_TOKEN", ("cloudflare",)),
        ("ZHIPU_API_KEY", ("zhipu", "glm")),
        ("STEPFUN_API_KEY", ("stepfun",)),
        ("YI_API_KEY", ("01.ai", "lingyi")),
        ("TAVILY_API_KEY", ("tavily",)),
        ("EXA_API_KEY", ("exa",)),
        ("JINA_API_KEY", ("jina",)),
        ("DEEPGRAM_API_KEY", ("deepgram",)),
        ("ASSEMBLYAI_API_KEY", ("assemblyai",)),
        ("ELEVENLABS_API_KEY", ("elevenlabs",)),
        ("CARTESIA_API_KEY", ("cartesia",)),
        ("TELEGRAM_BOT_TOKEN", ("telegram",)),
        ("IMAP_PASSWORD", ("imap", "senha do e-mail", "senha do email", "senha de e-mail", "senha de email")),
    ):
        if any(word in folded for word in words):
            return name
    return ""


def find_secrets(text: str) -> list[str]:
    return _TOKEN.findall(text or "")


def hide_tokens(text: str) -> str:
    raw = text or ""
    if not find_secrets(raw):
        return raw
    return _TOKEN.sub(HIDDEN, raw)


def redact(text: str) -> str:
    """Tira a chave. Se a mensagem era só ela, fica um pedido sem valor."""
    raw = text or ""
    if not find_secrets(raw):
        return raw
    cleaned = hide_tokens(raw)
    words = re.findall(r"[0-9A-Za-zÀ-ÿ]+", cleaned.replace(HIDDEN, " "))
    useful = [word for word in words if word.casefold() not in _FILLER]
    if not useful:
        return PLACEHOLDER
    return cleaned


class SecretGate:
    """Só o nome da chave e se a pessoa guardou. O valor não entra aqui."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._done: dict[str, str] = {}

    def open(self, name: str) -> tuple[str, threading.Event]:
        secret_id = uuid.uuid4().hex
        event = threading.Event()
        with self._lock:
            if len(self._done) > 20:
                self._done.clear()
            self._pending[secret_id] = {"name": name, "event": event, "status": "open"}
        return secret_id, event

    def pending(self) -> list[dict]:
        with self._lock:
            rows = [
                {"id": key, "name": item["name"], "label": label_for(item["name"])}
                for key, item in self._pending.items()
                if item["status"] == "open"
            ]
        return rows

    def finish(self, secret_id: str, status: str) -> bool:
        if status not in {"saved", "cancelled"}:
            return False
        with self._lock:
            item = self._pending.get(secret_id)
            if item is None or item["status"] != "open":
                return False
            item["status"] = status
            self._done[secret_id] = status
            self._pending.pop(secret_id, None)
            item["event"].set()
            return True

    def finish_name(self, name: str, status: str) -> bool:
        with self._lock:
            secret_id = ""
            for key, item in self._pending.items():
                if item["name"] == name and item["status"] == "open":
                    secret_id = key
                    break
        if not secret_id:
            return False
        return self.finish(secret_id, status)

    def take(self, secret_id: str) -> str:
        with self._lock:
            return self._done.pop(secret_id, "cancelled")

    def cancel_all(self) -> None:
        with self._lock:
            secret_ids = [key for key, item in self._pending.items() if item["status"] == "open"]
        for secret_id in secret_ids:
            self.finish(secret_id, "cancelled")


def scrub_notes(root: Path, clean) -> int:
    count = 0
    for folder in ("diario", "memorias", "licoes"):
        base = Path(root) / folder
        if not base.is_dir():
            continue
        for path in base.glob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            cleaned = clean(text)
            if cleaned != text:
                path.write_text(cleaned, encoding="utf-8")
                count += 1
    return count
