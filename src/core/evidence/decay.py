"""
Seeker.Bot — Confidence Decay 2.0
src/core/evidence/decay.py

Dois mecanismos que nenhum agente implementa juntos:

1. TIME DECAY — evidências velhas perdem confiança automaticamente.
   Domínios diferentes decaem em velocidades diferentes:
     - Crypto/preços: half-life de 1 dia (muda todo dia)
     - Tech/APIs: half-life de 30 dias (muda todo mês)
     - Ciência/papers: half-life de 180 dias (muda devagar)
     - Fatos históricos: half-life de 999 dias (quase nunca muda)

2. VERIFICATION PENALTY — claims NÃO verificadas por fonte cruzada
   sofrem penalty de confiança. A busca web INDUZ excesso de confiança
   (Xuan et al., jan/2026). O decay corrige isso.

   depth 0 (só buscada):           ×0.4
   depth 1 (corroborada 2ª fonte): ×0.7
   depth 2 (fonte primária):       ×0.9
   depth 3 (testada na prática):   ×1.0
"""

import logging
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.memory.protocol import MemoryProtocol

log = logging.getLogger("seeker.evidence.decay")


# ─────────────────────────────────────────────────────────────────────
# DOMÍNIOS E HALF-LIVES
# ─────────────────────────────────────────────────────────────────────

class Domain(str, Enum):
    CRYPTO     = "crypto"
    NEWS       = "news"
    TECH_API   = "tech_api"
    TECH_ARCH  = "tech_arch"
    SCIENCE    = "science"
    BUSINESS   = "business"
    HISTORY    = "history"
    GENERAL    = "general"

DOMAIN_HALF_LIFE = {
    Domain.CRYPTO:    1,
    Domain.NEWS:      3,
    Domain.TECH_API:  30,
    Domain.BUSINESS:  60,
    Domain.TECH_ARCH: 90,
    Domain.SCIENCE:   180,
    Domain.HISTORY:   999,
    Domain.GENERAL:   60,
}

VERIFICATION_MULTIPLIER = {
    0: 0.70,  # Não verificado — penalty leve (era 0.40, matava fatos legados)
    1: 0.85,  # Corroborado por 2ª fonte
    2: 0.93,  # Fonte primária
    3: 1.00,  # Testado na prática
}

DOMAIN_KEYWORDS = {
    Domain.CRYPTO: [
        "bitcoin", "ethereum", "crypto", "token", "defi", "nft",
        "blockchain", "solana", "cotação", "preço",
    ],
    Domain.NEWS: [
        "notícia", "hoje", "ontem", "breaking", "aconteceu",
        "eleição", "eleito", "morreu", "faleceu",
    ],
    Domain.TECH_API: [
        "api", "sdk", "free tier", "rate limit", "endpoint",
        "model id", "versão", "release", "deprecat", "pricing",
    ],
    Domain.TECH_ARCH: [
        "arquitetura", "padrão", "framework", "design pattern",
        "microserviço", "monolito", "event driven",
    ],
    Domain.SCIENCE: [
        "paper", "arxiv", "estudo", "pesquisa", "peer review",
        "experimento", "hipótese", "publicação",
    ],
    Domain.BUSINESS: [
        "ceo", "cto", "empresa", "startup", "funding",
        "aquisição", "ipo", "receita", "revenue",
    ],
    Domain.HISTORY: [
        "história", "histórico", "inventou", "fundou",
        "nasceu", "criado em", "origem",
    ],
}


# ─────────────────────────────────────────────────────────────────────
# FUNÇÕES DE DECAY (puras, sem side effects)
# ─────────────────────────────────────────────────────────────────────

def detect_domain(text: str) -> Domain:
    """Detecta o domínio de um fato por keywords."""
    text_lower = text.lower()
    scores: dict[Domain, int] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[domain] = score
    if not scores:
        return Domain.GENERAL
    return max(scores, key=scores.get)


