"""
Sinais de demanda comercial derivados do EventRadar.

Classifica eventos por tipo de oportunidade econômica e retorna
um texto pronto para injeção em skills de monetização (revenue_hunter).

Tipos mapeados:
  agro      → rodeio, exposição, agropecuária, feira
  religioso → padroeiro, festa junina, procissão, corpus
  turismo   → aniversário, carnaval, réveillon, festival, show
  negócios  → convenção, congresso, feira de negócios
"""

import re
from src.skills.event_radar.query import EventQuery, _MONTH_NAMES

_TIPO_PATTERNS = {
    "agro": re.compile(
        r"rodeio|exposi[cç]|agropec|fair[ao]|agro|pecuária|vaquejada", re.I
    ),
    "religioso": re.compile(
        r"padroeiro|padroeira|festa junina|são joão|são pedro|corpus|procissão|romaria", re.I
    ),
    "turismo": re.compile(
        r"anivers[aá]rio|carnaval|r[eé]veillon|festival|show|cultura|turismo", re.I
    ),
    "negocios": re.compile(
        r"congresso|conven[cç]|fórum|sem[ií]nario|feira de neg", re.I
    ),
}


def _classify(nome: str) -> str:
    for tipo, pat in _TIPO_PATTERNS.items():
        if pat.search(nome):
            return tipo
    return "outro"


def get_demand_report(days: int = 30, top_cities: int = 15) -> str:
    """
    Retorna texto de oportunidades comerciais para o próximo período.
    Formato pensado para ser passado a um LLM de revenue hunting.
    """
    q = EventQuery()
    signals = q.demand_signals(days=days)

    if not signals:
        return "Nenhum sinal de demanda no período."

    lines = [
        f"=== Oportunidades Comerciais — próximos {days} dias (Goiás) ===\n"
    ]
    for s in signals[:top_cities]:
        mes = _MONTH_NAMES[s["mes"]] if s.get("mes") else "?"
        # classifica os eventos da cidade
        full_events = [
            e for e in q.by_month(s["mes"])
            if e.get("cidade") == s["cidade"]
        ] if s.get("mes") else []
        tipos = list({_classify(e.get("nome", "")) for e in full_events})

        lines.append(
            f"• {s['cidade']} [{mes}] — {s['total_eventos']} eventos"
            f"  tipos: {', '.join(tipos)}"
        )
        for nome in s["nomes"]:
            lines.append(f"    - {nome}")

    return "\n".join(lines)


def get_demand_json(days: int = 30) -> list[dict]:
    """Versão estruturada para consumo programático."""
    q = EventQuery()
    signals = q.demand_signals(days=days)
    for s in signals:
        full_events = [
            e for e in q.by_month(s["mes"])
            if e.get("cidade") == s["cidade"]
        ] if s.get("mes") else []
        s["tipos"] = list({_classify(e.get("nome", "")) for e in full_events})
    return signals
