"""Avisa quando um disco passa de 95%. Só C, D, E, F e H. Sem varrer arquivo."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta

DISKS = ("C", "D", "E", "F", "H")
LIMIT = 95.0
EVERY = timedelta(hours=6)


def disk_percent(letter: str) -> float | None:
    try:
        usage = shutil.disk_usage(f"{letter}:\\")
    except OSError:
        return None
    if usage.total <= 0:
        return None
    return usage.used * 100 / usage.total


def disk_alerts(read=disk_percent) -> list[str]:
    lines = []
    for letter in DISKS:
        percent = read(letter)
        if percent is None or percent <= LIMIT:
            continue
        lines.append(f"Disco {letter}: está em {round(percent)}%.")
    return lines


def disk_due(store, now: datetime) -> bool:
    raw = store.get_setting("disk_check_at", "")
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=now.tzinfo)
    return now - last >= EVERY


def mark_disk(store, now: datetime) -> None:
    store.set_setting("disk_check_at", now.isoformat(timespec="minutes"))