def time_decay_factor(
    last_seen_timestamp: float,
    domain: Domain | str = Domain.GENERAL,
) -> float:
    """
    Fator de decay temporal: 0.5 ^ (days_since / half_life)
    Retorna float entre 0.0 e 1.0.
    """
    if isinstance(domain, str):
        try:
            domain = Domain(domain)
        except ValueError:
            domain = Domain.GENERAL

    half_life = DOMAIN_HALF_LIFE.get(domain, 60)
    days_since = (time.time() - last_seen_timestamp) / 86400

    if days_since <= 0:
        return 1.0

    return math.pow(0.5, days_since / half_life)


def verification_multiplier(depth: int) -> float:
    """Multiplicador de confiança por verification depth."""
    return VERIFICATION_MULTIPLIER.get(depth, 0.4)


def effective_confidence(
    base_confidence: float,
    last_seen_timestamp: float,
    verification_depth: int = 0,
    domain: Domain | str = Domain.GENERAL,
) -> float:
    """
    effective = base × time_decay × verification_multiplier
    Mínimo 0.05 (pode ser re-verificado), máximo 0.95 (humildade epistêmica).
    """
    time_factor = time_decay_factor(last_seen_timestamp, domain)
    verif_factor = verification_multiplier(verification_depth)
    result = base_confidence * time_factor * verif_factor
    return max(0.05, min(0.95, result))


# ─────────────────────────────────────────────────────────────────────
# DECAY ENGINE — usa MemoryProtocol, NUNCA acessa _db direto
# ─────────────────────────────────────────────────────────────────────

class DecayEngine:
    """
    Aplica decay em todos os fatos da memória semântica.
    
    Diferença do original: usa update_fact_confidence() e delete_fact()
    do MemoryProtocol ao invés de self.memory._db.execute() direto.
    Isso significa que QUALQUER backend (SQLite, Graphiti, Postgres)
    funciona sem mudar uma linha aqui.
    
    Também limpa sessões antigas no mesmo ciclo.
    
    Uso:
        engine = DecayEngine(memory_store)
        stats = await engine.run()
    """

    def __init__(self, memory: "MemoryProtocol", min_confidence: float = 0.08):
        self.memory = memory
        self.min_confidence = min_confidence

    async def run(self) -> dict:
        """Executa um ciclo completo: decay de fatos + cleanup de sessões."""
        facts = await self.memory.get_facts(min_confidence=0.0, limit=9999)

        decayed = 0
        removed = 0

        for fact in facts:
            # Memória Reflexiva: Imune a decay. Regras de usuário não envelhecem.
            if fact.get("category") == "reflexive_rule":
                continue
                
            domain = detect_domain(fact["fact"])
            eff_conf = effective_confidence(
                base_confidence=fact["confidence"],
                last_seen_timestamp=fact["last_seen"],
                verification_depth=fact.get("verification_depth", 0),
                domain=domain,
            )

            if eff_conf < self.min_confidence:
                # Muito baixa — remove fato (e embedding via cascade)
                try:
                    await self.memory.delete_fact(fact["id"])
                    removed += 1
                except Exception as e:
                    log.warning(f"[decay] Falha ao remover fato {fact['id']}: {e}")

            elif abs(eff_conf - fact["confidence"]) > 0.02:
                # Decaiu significativamente — atualiza
                try:
                    await self.memory.update_fact_confidence(fact["id"], eff_conf)
                    decayed += 1
                except Exception as e:
                    log.warning(f"[decay] Falha ao atualizar fato {fact['id']}: {e}")

        # Commit em batch (uma vez, não por operação)
        if decayed > 0 or removed > 0:
            await self.memory.commit()

        # Cleanup de sessões antigas (30 dias)
        sessions_removed = 0
        try:
            sessions_removed = await self.memory.cleanup_old_sessions(max_age_days=30)
        except Exception as e:
            log.warning(f"[decay] Falha ao limpar sessões: {e}")

        log.info(
            f"[decay] Ciclo completo: {len(facts)} fatos avaliados, "
            f"{decayed} decayed, {removed} removidos, "
            f"{sessions_removed} turns de sessão limpas"
        )

        return {
            "total": len(facts),
            "decayed": decayed,
            "removed": removed,
            "sessions_cleaned": sessions_removed,
        }
