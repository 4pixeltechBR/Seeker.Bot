"""Uma curiosidade por dia, a partir do que foi feito ontem. Sem fonte, fica quieto."""

from __future__ import annotations

from datetime import datetime, timedelta

from seeker.brain import Brain
from seeker.skills.last30 import gather


def curiosity_slot(now: datetime) -> str | None:
    if (now.hour, now.minute) >= (18, 0):
        return now.date().isoformat()
    return None


def curiosity_question(brain: Brain, now: datetime) -> str:
    day = (now.date() - timedelta(days=1)).isoformat()
    bits = []
    diary = brain.root / "diario" / f"{day}.md"
    lesson = brain.root / "licoes" / f"{day}.md"
    for path, marker in ((diary, "Pessoa:"), (lesson, "- ")):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if marker not in line:
                continue
            text = line.split(marker, 1)[1].strip()
            if len(text) >= 20:
                bits.append(" ".join(text.split()))
    if not bits:
        return ""
    return max(bits, key=len)[:80]


def curiosity_text(fetch, brain: Brain, now: datetime) -> str:
    question = curiosity_question(brain, now)
    if not question:
        return ""
    hits, _notes = gather(fetch, question, now)
    if not hits:
        return ""
    item = hits[0]
    return f"Curiosidade\n\nOntem: {question}\n- {item['title']}\n  {item['url']}"
