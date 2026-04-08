"""
Seeker.Bot — Phase Base Types
src/core/phases/base.py

Tipos compartilhados por todas as fases do pipeline.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from src.core.router.cognitive_load import RoutingDecision
from src.core.evidence.arbitrage import ArbitrageResult
from src.core.healing.judge import JudgeVerdict

if TYPE_CHECKING:
    from src.core.intent_card import IntentCard


@dataclass
class PhaseContext:
    """Tudo que uma fase precisa para executar."""
    user_input: str
    decision: RoutingDecision
    memory_prompt: str
    session_context: str = ""
    afk_protocol: any = None
    intent_card: "IntentCard | None" = None  # Para segurança + auditoria


@dataclass
class PhaseResult:
    """Output padronizado de qualquer fase."""
    response: str
    cost_usd: float = 0.0
    llm_calls: int = 0
    arbitrage: ArbitrageResult | None = None
    verdict: JudgeVerdict | None = None
    image_bytes: bytes | None = None
