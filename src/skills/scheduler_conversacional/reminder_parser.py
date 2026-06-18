"""
Scheduler Conversacional — Reminder Parser (NL → one-shot)

Interpreta lembretes em linguagem natural PT-BR e devolve um horário absoluto
(no fuso da tarefa) + o texto do lembrete. Suporta:

  - "me lembre daqui a 5 min para ..."     → agora + 5 minutos
  - "em 30 minutos ..."                     → agora + 30 minutos
  - "daqui a 2 horas ..."                   → agora + 2 horas
  - "me avisa em 1h ..."                    → agora + 1 hora
  - "amanhã às 9h ..." / "amanhã às 14:30"  → próximo dia no horário
  - "hoje às 18h ..."                       → hoje no horário (ou amanhã se já passou)
  - "às 7h ..." / "às 7:30 ..."             → próxima ocorrência do horário

Retorna None quando não há expressão temporal reconhecível — nesse caso o
chamador deve seguir o fluxo normal (pipeline cognitivo).
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pytz

DEFAULT_TZ = "America/Sao_Paulo"

# Gatilho de intenção de lembrete (rápido, antes de tentar parsear horário).
REMINDER_INTENT = re.compile(
    r"\bme\s+lembr[ae]\b|\bme\s+avis[ae]\b|\blembrete\b|\bn[ãa]o\s+(me\s+)?deixa\s+(eu\s+)?esquecer\b",
    re.IGNORECASE,
)

# Expressões temporais relativas: "daqui a 5 min", "em 30 minutos", "daqui a 2 horas"
_REL = re.compile(
    r"(?:daqui\s+a|daqui|em)\s+(\d+)\s*"
    r"(min(?:uto)?s?|m\b|h\b|hora?s?|seg(?:undo)?s?|s\b)",
    re.IGNORECASE,
)

# Expressões de horário absoluto: "amanhã às 9h", "hoje às 14:30", "às 7h"
_ABS = re.compile(
    r"\b(amanh[ãa]|hoje|depois\s+de\s+amanh[ãa])?\s*"
    r"(?:[àa]s?\s+)(\d{1,2})(?:[:h](\d{2}))?\s*(?:h(?:oras?)?)?",
    re.IGNORECASE,
)


@dataclass
class ReminderSpec:
    """Resultado do parse de um lembrete em linguagem natural."""

    run_at_utc: datetime          # horário de disparo (UTC, naive)
    run_at_local: datetime        # horário de disparo (fuso local, aware)
    body: str                     # texto do lembrete (sem a parte temporal)
    title: str                    # título curto para a tarefa


def _strip_temporal(text: str) -> str:
    """Remove expressões temporais e verbos de lembrete, sobrando o assunto."""
    # Verbos de lembrete primeiro (substitui por espaço para não colar tokens)
    out = re.sub(
        r"me\s+lembr[ae]r?|me\s+avis[ae]|lembrete|"
        r"n[ãa]o\s+(me\s+)?deixa\s+(eu\s+)?esquecer",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    out = _REL.sub(" ", out)
    out = _ABS.sub(" ", out)
    # Conectivos iniciais soltos ("de", "para", "que", "pra", "de que")
    out = re.sub(r"^\s*(de|para|pra|que|sobre|:|,|-)\s+", "", out.strip(), flags=re.IGNORECASE)
    out = re.sub(r"\s{2,}", " ", out).strip(" .,-:")
    return out


def parse_reminder(text: str, now: Optional[datetime] = None, tz_name: str = DEFAULT_TZ) -> Optional[ReminderSpec]:
    """
    Tenta interpretar um lembrete one-shot a partir de texto livre.

    Args:
        text: mensagem do usuário
        now: instante de referência (default: agora). Aware ou naive-UTC.
        tz_name: fuso da tarefa

    Returns:
        ReminderSpec se um horário foi reconhecido, senão None.
    """
    if not text or not text.strip():
        return None

    tz = pytz.timezone(tz_name)
    if now is None:
        now_local = datetime.now(tz)
    elif now.tzinfo is None:
        now_local = pytz.UTC.localize(now).astimezone(tz)
    else:
        now_local = now.astimezone(tz)

    target_local: Optional[datetime] = None

    # 1) Relativo ("daqui a N min/horas/seg")
    m = _REL.search(text)
    if m:
        qty = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("h"):
            delta = timedelta(hours=qty)
        elif unit.startswith("s"):
            delta = timedelta(seconds=max(qty, 60))  # mínimo 60s (cadência do poll)
        else:  # minutos (min, m)
            delta = timedelta(minutes=qty)
        target_local = now_local + delta

    # 2) Absoluto ("amanhã às 9h", "hoje às 14:30", "às 7h")
    if target_local is None:
        m = _ABS.search(text)
        if m:
            day_word = (m.group(1) or "").lower()
            hour = int(m.group(2))
            minute = int(m.group(3)) if m.group(3) else 0
            if hour > 23 or minute > 59:
                return None
            target_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if "depois" in day_word:
                target_local += timedelta(days=2)
            elif "amanh" in day_word:
                target_local += timedelta(days=1)
            elif day_word == "hoje":
                if target_local <= now_local:
                    target_local += timedelta(days=1)
            else:
                # Sem palavra de dia: próxima ocorrência do horário
                if target_local <= now_local:
                    target_local += timedelta(days=1)

    if target_local is None:
        return None

    # Garante que está no futuro
    if target_local <= now_local:
        target_local = now_local + timedelta(minutes=1)

    body = _strip_temporal(text) or "Lembrete"
    title = (body[:40] + "…") if len(body) > 40 else body

    run_at_utc = target_local.astimezone(pytz.UTC).replace(tzinfo=None)

    return ReminderSpec(
        run_at_utc=run_at_utc,
        run_at_local=target_local,
        body=body,
        title=title,
    )
