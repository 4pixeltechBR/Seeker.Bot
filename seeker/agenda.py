"""Agenda em leitura. Um arquivo ICS entra no Radar. Escrever fica para a tarefa local, depois do sim."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from seeker.schedule import TZ


def events_on(text: str, now: datetime) -> list[dict]:
    """Eventos com hora no dia de now. Dia inteiro fica de fora."""
    now = now.astimezone(TZ)
    found = []
    for block in _events(text or ""):
        start = _start(block, now)
        if start is None or start.astimezone(TZ).date() != now.date():
            continue
        title = _unescape(block.get("SUMMARY", "")).strip() or "Compromisso"
        uid = block.get("UID", "").strip() or f"{title}-{start.isoformat(timespec='minutes')}"
        found.append(
            {
                "uid": uid,
                "title": title,
                "start": start.astimezone(TZ),
                "description": _unescape(block.get("DESCRIPTION", "")).strip(),
            }
        )
    return found


def read_ics(path: str, now: datetime) -> list[dict]:
    if not path:
        return []
    file = Path(path)
    if not file.is_file():
        return []
    try:
        return events_on(file.read_text(encoding="utf-8"), now)
    except OSError:
        return []


def _events(text: str) -> list[dict]:
    blocks = []
    current: dict[str, str] | None = None
    for raw in _unfold(text).splitlines():
        line = raw.strip()
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                blocks.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        name = key.split(";", 1)[0].upper()
        if name == "DTSTART":
            current["DTSTART"] = value.strip()
            current["DTSTART_RAW"] = key
        else:
            current[name] = value.strip()
    return blocks


def _unfold(text: str) -> str:
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if lines and raw.startswith((" ", "\t")):
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return "\n".join(lines)


def _start(block: dict, now: datetime) -> datetime | None:
    raw_key = block.get("DTSTART_RAW", "")
    if "VALUE=DATE" in raw_key.upper() and "VALUE=DATE-TIME" not in raw_key.upper():
        return None
    value = block.get("DTSTART", "")
    if not value or len(value) < 15:
        return None
    try:
        parsed = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    if value.endswith("Z"):
        return parsed.replace(tzinfo=timezone.utc)
    zone = _tzid(raw_key) or now.tzinfo or TZ
    return parsed.replace(tzinfo=zone)


def _tzid(raw_key: str) -> ZoneInfo | None:
    for part in raw_key.split(";")[1:]:
        if part.upper().startswith("TZID="):
            try:
                return ZoneInfo(part.split("=", 1)[1])
            except Exception:
                return None
    return None


def _unescape(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def within(start: datetime, now: datetime, hours: int = 4) -> bool:
    now = now.astimezone(TZ)
    start = start.astimezone(TZ)
    return timedelta(hours=-1) <= start - now <= timedelta(hours=hours)
