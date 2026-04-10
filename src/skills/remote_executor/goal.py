"""
RemoteExecutorGoal — Goal Autônomo para Execução de Ações Multi-step

Fluxo:
1. Escuta intenções ACTION do usuário (via IntentCard)
2. Chama ActionOrchestrator para gerar ExecutionPlan
3. Valida plan contra SafetyGates
4. Processa L0_MANUAL actions (enqueue approval, escalate, retry)
5. Executa L1_LOGGED/L2_SILENT via ActionExecutor
6. Captura audit trail completo
7. Notifica via Telegram com resultados

Implementa AutonomousGoal protocol.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict

from src.core.pipeline import SeekerPipeline
from src.core.goals.protocol import (
    AutonomousGoal,
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)
from src.core.executor import (
    ActionOrchestrator,
    ActionExecutor,
    ExecutionContext,
    ExecutionPlan,
    AutonomyTier,
    ActionStatus,
)
from src.core.executor.afk_protocol import AFKProtocolCoordinator
from src.core.executor.safety import SafetyGateEvaluator, ExecutorPolicy

from .config import REMOTE_EXECUTOR_CONFIG

log = logging.getLogger("seeker.remote_executor")


class RemoteExecutorGoal:
    """
    Goal autônomo que executa ações multi-step.

    Responsabilidades:
    - Planejar ações via LLM (ActionOrchestrator)
    - Executar sequencialmente (ActionExecutor)
    - Gerenciar AFK protocol (approval queues)
    - Aplicar safety gates
    - Logging e audit trail
    """

    def __init__(self, pipeline: SeekerPipeline):
        """
        Inicializa RemoteExecutor goal.

        Args:
            pipeline: SeekerPipeline com model_router, api_keys, notifier
        """
        self.pipeline = pipeline

        # Status e budget
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(
            max_per_cycle_usd=REMOTE_EXECUTOR_CONFIG.MAX_COST_PER_CYCLE_USD,
            max_daily_usd=REMOTE_EXECUTOR_CONFIG.MAX_COST_PER_DAY_USD,
        )

        # Executores
        self.orchestrator = ActionOrchestrator(
            cascade_adapter=pipeline.cascade_adapter,
        )
        self.executor = ActionExecutor()
        self.afk_protocol = AFKProtocolCoordinator(user_id=getattr(pipeline, 'user_id', 'default'))
        self.safety_evaluator = SafetyGateEvaluator()
        self.policy = ExecutorPolicy()

        # Pending plans (para tracking)
        self.pending_plans: Dict[str, ExecutionPlan] = {}

    @property
    def name(self) -> str:
        """Identificador do goal."""
        return "remote_executor"

    @property
    def interval_seconds(self) -> int:
        """Polling interval para checks (approval queue, escalation)."""
        return REMOTE_EXECUTOR_CONFIG.INTERVAL_SECONDS

    @property
    def budget(self) -> GoalBudget:
        """Budget compartilhado."""
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        """Notificação via Telegram."""
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        """Status atual do goal."""
        return self._status

    async def run_cycle(self) -> GoalResult:
        """
        Executa um ciclo do goal.

        Responsabilidades:
        1. Verificar approval queue (timeouts, retries, escalation)
        2. Executar plans pendentes L0_MANUAL approved
        3. Processar novas intenções ACTION (se houver)

        Retorna GoalResult com summary e notification.
        """
        self._status = GoalStatus.RUNNING
        cycle_cost = 0.0

        try:
            # 1. Verificar approval queue
            log.debug("[remote_executor] Checking approval queue")
            approval_result = await self._process_approval_queue()
            cycle_cost += approval_result.get("cost", 0.0)

            # 2. Executar plans pendentes aprovados
            log.debug("[remote_executor] Executing pending plans")
            execution_results = await self._execute_pending_plans()
            cycle_cost += execution_results.get("cost", 0.0)

            # Log de status
            summary = f"Approval queue: {approval_result.get('processed', 0)} checked. " \
                     f"Executed: {execution_results.get('count', 0)} plans."
            notification = None

            if execution_results.get("failed", 0) > 0:
                notification = (
                    f"[Remote Executor] {execution_results['count']} planos executados, "
                    f"{execution_results['failed']} falharam."
                )

            # 3. Atualizar budget
            self._budget.spend(cycle_cost)

            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary=summary,
                notification=notification,
                cost_usd=cycle_cost,
            )

        except Exception as e:
            log.error(f"[remote_executor] Cycle failed: {e}", exc_info=True)
            self._status = GoalStatus.ERROR
            return GoalResult(
                success=False,
                summary=f"Erro: {str(e)}",
                cost_usd=cycle_cost,
            )

    async def plan_action(
        self, intention: str, user_id: str = "default"
    ) -> tuple[Optional[ExecutionPlan], str]:
        """
        API para usuário: planejar ação.

        Chamado externamente (ex: IntentCard ACTION route).
        """
        log.info(f"[remote_executor] Planning action: {intention[:80]}")

        # Criar contexto de execução
        context = ExecutionContext(
            plan_id=f"plan_{datetime.utcnow().isoformat()}",
            triggered_by_user=user_id,
            triggered_by_intent=intention,
            goal_name=self.name,
            budget_remaining_usd=self._budget.remaining_today,
            afk_time_seconds=0,  # TODO: obter do afk_protocol
            afk_window_l1_hours=REMOTE_EXECUTOR_CONFIG.AFK_WINDOW_L1_LOGGED_HOURS,
        )

        # Planejar
        plan, error = await self.orchestrator.plan(intention, context)
        if not plan:
            log.error(f"[remote_executor] Planning failed: {error}")
            return None, error

        # Avaliar segurança
        is_safe, violations = await self.safety_evaluator.evaluate_plan(plan, context)
        if not is_safe:
            log.warning(f"[remote_executor] Plan safety violations: {violations}")
            return None, f"Safety violations: {', '.join(violations)}"

        # Armazenar para execução posterior
        self.pending_plans[plan.plan_id] = plan
        log.info(f"[remote_executor] Plan created: {plan.plan_id}")

        return plan, ""

    async def execute_plan(
        self, plan_id: str, approval_context: Optional[Dict] = None
    ) -> GoalResult:
        """
        Executa plan específico.

        Args:
            plan_id: ID do plan a executar
            approval_context: Context se foi aprovado manualmente
        """
        if plan_id not in self.pending_plans:
            return GoalResult(success=False, summary=f"Plan {plan_id} not found")

        plan = self.pending_plans[plan_id]

        try:
            # Criar contexto
            context = ExecutionContext(
                plan_id=plan.plan_id,
                triggered_by_user=approval_context.get("user_id", "default")
                if approval_context
                else "system",
                triggered_by_intent=plan.intention,
                goal_name=self.name,
                budget_remaining_usd=self._budget.remaining_today,
            )

            # Executar plan
            results = await self.executor.execute_plan(plan, context)

            # Summarize
            summary = self.executor.summarize_results(results)
            cycle_cost = sum(r.cost_usd for r in results.values())

            # Notificação
            notification = REMOTE_EXECUTOR_CONFIG.TELEGRAM_EXECUTION_TEMPLATE.format(
                summary=plan.intention[:60],
                step_count=len(results),
                success_count=summary["successful"],
                total_cost_usd=summary["total_cost_usd"],
                duration_ms=summary["total_duration_ms"],
            )

            # Cleanup
            del self.pending_plans[plan_id]

            return GoalResult(
                success=summary["success_rate"] > 0,
                summary=f"{summary['successful']}/{summary['total_steps']} steps successful",
                notification=notification,
                cost_usd=cycle_cost,
            )

        except Exception as e:
            log.error(f"[remote_executor] Execution failed: {e}", exc_info=True)
            return GoalResult(
                success=False,
                summary=f"Execution error: {str(e)}",
                cost_usd=0.0,
            )

    async def _process_approval_queue(self) -> Dict:
        """Processa fila de aprovações L0_MANUAL."""
        # TODO: integração com AFK protocol
        # - Check timeouts
        # - Retry escalation
        # - Execute approved actions
        return {"processed": 0, "cost": 0.0}

    async def _execute_pending_plans(self) -> Dict:
        """Executa plans pendentes aprovados."""
        # TODO: iterar pending_plans e executar se aprovado
        return {"count": 0, "failed": 0, "cost": 0.0}

    def serialize_state(self) -> dict:
        """Serializa estado para persistência."""
        return {
            "status": self._status.value,
            "budget_spent_today": self._budget.spent_today_usd,
            "pending_plans_count": len(self.pending_plans),
        }

    def load_state(self, state: dict) -> None:
        """Carrega estado persistido."""
        if "budget_spent_today" in state:
            self._budget.spent_today_usd = state["budget_spent_today"]
        log.info(f"[remote_executor] State loaded: {state}")
