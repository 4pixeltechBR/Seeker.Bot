"""Revisão do dia: no máximo três frases verificáveis, gravadas no cérebro."""

from __future__ import annotations

from datetime import datetime

from seeker.brain import Brain
from seeker.schedule import TZ
from seeker.store import Store

PROMPT = """Leia o que foi falado hoje. Extraia no máximo 3 ensinamentos estáveis.
Cada ensinamento é uma frase curta, verificável, começando com "- ".
Não invente. Não guarde senha, chave ou segredo. Não repita tarefa de um dia só.
Se não houver ensinamento, responda só: nada.

Conversa:
{talk}
"""


def parse_lessons(text: str) -> list[str]:
    found: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        lesson = line.lstrip("-").strip()
        folded = lesson.casefold()
        if len(lesson) < 12 or len(lesson) > 180:
            continue
        if any(word in folded for word in ("senha", "chave", "token", "api_key", "secret")):
            continue
        if lesson in found:
            continue
        found.append(lesson)
        if len(found) == 3:
            break
    return found


def review_day(store: Store, brain: Brain, complete, when: datetime) -> list[str]:
    when = when.astimezone(TZ)
    talk = _talk_on(store, when)
    if not talk:
        return []
    raw = complete(PROMPT.format(talk=talk[:6000]))
    lessons = parse_lessons(raw or "")
    for lesson in lessons:
        saved = store.add_memory(lesson)
        if saved is not None:
            brain.write_memory(lesson)
        brain.write_lesson(when, lesson)
    if lessons:
        store.add_notice("Revisão do dia: " + " | ".join(lessons))
    else:
        store.add_notice("Revisão do dia: nada novo para guardar.")
    return lessons


def _talk_on(store: Store, when: datetime) -> str:
    lines = []
    day = when.date()
    for message in store.all_messages():
        created = datetime.fromisoformat(message["created_at"]).astimezone(TZ)
        if created.date() != day:
            continue
        who = "Pessoa" if message["role"] == "user" else "Seeker"
        lines.append(f"{who}: {' '.join(message['content'].split())[:500]}")
    return "\n".join(lines[-40:])
