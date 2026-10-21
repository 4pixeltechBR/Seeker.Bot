"""Às 22h, o que mudou de ferramenta, modelo e biblioteca. Sem fonte, não manda nada."""

from __future__ import annotations

from datetime import datetime

from seeker.skills.last30 import gather

TOPICS = (
    ("Modelos", "new LLM model"),
    ("Ferramentas", "AI developer tool"),
    ("Bibliotecas", "open source library release"),
)
KEEP = {"Hacker News", "GitHub"}


def scout_slot(now: datetime) -> str | None:
    if (now.hour, now.minute) >= (22, 0):
        return now.date().isoformat()
    return None


def scout_digest(fetch, now: datetime) -> str:
    blocks = []
    for label, query in TOPICS:
        hits, _notes = gather(fetch, query, now, days=1)
        chosen = [item for item in hits if item["source"] in KEEP][:1]
        if not chosen:
            continue
        item = chosen[0]
        blocks.append(f"{label}\n- {item['title']}\n  {item['url']}")
    if not blocks:
        return ""
    return "Tech scout\n\n" + "\n\n".join(blocks)
