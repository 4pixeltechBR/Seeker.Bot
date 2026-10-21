"""WhatsApp só pelo aviso que o Windows já mostrou. Sem envio e sem grupo."""

from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

WINDOWS_EPOCH = 11644473600


def default_db() -> Path:
    return Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Notifications" / "wpndatabase.db"


def read_toasts(path: Path | None = None, now: datetime | None = None) -> list[dict]:
    """Avisos recentes do aplicativo WhatsApp. Falha ou ausência vira lista vazia."""
    file = path or default_db()
    if not file.is_file():
        return []
    moment = now or datetime.now(timezone.utc)
    try:
        uri = "file:" + str(file).replace("\\", "/") + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            rows = conn.execute(
                """
                SELECT Notification.Id, Notification.Payload, Notification.ArrivalTime
                FROM Notification
                JOIN NotificationHandler ON NotificationHandler.RecordId = Notification.HandlerId
                WHERE instr(lower(NotificationHandler.PrimaryId), 'whatsapp') > 0
                ORDER BY Notification.ArrivalTime DESC
                """
            ).fetchall()
    except sqlite3.Error:
        return []
    found = []
    for notice_id, payload, arrival in rows:
        when = _arrival(arrival)
        if when is not None and moment.astimezone(timezone.utc) - when > timedelta(hours=36):
            continue
        item = parse_toast(notice_id, payload)
        if item is not None:
            found.append(item)
    return found[:8]


def parse_toast(notice_id: object, payload: object) -> dict | None:
    text = _xml(payload)
    if not text or "<toast" not in text.lower():
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    parts = ["".join(node.itertext()).strip() for node in root.iter() if _tag(node) == "text"]
    parts = [part for part in parts if part]
    if len(parts) < 2:
        return None
    title, body = parts[0], parts[1]
    if is_group(title, body):
        return None
    return {"id": str(notice_id), "title": title[:80], "body": body[:140]}


def is_group(title: str, body: str) -> bool:
    speaker, sep, rest = body.partition(":")
    if not sep or not rest.strip() or len(speaker.strip()) > 40:
        return False
    return speaker.strip().casefold() != title.strip().casefold()


def _xml(payload: object) -> str:
    if isinstance(payload, bytes):
        return payload.decode("utf-8", "replace")
    return str(payload or "")


def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def _arrival(value: object) -> datetime | None:
    if not isinstance(value, int) or value < 10**16:
        return None
    unix = value / 10_000_000 - WINDOWS_EPOCH
    try:
        return datetime.fromtimestamp(unix, timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
