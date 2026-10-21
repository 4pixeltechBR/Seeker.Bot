"""Agenda em português. O texto da pessoa vira um horário com fuso de São Paulo."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from seeker.store import Store

TZ = ZoneInfo("America/Sao_Paulo")

WEEKDAYS = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "domingo": 6,
}
WEEKDAY_NAME = (
    "segunda",
    "terça",
    "quarta",
    "quinta",
    "sexta",
    "sábado",
    "domingo",
)
MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
HOUR_WORDS = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
    "vinte": 20,
    "vinte e um": 21,
    "vinte e uma": 21,
    "vinte e dois": 22,
    "vinte e duas": 22,
    "vinte e tres": 23,
}
NUMBER_WORDS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "quinze": 15,
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "quarenta e cinco": 45,
    "cinquenta": 50,
}


class ParseError(Exception):
    pass


@dataclass(frozen=True)
class ParsedWhen:
    due: datetime
    repeat: str
    label: str


def parse_when(text: str, now: datetime) -> ParsedWhen:
    now = now.astimezone(TZ)
    folded = _fold(text)
    if not folded:
        raise ParseError("Falta o dia e a hora.")
    relative = _relative_delta(folded)
    if relative is not None:
        due = now + relative
        return ParsedWhen(due=due, repeat="none", label=_label(due, "none"))
    repeat = _repeat(folded)
    clock = _clock(folded)
    if clock is None:
        raise ParseError("Falta a hora. Diga, por exemplo, amanhã às 9h.")
    due = _date_for(folded, now, clock, repeat)
    return ParsedWhen(due=due, repeat=repeat, label=_label(due, repeat))


def advance(due: datetime, repeat: str, now: datetime) -> datetime | None:
    if repeat == "none":
        return None
    cursor = due.astimezone(TZ)
    now = now.astimezone(TZ)
    while cursor <= now:
        if repeat == "daily":
            cursor += timedelta(days=1)
        elif repeat == "weekdays":
            cursor += timedelta(days=1)
            while cursor.weekday() >= 5:
                cursor += timedelta(days=1)
        elif repeat == "weekly":
            cursor += timedelta(weeks=1)
        else:
            return None
    return cursor


def in_quiet(start: time | None, end: time | None, moment: datetime) -> bool:
    if start is None or end is None or start == end:
        return False
    current = moment.astimezone(TZ).time().replace(second=0, microsecond=0)
    if start < end:
        return start <= current < end
    return current >= start or current < end


def parse_quiet(text: str) -> tuple[time, time] | None:
    folded = _fold(text)
    if any(word in folded for word in ("nenhum", "desligar", "tirar", "sem silencio")):
        return None
    match = re.search(r"(\d{1,2})\s*(?:h|:)?\s*(?:as|a|ate|-)\s*(\d{1,2})\s*h?", folded)
    if not match:
        raise ParseError("Diga o intervalo, por exemplo 22h às 7h.")
    start = time(int(match.group(1)) % 24, 0)
    end = time(int(match.group(2)) % 24, 0)
    return start, end


def format_when(due: datetime, repeat: str) -> str:
    return _label(due.astimezone(TZ), repeat)


class TaskBook:
    def __init__(self, store: Store, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(TZ))

    def schedule(self, title: str, when_text: str) -> str:
        title = " ".join((title or "").split())
        if not title:
            return "Falta o nome da tarefa."
        try:
            parsed = parse_when(when_text, self.clock())
        except ParseError as exc:
            return str(exc)
        task = self.store.add_task(title, parsed.due.isoformat(timespec="minutes"), parsed.repeat)
        return f"Agendado ({task['id']}): {title}. {parsed.label}."

    def list_pending(self) -> str:
        now = self.clock()
        rows = self.store.pending_tasks()
        if not rows:
            return "Nada marcado."
        lines = []
        for task in rows:
            due = datetime.fromisoformat(task["due_at"])
            mark = "atrasada" if due <= now else "pendente"
            lines.append(f"{task['id']} | {mark} | {format_when(due, task['repeat'])} | {task['title']}")
        return "\n".join(lines)

    def complete(self, query: str) -> str:
        task, error = self._resolve(query)
        if error:
            return error
        self.store.update_task(task["id"], status="done")
        nxt = advance(datetime.fromisoformat(task["due_at"]), task["repeat"], self.clock())
        if nxt is not None:
            created = self.store.add_task(task["title"], nxt.isoformat(timespec="minutes"), task["repeat"])
            return f"Concluí esta. A próxima fica para {format_when(nxt, task['repeat'])} ({created['id']})."
        return f"Concluí: {task['title']}."

    def cancel(self, query: str) -> str:
        task, error = self._resolve(query)
        if error:
            return error
        self.store.update_task(task["id"], status="cancelled")
        return f"Cancelei: {task['title']}."

    def snooze(self, query: str, minutes: int) -> str:
        task, error = self._resolve(query)
        if error:
            return error
        minutes = max(1, min(int(minutes or 10), 24 * 60))
        due = self.clock().astimezone(TZ) + timedelta(minutes=minutes)
        self.store.update_task(task["id"], due_at=due.isoformat(timespec="minutes"), status="pending")
        return f"Adiei {task['title']} para {format_when(due, 'none')}."

    def quiet_hours(self, text: str) -> str:
        try:
            parsed = parse_quiet(text)
        except ParseError as exc:
            return str(exc)
        if parsed is None:
            self.store.set_setting("quiet_start", "")
            self.store.set_setting("quiet_end", "")
            return "Sem horário de silêncio."
        start, end = parsed
        self.store.set_setting("quiet_start", start.strftime("%H:%M"))
        self.store.set_setting("quiet_end", end.strftime("%H:%M"))
        return f"Silêncio de {start.strftime('%H:%M')} até {end.strftime('%H:%M')}."

    def _resolve(self, query: str) -> tuple[dict | None, str | None]:
        text = (query or "").strip().casefold()
        pending = self.store.pending_tasks()
        if not text:
            return None, "Diga qual tarefa."
        by_id = [task for task in pending if task["id"] == text or task["id"].startswith(text)]
        if len(by_id) == 1:
            return by_id[0], None
        hits = [task for task in pending if text in task["title"].casefold()]
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            codes = ", ".join(task["id"] for task in hits)
            return None, f"Achei mais de uma. Use o código: {codes}."
        return None, "Não achei essa tarefa."


class Scheduler:
    def __init__(self, store: Store, on_fire, interval: float = 5.0, clock=None):
        import threading

        self.store = store
        self.on_fire = on_fire
        self.interval = interval
        self.clock = clock or (lambda: datetime.now(TZ))
        self.on_review = None
        self.on_routine = None
        self.on_morning = None
        self.on_disk = None
        self.on_news = None
        self.on_mail = None
        self.on_scout = None
        self.on_watch = None
        self.on_curiosity = None
        self.review_hour = 21
        self.morning_hour = 8
        self.morning_minute = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import threading

        self._thread = threading.Thread(target=self._loop, name="seeker-agenda", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.tick()

    def tick(self) -> list[str]:
        from seeker.suggest import ensure_suggestion

        now = self.clock().astimezone(TZ)
        self._maybe_disk(now)
        self._maybe_news(now)
        self._maybe_mail(now)
        self._maybe_scout(now)
        self._maybe_curiosity(now)
        self._maybe_morning(now)
        self._maybe_review(now)
        if _quiet_now(self.store, now):
            ensure_suggestion(self.store, now)
            return []
        self._maybe_watch(now)
        fired = []
        for task in self.store.pending_tasks():
            due = datetime.fromisoformat(task["due_at"])
            if due > now:
                continue
            nxt = advance(due, task["repeat"], now)
            if nxt is None:
                self.store.update_task(task["id"], status="done", last_fired_at=now.isoformat(timespec="minutes"))
            else:
                self.store.update_task(
                    task["id"],
                    due_at=nxt.isoformat(timespec="minutes"),
                    last_fired_at=now.isoformat(timespec="minutes"),
                )
            text = f"Agora: {task['title']}"
            self.store.add_notice(text)
            fired.append(text)
            self.on_fire(text)
        ensure_suggestion(self.store, now)
        self._fire_routines(now)
        return fired

    def _fire_routines(self, now: datetime) -> None:
        from seeker.routine import RoutineBook

        if self.on_routine is None:
            return
        book = RoutineBook(self.store, clock=lambda: now)
        for routine in book.due(now):
            try:
                self.on_routine(routine)
            except Exception:
                continue
            book.mark_ran(routine, now)

    def _maybe_watch(self, now: datetime) -> None:
        if self.on_watch is None:
            return
        try:
            self.on_watch(now)
        except Exception:
            return

    def _maybe_disk(self, now: datetime) -> None:
        from seeker.disk import disk_due, mark_disk

        if self.on_disk is None or not disk_due(self.store, now):
            return
        mark_disk(self.store, now)
        try:
            self.on_disk(now)
        except Exception:
            return

    def _maybe_news(self, now: datetime) -> None:
        from seeker.news import news_slot

        if self.on_news is None or _quiet_now(self.store, now):
            return
        slot = news_slot(now)
        if slot is None:
            return
        key = "news_" + slot
        if self.store.get_setting(key) == "done":
            return
        try:
            self.on_news(now)
        except Exception:
            return
        self.store.set_setting(key, "done")
        if slot.endswith("1930"):
            self.store.set_setting("news_" + slot.replace("1930", "0730"), "done")

    def _maybe_scout(self, now: datetime) -> None:
        from seeker.scout import scout_slot

        if self.on_scout is None or _quiet_now(self.store, now):
            return
        slot = scout_slot(now)
        if slot is None:
            return
        key = "scout_" + slot
        if self.store.get_setting(key) == "done":
            return
        try:
            self.on_scout(now)
        except Exception:
            return
        self.store.set_setting(key, "done")

    def _maybe_curiosity(self, now: datetime) -> None:
        from seeker.curiosity import curiosity_slot

        if self.on_curiosity is None or _quiet_now(self.store, now):
            return
        slot = curiosity_slot(now)
        if slot is None:
            return
        key = "curiosity_" + slot
        if self.store.get_setting(key) == "done":
            return
        try:
            self.on_curiosity(now)
        except Exception:
            return
        self.store.set_setting(key, "done")

    def _maybe_mail(self, now: datetime) -> None:
        from seeker.mail import mail_slot

        if self.on_mail is None or _quiet_now(self.store, now):
            return
        slot = mail_slot(now)
        if slot is None:
            return
        key = "mail_" + slot
        if self.store.get_setting(key) == "done":
            return
        try:
            self.on_mail(now)
        except Exception:
            return
        self.store.set_setting(key, "done")
        if slot.endswith("2100"):
            self.store.set_setting("mail_" + slot.replace("2100", "0900"), "done")

    def _maybe_morning(self, now: datetime) -> None:
        if self.on_morning is None or (now.hour, now.minute) < (self.morning_hour, self.morning_minute):
            return
        if _quiet_now(self.store, now):
            return
        key = "morning_" + now.date().isoformat()
        if self.store.get_setting(key) == "done":
            return
        try:
            self.on_morning(now)
        except Exception:
            return
        self.store.set_setting(key, "done")

    def _maybe_review(self, now: datetime) -> None:
        if self.on_review is None or now.hour < self.review_hour:
            return
        key = "review_" + now.date().isoformat()
        if self.store.get_setting(key) == "done":
            return
        try:
            self.on_review(now)
        except Exception:
            return
        self.store.set_setting(key, "done")


def _quiet_now(store: Store, now: datetime) -> bool:
    start = _parse_hhmm(store.get_setting("quiet_start"))
    end = _parse_hhmm(store.get_setting("quiet_end"))
    return in_quiet(start, end, now)


def _parse_hhmm(value: str) -> time | None:
    if not value or ":" not in value:
        return None
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    without = "".join(char for char in normalized if not unicodedata.combining(char))
    without = without.replace("-", " ")
    return " ".join(without.split())


def _number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def _relative_delta(folded: str) -> timedelta | None:
    match = re.search(
        r"\b(?:daqui a|em)\s+(\d+|um|uma|dois|duas|tres|quatro|cinco|dez|quinze|vinte|trinta|quarenta|cinquenta)\s+(minutos|minuto|horas|hora)\b",
        folded,
    )
    if not match:
        return None
    amount = _number(match.group(1))
    if amount is None:
        return None
    if match.group(2).startswith("hora"):
        return timedelta(hours=amount)
    return timedelta(minutes=amount)


def _repeat(folded: str) -> str:
    if re.search(r"\b(todo dia|todos os dias|diariamente)\b", folded):
        return "daily"
    if re.search(r"\bdias uteis\b|\bdia util\b", folded):
        return "weekdays"
    if re.search(r"\b(toda|todo|todas)\s+(segunda|terca|quarta|quinta|sexta|sabado|domingo)\b", folded):
        return "weekly"
    return "none"


def _clock(folded: str) -> time | None:
    if re.search(r"\bmeia noite\b", folded):
        return time(0, 0)
    if re.search(r"\bmeio dia\b", folded):
        return time(12, 0)
    match = re.search(r"\b(\d{1,2})\s*:\s*(\d{2})\b", folded)
    if match:
        return _safe_time(int(match.group(1)), int(match.group(2)), folded)
    match = re.search(r"\b(\d{1,2})\s*h\s*(\d{2})\b", folded)
    if match:
        return _safe_time(int(match.group(1)), int(match.group(2)), folded)
    match = re.search(r"\b(\d{1,2})\s*h\b", folded)
    if match:
        return _safe_time(int(match.group(1)), 0, folded)
    match = re.search(r"\b(\d{1,2})\s+da\s+(manha|tarde|noite)\b", folded)
    if match:
        return _safe_time(int(match.group(1)), 0, folded)
    match = re.search(r"\bas\s+(\d{1,2})\b", folded)
    if match:
        return _safe_time(int(match.group(1)), 0, folded)
    for words, hour in sorted(HOUR_WORDS.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = rf"\b{re.escape(words)}\b(?:\s+horas|\s+hora)?"
        match = re.search(pattern, folded)
        if not match:
            continue
        minute = 0
        tail = folded[match.end() :]
        if tail.startswith(" e meia"):
            minute = 30
        elif tail.startswith(" e quinze"):
            minute = 15
        elif tail.startswith(" e trinta"):
            minute = 30
        elif tail.startswith(" e quarenta e cinco"):
            minute = 45
        return _safe_time(hour, minute, folded)
    if re.search(r"\bde manha\b|\bmanha\b", folded):
        return time(9, 0)
    if re.search(r"\bde tarde\b|\btarde\b", folded):
        return time(14, 0)
    if re.search(r"\bde noite\b|\bnoite\b", folded):
        return time(20, 0)
    return None


def _safe_time(hour: int, minute: int, folded: str) -> time | None:
    if minute > 59 or hour > 23:
        return None
    if hour < 12 and re.search(r"\b(da tarde|de tarde|da noite|de noite)\b", folded):
        hour += 12
    return time(hour, minute)


def _date_for(folded: str, now: datetime, clock: time, repeat: str) -> datetime:
    if repeat == "daily":
        due = _combine(now, clock)
        if due <= now:
            due += timedelta(days=1)
        return due
    if repeat == "weekdays":
        due = _combine(now, clock)
        if due <= now:
            due += timedelta(days=1)
        while due.weekday() >= 5:
            due += timedelta(days=1)
        return due
    weekday = _weekday_in(folded)
    if weekday is not None:
        force = "que vem" in folded and weekday == now.weekday()
        return _next_weekday(now, weekday, clock, force)
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", folded)
    if match:
        return _on_date(now, int(match.group(1)), int(match.group(2)), int(match.group(3)), clock, "data")
    match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", folded)
    if match:
        year = int(match.group(3)) if match.group(3) else now.year
        if year < 100:
            year += 2000
        return _on_date(now, year, int(match.group(2)), int(match.group(1)), clock, "data")
    if "depois de amanha" in folded:
        return _combine(now + timedelta(days=2), clock)
    if "amanha" in folded:
        return _combine(now + timedelta(days=1), clock)
    if "hoje" in folded:
        due = _combine(now, clock)
        if due <= now:
            raise ParseError("Esse horário de hoje já passou.")
        return due
    due = _combine(now, clock)
    if due <= now:
        due += timedelta(days=1)
    return due


def _weekday_in(folded: str) -> int | None:
    for name, index in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", folded):
            return index
    return None


def _next_weekday(now: datetime, weekday: int, clock: time, force_next_week: bool) -> datetime:
    days = (weekday - now.weekday()) % 7
    candidate = _combine(now + timedelta(days=days), clock)
    if days == 0 and (force_next_week or candidate <= now):
        candidate += timedelta(days=7)
    return candidate


def _on_date(now: datetime, year: int, month: int, day: int, clock: time, what: str) -> datetime:
    try:
        due = datetime(year, month, day, clock.hour, clock.minute, tzinfo=TZ)
    except ValueError as exc:
        raise ParseError("Essa data não existe.") from exc
    if due <= now:
        raise ParseError(f"Esse horário dessa {what} já passou.")
    return due


def _combine(day: datetime, clock: time) -> datetime:
    return day.astimezone(TZ).replace(hour=clock.hour, minute=clock.minute, second=0, microsecond=0)


def _label(due: datetime, repeat: str) -> str:
    due = due.astimezone(TZ)
    when = (
        f"{WEEKDAY_NAME[due.weekday()]}, {due.day} de {MONTHS[due.month - 1]}, "
        f"às {due.strftime('%H:%M')}"
    )
    prefix = {
        "none": "",
        "daily": "todo dia, a partir de ",
        "weekly": "toda semana, a partir de ",
        "weekdays": "nos dias úteis, a partir de ",
    }[repeat]
    return prefix + when
