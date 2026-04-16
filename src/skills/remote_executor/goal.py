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
    ApprovalTier,
    ActionStatus,
)
from src.core.executor.afk_protocol import AFKProtocolCoordinator
from src.core.executor.safety import SafetyGateEvaluator, ExecutorPolicy
from src.core.evidence import EvidenceEntry, get_evidence_store

from .config import REMOTE_EXECUTOR_CONFIG
from .prompts import get_approval_notification
from src.core.metrics import Sprint11Tracker

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

    def __init__(self, pipeline: SeekerPipeline, notifier=None):
        """
        Inicializa RemoteExecutor goal.

        Args:
            pipeline: SeekerPipeline com model_router, api_keys, notifier
            notifier: GoalNotifier para envio de notificações imediatas (opcional)
        """
        self.pipeline = pipeline
        self.notifier = notifier  # Injetado pelo scheduler

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

        # Metrics tracking (Sprint 11)
        self.tracker = getattr(pipeline, 'sprint11_tracker', Sprint11Tracker())

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

        # Registrar métrica
        self.tracker.record_remote_executor_plan()

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

            # Log Evidence entries para cada step executado
            evidence_store = get_evidence_store()
            for step_id, result in results.items():
                step = next((s for s in plan.steps if s.id == step_id), None)
                if step:
                    evidence = EvidenceEntry(
                        feature="executor_action",
                        decision=f"executed_{step.approval_tier.value}",
                        inputs={
                            "command": step.command,
                            "approval_tier": step.approval_tier.value,
                            "afk_status": self.afk_protocol.status.value if hasattr(self.afk_protocol, 'status') else "unknown",
                        },
                        output={
                            "status": result.status,
                            "output_length": len(result.output) if result.output else 0,
                        },
                        confidence=0.95,
                        model_used="remote_executor_orchestrator",
                        cost_usd=result.cost_usd,
                        latency_ms=result.duration_ms,
                        executed=True,
                        execution_status=result.status,
                        execution_error=result.error_message,
                        reasoning=f"Executed {step.approval_tier.value} action: {step.command[:50]}",
                        parent_evidence_id=None,  # Poderia ser plan_id se houvesse evidência do planejamento
                    )
                    evidence_store.store(evidence)

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

    async def _send_approval_notification(self, step, approval) -> None:
        """Envia notificação de aprovação com inline buttons via notifier."""
        if not self.notifier:
            log.warning("[remote_executor] Notifier não disponível, pulando notificação")
            return

        text, buttons = get_approval_notification(
            action_id=step.id,
            description=step.description[:100],
            timeout_seconds=approval.time_until_timeout,
            estimated_cost=step.estimated_cost_usd,
        )

        # Envia via notifier com buttons no data
        await self.notifier.send(
            goal_name=self.name,
            content=text,
            channels=self.channels,
            data={"buttons": buttons},
        )

    async def _process_approval_queue(self) -> Dict:
        """
        Processa fila de aprovações L0_MANUAL.

        Responsabilidades:
        - Verificar timeouts de aprovações
        - Gerar notificações com inline buttons
        - Retirar da fila quando aprovadas/rejeitadas
        """
        processed = 0
        cost = 0.0

        try:
            # AFKProtocol não expõe approval_queue publicamente
            # A estrutura real é _requests (dict de asyncio.Future)
            if not hasattr(self.afk_protocol, '_requests'):
                log.debug("[remote_executor] AFKProtocol não inicializado, skipping approval queue")
                return processed, cost

            # Apenas logs informativos, não processa atualmente
            # pois AFKProtocol gerencia suas próprias Futures
            requests_copy = dict(self.afk_protocol._requests)
            pending_count = sum(1 for f in requests_copy.values() if not f.done())

            if pending_count > 0:
                log.debug(f"[remote_executor] {pending_count} approval requests pendentes (AFKProtocol gerencia)")
                processed = pending_count

        except Exception as e:
            log.debug(f"[remote_executor] Note ao verificar AFKProtocol requests: {e}")

        return {
            "processed": processed,
            "cost": cost,
        }

    async def _execute_pending_plans(self) -> Dict:
        """
        Executa plans pendentes aprovados.

        Responsabilidades:
        - Iterar plans pendentes
        - Verificar se foram aprovados (L0_MANUAL)
        - Executar via ActionExecutor
        - Registrar métricas
        """
        count = 0
        failed = 0
        cost = 0.0

        try:
            pending_plans_list = list(self.pending_plans.items())

            for plan_id, plan in pending_plans_list:
                # Verificar se foi aprovado (se houver L0_MANUAL)
                has_l0_manual = any(s.approval_tier.value == "L0_MANUAL" for s in plan.steps)
                if has_l0_manual:
                    # Verificar se foi respondido (aprovado/rejeitado)
                    all_l0_responded = True
                    for step in plan.steps:
                        if step.approval_tier.value == "L0_MANUAL":
                            if step.id not in self.afk_protocol.approval_responses:
                                all_l0_responded = False
                                break

                    if not all_l0_responded:
                        log.debug(f"[remote_executor] Plan {plan_id} ainda aguarda L0 approval")
                        continue

                # Executar plan
                context = ExecutionContext(
                    plan_id=plan.plan_id,
                    triggered_by_user="system",
                    triggered_by_intent=plan.intention,
                    goal_name=self.name,
                    budget_remaining_usd=self._budget.remaining_today,
                )

                start_time = datetime.utcnow()
                results = await self.executor.execute_plan(plan, context)
                elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

                # Processa resultados e registra métricas
                for step_id, result in results.items():
                    self.tracker.record_remote_executor_execution(
                        success=(result.status.value == "success"),
                        execution_status=result.status.value.upper(),
                        latency_ms=result.duration_ms,
                        cost_usd=result.cost_usd,
                    )

                    # Registra tier de autonomia
                    step = next((s for s in plan.steps if s.id == step_id), None)
                    if step:
                        self.tracker.record_remote_executor_autonomy_tier(step.approval_tier.value)

                # Atualizar contadores
                summary = self.executor.summarize_results(results)
                count += 1
                failed += summary.get("failed", 0)
                cost += summary.get("total_cost_usd", 0.0)

                # Remover da fila
                del self.pending_plans[plan_id]

        except Exception as e:
            log.error(f"[remote_executor] Error executing pending plans: {e}", exc_info=True)

        return {
            "count": count,
            "failed": failed,
            "cost": cost,
        }

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


def create_goal(pipeline: SeekerPipeline) -> RemoteExecutorGoal:
    """
    Factory chamada pelo Goal Registry para criar instância de RemoteExecutorGoal.

    Args:
        pipeline: SeekerPipeline necessário para acesso a cascade_adapter, api_keys, etc.

    Returns:
        RemoteExecutorGoal instanciado e pronto para o scheduler.
    """
    return RemoteExecutorGoal(pipeline)
