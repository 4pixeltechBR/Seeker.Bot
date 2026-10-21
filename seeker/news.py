"""Notícias das 7h30 e das 19h30. Sem fonte, não manda nada."""

from __future__ import annotations

from datetime import datetime

from seeker.skills.last30 import gather

TOPICS = (
    ("Inteligência artificial local", "local AI"),
    ("Comércio", "small business"),
    ("4Pixel", "web design agency"),
)
SLOTS = ((7, 30), (19, 30))


def news_slot(now: datetime) -> str | None:
    """A edição da vez. Depois das 19h30 vale a da noite, senão a da manhã."""
    day = now.date().isoformat()
    if (now.hour, now.minute) >= (19, 30):
        return f"{day}_1930"
    if (now.hour, now.minute) >= (7, 30):
        return f"{day}_0730"
    return None


def news_digest(fetch, now: datetime) -> str:
    blocks = []
    for label, query in TOPICS:
        hits, _notes = gather(fetch, query, now)
        if not hits:
            continue
        lines = [label]
        for item in hits[:2]:
            lines.append(f"- {item['title']}")
            lines.append(f"  {item['url']}")
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    return "Notícias\n\n" + "\n\n".join(blocks)
