"""Cartão das 8h: tarefas de hoje e a lição de ontem. Sem isso, fica quieto."""

from __future__ import annotations

from datetime import datetime, timedelta

from seeker.brain import Brain
from seeker.schedule import TZ
from seeker.store import Store


def morning_text(store: Store, brain: Brain, now: datetime) -> str:
    now = now.astimezone(TZ)
    tasks = _today(store, now)
    lessons = _yesterday(brain, now)
    parts = []
    if tasks:
        shown = tasks[:4]
        body = ". ".join(shown)
        extra = len(tasks) - len(shown)
        if extra:
            body += f". E mais {extra}."
        parts.append("Hoje: " + body + ".")
    if lessons:
        parts.append("De ontem: " + " | ".join(lessons) + ".")
    return " ".join(parts)


def _today(store: Store, now: datetime) -> list[str]:
    lines = []
    for task in store.pending_tasks():
        due = datetime.fromisoformat(task["due_at"]).astimezone(TZ)
        if due.date() != now.date():
            continue
        lines.append(f"{task['title']} às {due.strftime('%H:%M')}")
    return lines


def _yesterday(brain: Brain, now: datetime) -> list[str]:
    path = brain.root / "licoes" / f"{(now.date() - timedelta(days=1)).isoformat()}.md"
    if not path.exists():
        return []
    lessons = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("- "):
            continue
        lesson = line[2:].strip()
        if lesson:
            lessons.append(lesson)
    return lessons[:3]
