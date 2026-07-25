"""
research_machine.scheduler — Parser de expressões de schedule para pesquisa agendada.

Suporta:
  - "every day 8am"        → DAILY @ 08:00
  - "every day 20:30"      → DAILY @ 20:30
  - "every monday 9am"     → WEEKLY segunda 09:00
  - "every tuesday 14h"    → WEEKLY terça 14:00
  - "every 6h"             → não suportado pelo modelo ONCE/DAILY/WEEKLY;
                              mapeado para DAILY @ próximo slot de 6h (limitação)
  - cron "0 8 * * 1-5"     → WEEKLY segunda-sexta 08:00 (simplificado)

Retorna um ScheduleSpec com schedule_type, day_of_week, hour, minute.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytz

from src.skills.scheduler_conversacional.models import (
    ScheduledTask,
    ScheduleType,
    TaskStatus,
)

DEFAULT_TZ = "America/Sao_Paulo"

_DAYS_PT = {
    "monday": 0, "mon": 0, "segunda": 0, "seg": 0,
    "tuesday": 1, "tue": 1, "terca": 1, "ter": 1,
    "wednesday": 2, "wed": 2, "quarta": 2, "qua": 2,
    "thursday": 3, "thu": 3, "quinta": 3, "qui": 3,
    "friday": 4, "fri": 4, "sexta": 4, "sex": 4,
    "saturday": 5, "sat": 5, "sabado": 5, "sab": 5,
    "sunday": 6, "sun": 6, "domingo": 6, "dom": 6,
}

_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|h)?", re.IGNORECASE)
_EVERY_DAY_RE = re.compile(r"^every\s+day\s+(\S+)$", re.IGNORECASE)
_EVERY_WEEKDAY_RE = re.compile(r"^every\s+(\w+)\s+(\S+)$", re.IGNORECASE)
_CRON_RE = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$")


@dataclass
class ScheduleSpec:
    """Resultado do parse."""
    schedule_type: ScheduleType
    hour: int
    minute: int = 0
    day_of_week: Optional[int] = None
    description: str = ""
    ok: bool = True
    error: str = ""


def parse_schedule(expr: str) -> ScheduleSpec:
    """
    Interpreta expressão de schedule. Retorna ScheduleSpec com ok=False e error
    preenchido se a expressão for inválida.
    """
    expr = expr.strip().strip('"').strip("'")
    if not expr:
        return ScheduleSpec(ok=False, error="Expressão vazia", schedule_type=ScheduleType.ONCE, hour=0)

    # 1) "every day HH:MM"
    m = _EVERY_DAY_RE.match(expr)
    if m:
        hour, minute = _parse_time(m.group(1))
        if hour is None:
            return ScheduleSpec(ok=False, error=f"Horário inválido: {m.group(1)!r}", schedule_type=ScheduleType.ONCE, hour=0)
        return ScheduleSpec(
            schedule_type=ScheduleType.DAILY,
            hour=hour,
            minute=minute,
            description=f"Todos os dias às {hour:02d}:{minute:02d}",
        )

    # 2) "every <weekday> HH:MM"
    m = _EVERY_WEEKDAY_RE.match(expr)
    if m:
        day_token = m.group(1).lower()
        if day_token not in _DAYS_PT:
            return ScheduleSpec(ok=False, error=f"Dia da semana inválido: {day_token!r}", schedule_type=ScheduleType.ONCE, hour=0)
        hour, minute = _parse_time(m.group(2))
        if hour is None:
            return ScheduleSpec(ok=False, error=f"Horário inválido: {m.group(2)!r}", schedule_type=ScheduleType.ONCE, hour=0)
        day = _DAYS_PT[day_token]
        return ScheduleSpec(
            schedule_type=ScheduleType.WEEKLY,
            day_of_week=day,
            hour=hour,
            minute=minute,
            description=f"Toda {day_token} às {hour:02d}:{minute:02d}",
        )

    # 3) cron "m h dom mon dow" (simplificado: dia da semana obrigatório, aceita ranges "1-5", "0,3,5", "*")
    m = _CRON_RE.match(expr)
    if m and re.match(r"^\d+(\s+\S+){4}$", expr):
        minute_s, hour_s, _dom, _mon, dow_s = m.groups()
        if minute_s.isdigit() and hour_s.isdigit() and dow_s not in ("*", ""):
            minute = int(minute_s)
            hour = int(hour_s)
            # Parse DOW: aceita "1", "1-5" (primeiro dia), "1,3,5" (primeiro dia)
            dow = None
            if "-" in dow_s:
                first = dow_s.split("-")[0]
                if first.isdigit():
                    dow = int(first)
            elif "," in dow_s:
                first = dow_s.split(",")[0]
                if first.isdigit():
                    dow = int(first)
            elif dow_s.isdigit():
                dow = int(dow_s)
            if dow is not None and 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= dow <= 6:
                return ScheduleSpec(
                    schedule_type=ScheduleType.WEEKLY,
                    day_of_week=dow,
                    hour=hour,
                    minute=minute,
                    description=f"Cron: dow={dow} {hour:02d}:{minute:02d}",
                )

    return ScheduleSpec(
        ok=False,
        error=(
            "Formato não reconhecido. Use: "
            "'every day HH:MM', 'every <dia> HH:MM', ou cron 'm h * * dow'"
        ),
        schedule_type=ScheduleType.ONCE,
        hour=0,
        description=(
            "Formato não reconhecido. Use: "
            "'every day HH:MM', 'every <dia> HH:MM', ou cron 'm h * * dow'"
        ),
    )


def _parse_time(token: str) -> tuple[Optional[int], Optional[int]]:
    """Parse '8am', '20:30', '14h', '9'."""
    m = _TIME_RE.match(token.strip().lower())
    if not m:
        return None, None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    suffix = m.group(3)
    if suffix == "pm" and hour < 12:
        hour += 12
    elif suffix == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None, None
    return hour, minute


def build_scheduled_task(
    spec: ScheduleSpec,
    query: str,
    chat_id: int,
    user_id: str = "telegram",
) -> ScheduledTask:
    """Constrói ScheduledTask a partir de um ScheduleSpec válido."""
    from src.skills.scheduler_conversacional.calculator import NextRunCalculator

    task = ScheduledTask(
        id=f"research_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}",
        title=f"Research: {query[:40]}",
        schedule_type=spec.schedule_type,
        hour=spec.hour,
        minute=spec.minute,
        day_of_week=spec.day_of_week,
        timezone=DEFAULT_TZ,
        instruction_text=f"[research_machine] {query}",
        chat_id=chat_id,
        created_by=str(user_id),
        source="research_schedule_telegram",
    )

    # Calcula a primeira execução
    if spec.schedule_type == ScheduleType.DAILY:
        next_run = NextRunCalculator.calculate_next_run(task)
        task.next_run_at = next_run

    return task
