"""Rotina: uma ordem com horário. Na hora, roda leitura e pesquisa. Comando pede licença."""

from __future__ import annotations

from datetime import datetime

from seeker.schedule import ParseError, TZ, advance, format_when, parse_when
from seeker.store import Store


class RoutineBook:
    def __init__(self, store: Store, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(TZ))

    def create(self, instruction: str, when_text: str) -> str:
        instruction = " ".join((instruction or "").split())
        if len(instruction) < 8:
            return "Diga o que a rotina deve fazer."
        try:
            parsed = parse_when(when_text, self.clock())
        except ParseError as exc:
            return str(exc)
        routine = self.store.add_routine(instruction, parsed.due.isoformat(timespec="minutes"), parsed.repeat)
        return f"Rotina ({routine['id']}): {instruction}. {parsed.label}. Leitura e pesquisa rodam sozinhas. Comando no PowerShell continua pedindo licença."

    def list_active(self) -> str:
        rows = self.store.active_routines()
        if not rows:
            return "Nenhuma rotina."
        lines = []
        for routine in rows:
            due = datetime.fromisoformat(routine["due_at"])
            lines.append(f"{routine['id']} | {format_when(due, routine['repeat'])} | {routine['instruction']}")
        return "\n".join(lines)

    def cancel(self, query: str) -> str:
        routine, error = self._resolve(query)
        if error:
            return error
        self.store.update_routine(routine["id"], status="cancelled")
        return f"Cancelei a rotina: {routine['instruction']}."

    def due(self, now: datetime) -> list[dict]:
        now = now.astimezone(TZ)
        ready = []
        for routine in self.store.active_routines():
            if datetime.fromisoformat(routine["due_at"]) <= now:
                ready.append(routine)
        return ready

    def mark_ran(self, routine: dict, now: datetime) -> None:
        now = now.astimezone(TZ)
        nxt = advance(datetime.fromisoformat(routine["due_at"]), routine["repeat"], now)
        if nxt is None:
            self.store.update_routine(routine["id"], status="done", last_run_at=now.isoformat(timespec="minutes"))
            return
        self.store.update_routine(
            routine["id"],
            due_at=nxt.isoformat(timespec="minutes"),
            last_run_at=now.isoformat(timespec="minutes"),
        )

    def _resolve(self, query: str) -> tuple[dict | None, str | None]:
        text = (query or "").strip().casefold()
        rows = self.store.active_routines()
        if not text:
            return None, "Diga qual rotina."
        by_id = [row for row in rows if row["id"] == text or row["id"].startswith(text)]
        if len(by_id) == 1:
            return by_id[0], None
        hits = [row for row in rows if text in row["instruction"].casefold()]
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            codes = ", ".join(row["id"] for row in hits)
            return None, f"Achei mais de uma. Use o código: {codes}."
        return None, "Não achei essa rotina."
