"""
Seeker.Bot — Hierarchical Memory
src/core/memory/hierarchy.py

Resolve conflitos entre fatos de diferentes camadas.
Inspirado no CLAUDE.md: global → user → project → local,
prioridade por proximidade.

Camadas (mais genérica → mais específica):
    SYSTEM(10)   — fatos sobre o mundo
    DOMAIN(20)   — fatos sobre um domínio (eventos GO, etc.)
    USER(30)     — fatos sobre o Victor
    PROJECT(40)  — fatos sobre um projeto (Seeker, ViralClip)
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


CATEGORY_TO_LAYER = {
    "general": MemoryLayer.SYSTEM,
    "tech_context": MemoryLayer.SYSTEM,
    "world_fact": MemoryLayer.SYSTEM,
    "domain": MemoryLayer.DOMAIN,
    "industry": MemoryLayer.DOMAIN,
    "events": MemoryLayer.DOMAIN,
    "user_preference": MemoryLayer.USER,
    "user_pref": MemoryLayer.USER,          # alias do FactExtractor
    "user_context": MemoryLayer.USER,
    "user_habit": MemoryLayer.USER,
    "personal": MemoryLayer.USER,
    "decision": MemoryLayer.USER,           # escolhas do usuário
    "pattern": MemoryLayer.USER,            # comportamentos recorrentes
    "project": MemoryLayer.PROJECT,
    "seeker": MemoryLayer.PROJECT,
    "viralclip": MemoryLayer.PROJECT,
    "session": MemoryLayer.SESSION,
    "reflexive_rule": MemoryLayer.OVERRIDE, # regras de comportamento do bot (prioridade absoluta)
    "correction": MemoryLayer.OVERRIDE,
    "override": MemoryLayer.OVERRIDE,
}


def get_layer(category: str) -> MemoryLayer:
    return CATEGORY_TO_LAYER.get(category, MemoryLayer.SYSTEM)


def score_fact(fact: dict) -> float:
    """
    Score = (layer * 10) + confidence + recency_bonus.
    Camada mais específica sempre ganha, independente da confiança.
    """
    layer = get_layer(fact.get("category", "general"))
    confidence = fact.get("confidence", 0.5)
    last_seen = fact.get("last_seen", 0)
    age = time.time() - last_seen
    recency = max(0, 1 - (age / (30 * 86400)))
    return (layer * 10) + confidence + recency


def prioritize_facts(facts: list[dict], limit: int = 20) -> list[dict]:
    scored = [(score_fact(f), f) for f in facts]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in scored[:limit]]


def format_hierarchical_context(facts: list[dict], limit: int = 15) -> str:
    if not facts:
        return ""

    prioritized = prioritize_facts(facts, limit=limit)
    by_layer: dict[MemoryLayer, list[dict]] = {}
    for f in prioritized:
        layer = get_layer(f.get("category", "general"))
        by_layer.setdefault(layer, []).append(f)

    lines = ["=== MEMÓRIA SEMÂNTICA ==="]
    for layer in sorted(by_layer.keys(), reverse=True):
        lines.append(f"\n[{layer.name.lower()}]")
        for f in by_layer[layer]:
            lines.append(f"  [{f['confidence']:.0%}] {f['fact']}")

    return "\n".join(lines)
