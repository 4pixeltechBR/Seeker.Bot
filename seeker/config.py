"""Configuração do app. O arquivo config.toml manda na ordem dos provedores."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PROVIDERS = (
    {
        "name": "Gemini",
        "kind": "gemini",
        "model": "gemini-2.5-flash",
        "env_key": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
    },
    {
        "name": "Maritaca",
        "kind": "openai",
        "model": "sabia-4-thinking",
        "env_key": "MARITACA_API_KEY",
        "base_url": "https://chat.maritaca.ai/api",
    },
    {
        "name": "NVIDIA",
        "kind": "openai",
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "env_key": "NVIDIA_API_KEY",
        "base_url": "https://integrate.api.nvidia.com/v1",
    },
)


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    kind: str
    model: str
    env_key: str
    base_url: str


@dataclass(frozen=True)
class Config:
    root: Path
    roots: tuple[Path, ...]
    shell_timeout_seconds: int
    max_tool_steps: int
    output_cap_chars: int
    file_cap_chars: int
    providers: tuple[ProviderConfig, ...]
    voice_engine: str
    voice_device: str
    voice_name: str
    voice_language: str
    vault: Path
    review_hour: int
    morning_hour: int
    morning_minute: int
    radar_tarefa: bool = True
    radar_disco: bool = True
    radar_email: bool = True
    radar_agenda: bool = True
    radar_whatsapp: bool = True
    calendar_ics: str = ""

    def radar_sources(self) -> tuple[str, ...]:
        chosen = []
        for name, flag in (
            ("tarefa", self.radar_tarefa),
            ("disco", self.radar_disco),
            ("email", self.radar_email),
            ("agenda", self.radar_agenda),
            ("whatsapp", self.radar_whatsapp),
        ):
            if flag:
                chosen.append(name)
        return tuple(chosen)


KEY_FIELDS = (
    ("GEMINI_API_KEY", "Gemini"),
    ("MARITACA_API_KEY", "Maritaca"),
    ("NVIDIA_API_KEY", "NVIDIA"),
    ("GROQ_API_KEY", "Groq"),
    ("IMAP_PASSWORD", "E-mail"),
    ("TELEGRAM_BOT_TOKEN", "Telegram"),
)


def settings_view(config: Config, env: dict[str, str]) -> dict:
    return {
        "keys": [{"id": key, "label": label, "set": bool(env.get(key))} for key, label in KEY_FIELDS],
        "models": [{"name": item.name, "model": item.model} for item in config.providers],
    }


def save_env_keys(path: Path, updates: dict[str, str]) -> list[str]:
    allowed = {key for key, _label in KEY_FIELDS}
    clean = {}
    for key, value in updates.items():
        if key not in allowed:
            continue
        text = str(value or "").strip()
        if not text or "\n" in text or "\r" in text:
            continue
        clean[key] = text
    if not clean:
        return []
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen = set()
    out = []
    for raw in lines:
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            name = line.split("=", 1)[0].strip()
            if name in clean:
                out.append(f"{name}={clean[name]}")
                seen.add(name)
                continue
        out.append(raw)
    for name, value in clean.items():
        if name not in seen:
            out.append(f"{name}={value}")
    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    return list(clean)


def save_models(path: Path, models: dict[str, str]) -> None:
    if not path.exists():
        return
    wanted = {name: value.replace('"', "").strip() for name, value in models.items() if str(value).strip()}
    lines = path.read_text(encoding="utf-8").splitlines()
    current = ""
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("name ="):
            current = stripped.split("=", 1)[1].strip().strip('"')
        if stripped.startswith("model =") and current in wanted:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}model = "{wanted[current]}"')
            continue
        out.append(line)
    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def load_env(path: Path) -> dict[str, str]:
    """Lê só o .env desta pasta. Variável vazia conta como ausente."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            values[key] = value
    return values


def load_config(root: Path | None = None) -> Config:
    root = (root or PROJECT_ROOT).resolve()
    path = root / "config.toml"
    data: dict = {}
    if path.exists():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    relative_roots = data.get("roots") or ["workspace"]
    roots = tuple(_resolve_root(root, item) for item in relative_roots)
    providers_raw = data.get("providers") or list(DEFAULT_PROVIDERS)
    providers = tuple(
        ProviderConfig(
            name=str(item["name"]),
            kind=str(item["kind"]),
            model=str(item["model"]),
            env_key=str(item["env_key"]),
            base_url=str(item["base_url"]).rstrip("/"),
        )
        for item in providers_raw
    )
    radar = data.get("radar") or {}
    ics = str(radar.get("calendar_ics") or "").strip()
    return Config(
        root=root,
        roots=roots,
        shell_timeout_seconds=int(data.get("shell_timeout_seconds", 30)),
        max_tool_steps=int(data.get("max_tool_steps", 8)),
        output_cap_chars=int(data.get("output_cap_chars", 8000)),
        file_cap_chars=int(data.get("file_cap_chars", 100_000)),
        providers=providers,
        voice_engine=str((data.get("voice") or {}).get("engine", "kokoro")),
        voice_device=str((data.get("voice") or {}).get("device", "cuda")),
        voice_name=str((data.get("voice") or {}).get("voice", "pm_santa")),
        voice_language=str((data.get("voice") or {}).get("language", "pt-BR")),
        vault=_resolve_root(root, (data.get("brain") or {}).get("vault", "cerebro")),
        review_hour=int((data.get("brain") or {}).get("review_hour", 21)),
        morning_hour=int((data.get("brain") or {}).get("morning_hour", 8)),
        morning_minute=int((data.get("brain") or {}).get("morning_minute", 30)),
        radar_tarefa=_flag(radar, "tarefa"),
        radar_disco=_flag(radar, "disco"),
        radar_email=_flag(radar, "email"),
        radar_agenda=_flag(radar, "agenda"),
        radar_whatsapp=_flag(radar, "whatsapp"),
        calendar_ics=str(_resolve_root(root, ics)) if ics else "",
    )


def _flag(section: dict, name: str) -> bool:
    value = section.get(name, True)
    if isinstance(value, str):
        return value.strip().casefold() not in {"0", "false", "nao", "não", "off"}
    return bool(value)


def _resolve_root(project: Path, item: object) -> Path:
    path = Path(str(item))
    if not path.is_absolute():
        path = project / path
    return path.resolve()
