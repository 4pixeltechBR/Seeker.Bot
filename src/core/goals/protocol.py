"""
Seeker.Bot — Goal Engine Protocol
src/core/goals/protocol.py

Interface que todo goal autônomo implementa.
Inspirado no Coordinator Mode / Tasks do Claude Code:
cada goal tem ciclo, budget, estado, canal de notificação.
"""

from __future__ import annotations
from typing import Protocol, runtime_checkable
from dataclasses import dataclass, field
from enum import Enum, auto


class GoalStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"         # Budget esgotado ou backoff
    WAITING_APPROVAL = "waiting_approval"  # AFK Protocol
    ERROR = "error"


class NotificationChannel(str, Enum):
    TELEGRAM = "telegram"
    EMAIL = "email"
    BOTH = "both"


@dataclass
class GoalBudget:
    """Controle de custo por goal."""
    max_per_cycle_usd: float = 0.05
    max_daily_usd: float = 0.50
    spent_today_usd: float = 0.0
    budget_reset_date: str = ""

    @property
    def remaining_today(self) -> float:
        return max(0, self.max_daily_usd - self.spent_today_usd)

    @property
    def exhausted(self) -> bool:
        # max_daily_usd == 0 significa "goal gratuito, sem limite"
        if self.max_daily_usd <= 0:
            return False
        return self.spent_today_usd >= self.max_daily_usd

    def spend(self, amount: float):
        self.spent_today_usd += amount

    def reset_if_new_day(self, today: str):
        if today != self.budget_reset_date:
            self.spent_today_usd = 0.0
            self.budget_reset_date = today


@dataclass
class GoalResult:
    """Resultado de um ciclo de goal."""
    success: bool
    summary: str                          # 1 linha pro log
    notification: str | None = None       # HTML pro Telegram/email (None = sem notificação)
    cost_usd: float = 0.0
    data: dict = field(default_factory=dict)  # Payload livre pro goal


@runtime_checkable
class AutonomousGoal(Protocol):
    """
    Contrato para goals autônomos do Seeker.

    Implementar:
        name, interval_seconds, budget, channels,
        run_cycle(), get_status(), serialize_state(), load_state()
    """

    @property
    def name(self) -> str:
        """Identificador único do goal. Ex: 'revenue_hunter', 'sense_news'."""
        ...

    @property
    def interval_seconds(self) -> int:
        """Intervalo entre ciclos em segundos."""
        ...

    @property
    def budget(self) -> GoalBudget:
        """Budget compartilhado com o scheduler."""
        ...

    @property
    def channels(self) -> list[NotificationChannel]:
        """Canais de notificação. Default: Telegram."""
        ...

    async def run_cycle(self) -> GoalResult:
        """
        Executa um ciclo do goal.
        Deve ser idempotente — falha não corrompe estado.
        Retorna GoalResult com summary e notification opcional.
        """
        ...

    def get_status(self) -> GoalStatus:
        """Status atual do goal."""
        ...

    def serialize_state(self) -> dict:
        """Serializa estado para persistência entre reinícios."""
        ...

    def load_state(self, state: dict) -> None:
        """Restaura estado de dict persistido."""
        ...
