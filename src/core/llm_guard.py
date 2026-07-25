"""
LLMCallGuard — limita número de chamadas LLM por turno de conversa.

Problema: um único turno do usuário pode disparar várias chamadas LLM em
cascata (cascade fallback, refinement loops, validation, etc.). Sem limite,
uma mensagem pode custar $5+ sem que o usuário perceba.

Solução: ContextVar que armazena o guard ativo. `invoke_with_fallback`
em src/providers/base.py checa esse guard antes de cada chamada e
incrementa o counter. Quando o limite é atingido, lança BudgetExceededError.

Uso (no pipeline.process):
    from src.core.llm_guard import LLMCallGuard, set_active_guard, clear_active_guard

    guard = LLMCallGuard(max_calls=20, max_cost_usd=0.50)
    token = set_active_guard(guard)
    try:
        ... invoca o pipeline ...
    finally:
        clear_active_guard(token)

A função invoke_with_fallback checa o guard via get_active_guard().
Se não há guard ativo, comportamento é o mesmo de antes (sem limite).
"""

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass, field

log = logging.getLogger("seeker.llm_guard")


class BudgetExceededError(Exception):
    """Levantada quando o guard atinge max_calls ou max_cost_usd."""


@dataclass
class LLMCallGuard:
    """Limita chamadas LLM por turno.

    Atributos:
        max_calls: número máximo de chamadas LLM permitidas no turno.
                   Default 20 (suficiente para cascade + refinement típico).
        max_cost_usd: teto de custo em USD. Default 0.50 (configurável por plano).
        calls: counter atual de chamadas.
        cost_usd: custo acumulado.
        label: descrição para logs (ex: "session:telegram:12345").
    """

    max_calls: int = 20
    max_cost_usd: float = 0.50
    label: str = "turn"
    calls: int = field(default=0, init=False)
    cost_usd: float = field(default=0.0, init=False)

    def check(self, estimated_cost: float = 0.0) -> None:
        """Checa se pode fazer mais uma chamada. Lança BudgetExceededError se não.

        Regras:
        1. calls >= max_calls → bloqueia
        2. cost_usd já acumulado >= max_cost_usd → bloqueia (proteção tardia
           mas evita estouro adicional)
        3. cost_usd + estimated_cost > max_cost_usd → bloqueia (proteção
           prospectiva quando o caller sabe o custo estimado)
        """
        if self.calls >= self.max_calls:
            raise BudgetExceededError(
                f"LLMCallGuard[{self.label}] atingiu max_calls={self.max_calls}. "
                f"Possível loop infinito em alguma phase. Abortando turno."
            )
        # Proteção tardia: se já passamos do teto por chamadas anteriores,
        # bloqueia novas calls para evitar explodir o budget ainda mais.
        if self.cost_usd >= self.max_cost_usd:
            raise BudgetExceededError(
                f"LLMCallGuard[{self.label}] já consumiu ${self.cost_usd:.4f} "
                f"≥ max_cost_usd=${self.max_cost_usd:.2f}. "
                f"Abortando turno para evitar estouro de budget."
            )
        if self.cost_usd + estimated_cost > self.max_cost_usd:
            raise BudgetExceededError(
                f"LLMCallGuard[{self.label}] atingiria max_cost_usd=${self.max_cost_usd:.2f} "
                f"(atual ${self.cost_usd:.4f} + estimado ${estimated_cost:.4f}). "
                f"Abortando turno para evitar estouro de budget."
            )

    def record(self, cost: float = 0.0) -> None:
        """Registra uma chamada feita e seu custo."""
        self.calls += 1
        self.cost_usd += cost
        if self.calls % 5 == 0 or self.cost_usd > self.max_cost_usd * 0.8:
            log.debug(
                f"[llm_guard:{self.label}] {self.calls}/{self.max_calls} calls, "
                f"${self.cost_usd:.4f}/${self.max_cost_usd:.2f}"
            )


_active_guard: ContextVar[LLMCallGuard | None] = ContextVar(
    "seeker_active_llm_guard", default=None
)


def get_active_guard() -> LLMCallGuard | None:
    """Retorna o guard ativo no contexto atual, ou None."""
    return _active_guard.get()


def set_active_guard(guard: LLMCallGuard) -> Token:
    """Define o guard ativo. Retorna token para reset."""
    return _active_guard.set(guard)


def clear_active_guard(token: Token) -> None:
    """Reseta o guard ativo para o estado anterior."""
    _active_guard.reset(token)
