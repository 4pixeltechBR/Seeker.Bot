"""Uma sugestão por vez, só quando existe tarefa real. Dispensar vale até o dia acabar."""

from __future__ import annotations

from datetime import datetime, timedelta

from seeker.schedule import TZ
from seeker.store import Store


def ensure_suggestion(store: Store, now: datetime) -> None:
    now = now.astimezone(TZ)
    if store.open_suggestions():
        return
    day = now.date().isoformat()
    pending = []
    soon = []
    horizon = now + timedelta(hours=3)
    for task in store.pending_tasks():
        due = datetime.fromisoformat(task["due_at"])
        if due <= now:
            pending.append(task)
        elif due <= horizon:
            soon.append(task)
    if pending:
        _offer(store, "overdue", day, _overdue_text(pending))
        return
    if soon:
        _offer(store, "soon", day, _soon_text(soon[0]))


def _offer(store: Store, kind: str, day: str, text: str) -> None:
    if store.suggestion_blocked(kind, day):
        return
    store.add_suggestion(kind, text, day)


def _overdue_text(tasks: list[dict]) -> str:
    first = tasks[0]["title"]
    if len(tasks) == 1:
        return f"{first} já passou da hora. Quer que eu leia o que falta?"
    return f"{first} e mais {len(tasks) - 1} já passaram da hora. Quer que eu leia a lista?"


def _soon_text(task: dict) -> str:
    due = datetime.fromisoformat(task["due_at"]).astimezone(TZ)
    return f"{task['title']} é às {due.strftime('%H:%M')}. Quer ver o resto do dia?"
