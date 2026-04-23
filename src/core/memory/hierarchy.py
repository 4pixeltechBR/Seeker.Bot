"""
Seeker.Bot — Hierarchical Memory
src/core/memory/hierarchy.py

Resolve conflitos entre fatos de diferentes camadas.
Inspirado no CLAUDE.md: global → user → project → local,
prioridade por proximidade.

Camadas (mais genérica → mais específica):
    SYSTEM(10)   — fatos sobre o mundo
    DOMAIN(20)   — fatos sobre um domínio (eventos, contexto externo)
    USER(30)     — fatos sobre o Victor
    PROJECT(40)  — fatos sobre projetos ativos (Seeker, etc.)
    SESSION(50)  — fatos da conversa atual
    OVERRIDE(100)— correções explícitas (prioridade absoluta)

Conflito: camada mais específica ganha. Mesma camada: mais recente ganha.
"""

import logging
import time
from enum import IntEnum

log = logging.getLogger("seeker.memory.hierarchy")


class MemoryLayer(IntEnum):
    SYSTEM = 10
    DOMAIN = 20
    USER = 30
    PROJECT = 40
    SESSION = 50
    OVERRIDE = 100

# ─── 4-LAYER STACK DE contexto ─────────────────────────────
# L0: IDENTITY   (~100 tokens) - Identidade fixa e estado do bot
# L1: ESSENTIAL  (~500 tokens) - Top fatos por score (importância + recência)
# L2: ON-DEMAND  (~500 tokens) - Fatos relevantes ao domínio da conversa
# L3: SEARCH     (~1000 tokens) - Resultados de busca semântica/híbrida

CATEGORY_TO_LAYER = {
    "general": MemoryLayer.SYSTEM,
    "tech_context": MemoryLayer.SYSTEM,
    "world_fact": MemoryLayer.SYSTEM,
    "domain": MemoryLayer.DOMAIN,
    "industry": MemoryLayer.DOMAIN,
    "events": MemoryLayer.DOMAIN,
    "user_preference": MemoryLayer.USER,
    "user_pref": MemoryLayer.USER,
    "user_context": MemoryLayer.USER,
    "user_habit": MemoryLayer.USER,
    "personal": MemoryLayer.USER,
    "decision": MemoryLayer.USER,
    "pattern": MemoryLayer.USER,
    "project": MemoryLayer.PROJECT,
    "seeker": MemoryLayer.PROJECT,
    "session": MemoryLayer.SESSION,
    "reflexive_rule": MemoryLayer.OVERRIDE,
    "correction": MemoryLayer.OVERRIDE,
    "override": MemoryLayer.OVERRIDE,
}

def get_layer(category: str) -> MemoryLayer:
    return CATEGORY_TO_LAYER.get(category, MemoryLayer.SYSTEM)

def score_fact(fact: dict) -> float:
    """Score = (layer * 10) + (confidence * 5) + recency_bonus."""
    layer = get_layer(fact.get("category", "general"))
    confidence = fact.get("confidence", 0.5)
    last_seen = fact.get("last_seen", 0)
    age = time.time() - last_seen
    # Bonus de recência: decai em 30 dias
    recency = max(0, 1 - (age / (30 * 86400)))
    return (float(layer) * 10.0) + (confidence * 5.0) + recency

def format_4layer_context(
    *,
    identity: str = "",
    essential_facts: list[dict] | None = None,
    on_demand_facts: list[dict] | None = None,
    search_results: list[dict] | None = None,
    episodes: list[dict] | None = None,
) -> str:
    """
    Formata o contexto seguindo o padrão MemPalace de 4 camadas.
    Otimizado para economia de tokens e clareza.
    """
    sections = []

    # L0: IDENTITY
    if identity:
        sections.append(f"=== L0: IDENTITY ===\n{identity}")

    # L1: ESSENTIAL
    if essential_facts:
        lines = ["=== L1: ESSENTIAL MEMORY ==="]
        for f in essential_facts:
            lines.append(f"• {f['fact']}")
        sections.append("\n".join(lines))

    # L2: ON-DEMAND
    if on_demand_facts:
        lines = ["=== L2: CONTEXTUAL MEMORY ==="]
        for f in on_demand_facts:
            lines.append(f"• ({f['category']}) {f['fact']}")
        sections.append("\n".join(lines))

    # L3: SEARCH
    if search_results:
        lines = ["=== L3: SEARCH RESULTS ==="]
        for f in search_results:
            score = f.get("hybrid_score", f.get("similarity", 0))
            lines.append(f"• [{score:.2f}] {f['fact']}")
        sections.append("\n".join(lines))

    # EPISODES (histórico recente de interações)
    if episodes:
        icons = {"reflex": "⚡", "deliberate": "🧠", "deep": "🔬"}
        lines = ["=== INTERAÇÕES RECENTES ==="]
        for ep in episodes:
            icon = icons.get(ep.get("depth", ""), "")
            lines.append(f"{icon} {ep['user_input'][:100]}")
            if ep.get("response_summary"):
                lines.append(f"   → {ep['response_summary'][:100]}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)
