"""
Engine de consulta sobre event_radar_results.jsonl.

Uso:
    from src.skills.event_radar.query import EventQuery
    q = EventQuery()
    q.upcoming(days=30)          # próximos 30 dias
    q.by_month(6)                # todos em junho
    q.demand_signals(days=30)    # agrupado por cidade/tipo (para revenue)
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Optional


_MONTH_NAMES = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _default_jsonl() -> Path:
    gdrive = os.getenv("GDRIVE_PATH")
    if gdrive and Path(gdrive).exists():
        p = Path(gdrive) / "event_radar" / "event_radar_results.jsonl"
        if p.exists():
            return p
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent
        / "data" / "event_radar" / "event_radar_results.jsonl",
        Path("E:/Seeker.Bot/data/event_radar/event_radar_results.jsonl"),
    ]
    return next((c for c in candidates if c.exists()), candidates[0])


class EventQuery:
    def __init__(self, jsonl_path: Optional[Path] = None):
        self._path = jsonl_path or _default_jsonl()
        self._events: list[dict] | None = None

    def _load(self) -> list[dict]:
        if self._events is None:
            if not self._path.exists():
                self._events = []
            else:
                self._events = [
                    json.loads(line)
                    for line in self._path.read_text("utf-8").splitlines()
                    if line.strip()
                ]
        return self._events

    def all(self, uf: Optional[str] = None) -> list[dict]:
        events = self._load()
        if uf:
            uf_norm = uf.strip().upper()
            return [e for e in events if str(e.get("uf", "")).upper() == uf_norm]
        return events

    def by_month(self, mes: int, mes_fim: Optional[int] = None) -> list[dict]:
        """Todos os eventos que cobrem o mês `mes` (inclusive ranges)."""
        result = []
        for e in self._load():
            e_mes = e.get("mes")
            e_fim = e.get("mes_fim") or e_mes
            if e_mes is None:
                continue
            target_end = mes_fim or mes
            # Evento cobre o range se os intervalos se sobrepõem
            if e_mes <= target_end and (e_fim or e_mes) >= mes:
                result.append(e)
        return result

    def upcoming(self, days: int = 30, ref: Optional[date] = None) -> list[dict]:
        """
        Eventos que ocorrem nos próximos `days` dias.
        Usa apenas o mês como aproximação (precisao=exata/mensal/semestral).
        Exclui indeterminados.
        """
        today = ref or date.today()
        end = today + timedelta(days=days)
        months_in_window = set()
        d = today.replace(day=1)
        while d <= end:
            months_in_window.add(d.month)
            # avança para o próximo mês
            if d.month == 12:
                d = d.replace(year=d.year + 1, month=1)
            else:
                d = d.replace(month=d.month + 1)

        result = []
        for e in self._load():
            e_mes = e.get("mes")
            e_fim = e.get("mes_fim") or e_mes
            if e_mes is None:
                continue
            event_months = set(range(e_mes, (e_fim or e_mes) + 1))
            if event_months & months_in_window:
                result.append(e)
        return sorted(result, key=lambda x: x.get("mes") or 0)

    def demand_signals(self, days: int = 30, ref: Optional[date] = None) -> list[dict]:
        """
        Retorna oportunidades comerciais agrupadas por cidade.
        Cada item: {cidade, mes, total_eventos, tipos, nomes}
        """
        events = self.upcoming(days=days, ref=ref)
        by_city: dict[str, dict] = {}
        for e in events:
            city = e.get("cidade", "Desconhecida")
            if city not in by_city:
                by_city[city] = {
                    "cidade": city,
                    "mes": e.get("mes"),
                    "total_eventos": 0,
                    "nomes": [],
                }
            by_city[city]["total_eventos"] += 1
            nome = e.get("nome", "")
            if nome and len(by_city[city]["nomes"]) < 3:
                by_city[city]["nomes"].append(nome)

        return sorted(
            by_city.values(),
            key=lambda x: x["total_eventos"],
            reverse=True,
        )

    def summary_text(self, days: int = 30, max_events: int = 10) -> str:
        """Texto formatado para injeção em briefings."""
        events = self.upcoming(days=days)
        if not events:
            return ""
        total = len(events)
        lines = [f"<b>📅 Próximos {days} dias — {total} eventos mapeados em GO:</b>"]
        for e in events[:max_events]:
            mes_nome = _MONTH_NAMES[e["mes"]] if e.get("mes") else "?"
            lines.append(
                f"  • <b>{e.get('cidade','?')}</b> — {e.get('nome','?')} "
                f"({e.get('data_estimada', mes_nome)})"
            )
        if total > max_events:
            lines.append(f"  <i>...e mais {total - max_events} eventos.</i>")
        return "\n".join(lines)
