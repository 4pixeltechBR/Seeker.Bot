"""
Scheduler Conversacional — Autonomous Goal

Goal que faz polling de tarefas agendadas e as executa.
"""

import asyncio
import logging

from src.core.pipeline import SeekerPipeline
from src.core.goals.protocol import (
    AutonomousGoal,
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)
from src.skills.scheduler_conversacional.store import SchedulerStore
from src.skills.scheduler_conversacional.dispatcher import TaskDispatcher

log = logging.getLogger("seeker.scheduler_goal")


class SchedulerConversacional(AutonomousGoal):
    """
    Autonomous goal que executa tarefas agendadas.

    Faz polling a cada 5 minutos para verificar se há tarefas vencidas
    e as executa respeitando as políticas de approval.
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self.store = None
        self.dispatcher = None

        self._budget = GoalBudget(
            max_per_cycle_usd=0.01,  # Tarefas agendadas são leves
            max_daily_usd=0.10,
        )

        self._status = GoalStatus.IDLE

    @property
    def name(self) -> str:
        return "scheduler_conversacional"

    @property
    def interval_seconds(self) -> int:
        return 300  # Poll a cada 5 minutos

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    # ────────────────────────────────────────────────────────
    # Main Cycle
    # ────────────────────────────────────────────────────────

    async def run_cycle(self) -> GoalResult:
        """Executa ciclo de polling e dispatch"""
        self._status = GoalStatus.RUNNING
        cycle_cost = 0.0

        try:
            # Inicializar se necessário
            if not self.store:
                self.store = SchedulerStore(self.pipeline.memory._db)
                await self.store.init()
                self.dispatcher = TaskDispatcher(self.store, self.pipeline.cascade_adapter)

            # Limpar sessões wizard expiradas
            cleanup_count = await self.store.cleanup_expired_sessions()
            if cleanup_count > 0:
                log.info(f"[scheduler] Cleaned up {cleanup_count} expired wizard sessions")

            # Executar tarefas vencidas
            dispatch_stats = await self.dispatcher.dispatch_overdue_tasks()

            # Construir resposta
            if dispatch_stats["executed"] == 0 and dispatch_stats["failed"] == 0:
                self._status = GoalStatus.IDLE
                return GoalResult(
                    success=True,
                    summary="No overdue tasks",
                    cost_usd=cycle_cost,
                )

            # Havia tarefas para executar
            summary = (
                f"Scheduler: {dispatch_stats['executed']} executed, "
                f"{dispatch_stats['failed']} failed"
            )

            notification = None
            if dispatch_stats["executed"] > 0:
                notification = self._build_notification(dispatch_stats)

            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary=summary,
                notification=notification,
                cost_usd=cycle_cost,
                data=dispatch_stats,
            )

        except Exception as e:
            log.error(f"[scheduler] Cycle failed: {e}", exc_info=True)
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=False,
                summary=f"Scheduler error: {str(e)[:100]}",
                cost_usd=cycle_cost,
            )

    def _build_notification(self, stats: dict) -> str:
        """Constrói notificação Telegram"""
        msg = f"✅ **Scheduler — Ciclo Completo**\n\n"
        msg += f"Executadas: {stats['executed']}\n"
        msg += f"Puladas: {stats['skipped']}\n"
        msg += f"Erros: {stats['failed']}\n"

        if stats["errors"]:
            msg += f"\n⚠️ **Erros:**\n"
            for error in stats["errors"][:3]:  # Mostrar primeiros 3
                msg += f"- {error[:100]}\n"

        return msg

    # ────────────────────────────────────────────────────────
    # State Management
    # ────────────────────────────────────────────────────────

    def serialize_state(self) -> dict:
        """Serializa estado"""
        return {
            "last_run": None,
        }

    def load_state(self, state: dict) -> None:
        """Carrega estado"""
        log.info("[scheduler] State loaded")


def create_goal(pipeline: SeekerPipeline) -> AutonomousGoal:
    """Factory function para skill registration"""
    return SchedulerConversacional(pipeline)
