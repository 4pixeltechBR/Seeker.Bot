"""
ActionExecutor — Sequential execution of multi-step plans.

Responsabilidades:
- Executar steps em ordem (respeitando dependências)
- Invocar handlers apropriados (bash, file_ops, api, remote_trigger)
- Capture snapshots antes/depois
- Rollback automático em caso de erro
- Audit trail completo
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .models import (
    ActionStep,
    ExecutionPlan,
    ExecutionResult,
    ActionStatus,
    ExecutionContext,
)
from .handlers import get_handler

logger = logging.getLogger("seeker.executor.actions")


class ActionExecutor:
    """
    Executa ExecutionPlan multi-step com dependências e rollback.

    Fluxo:
    1. Recebe ExecutionPlan
    2. Resolve ordem topológica de steps (respeita dependências)
    3. Para cada step, chama handler apropriado
    4. Captura snapshots antes/depois
    5. Se falhar, tenta rollback automático
    6. Retorna resultados agregados
    """

    def __init__(self):
        """Inicializa executor."""
        self.handlers = {}  # Cache de handlers por tipo
        self.execution_log: List[dict] = []

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        context: ExecutionContext,
    ) -> Dict[str, ExecutionResult]:
        """
        Executa plano e retorna resultados de cada step.

        Args:
            plan: ExecutionPlan com steps, dependências, etc.
            context: ExecutionContext com budget, AFK status, etc.

        Returns:
            Dict[step_id] → ExecutionResult
            Inclui status de cada step (success, failed, rolled_back, etc)
        """
        logger.info(f"[executor] Executing plan {plan.plan_id}: {len(plan.steps)} steps")

        results: Dict[str, ExecutionResult] = {}
        executed_order: List[str] = []

        try:
            # 1. Resolver ordem topológica (construir dependencies completo se necessário)
            dependencies = self._build_dependencies_map(plan)
            execution_order = self._topological_sort(dependencies)
            logger.debug(f"[executor] Execution order: {execution_order}")

            # 2. Executar steps sequencialmente
            for step_id in execution_order:
                # Encontra step
                step = next((s for s in plan.steps if s.id == step_id), None)
                if not step:
                    logger.error(f"[executor] Step {step_id} not found in plan")
                    continue

                # Checa se dependências foram atendidas
                if not self._dependencies_met(step_id, step.depends_on, results):
                    logger.warning(
                        f"[executor] Step {step_id} dependencies not met, skipping"
                    )
                    results[step_id] = ExecutionResult(
                        step_id=step_id,
                        status=ActionStatus.CANCELLED,
                        error="Dependências não atendidas",
                    )
                    continue

                # Executa step
                logger.info(f"[executor] Executing step {step_id}: {step.description[:60]}")
                result = await self._execute_step(step, context)
                results[step_id] = result
                executed_order.append(step_id)

                # Log execution
                self.execution_log.append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "plan_id": plan.plan_id,
                    "step_id": step_id,
                    "status": result.status.value,
                    "cost_usd": result.cost_usd,
                    "duration_ms": result.duration_ms,
                })

                # Se step falhou e tem rollback instruction, tenta rollback
                if (
                    result.status == ActionStatus.FAILED
                    and step.rollback_instruction
                ):
                    logger.warning(
                        f"[executor] Step {step_id} failed, attempting rollback"
                    )
                    rollback_success = await self._rollback_step(step, result)
                    result.status = (
                        ActionStatus.ROLLED_BACK
                        if rollback_success
                        else ActionStatus.FAILED
                    )

            logger.info(
                f"[executor] Plan execution complete: "
                f"{sum(1 for r in results.values() if r.status == ActionStatus.SUCCESS)}/{len(results)} success"
            )

            return results

        except Exception as e:
            logger.error(f"[executor] Plan execution failed: {e}", exc_info=True)
            raise

    async def _execute_step(
        self, step: ActionStep, context: ExecutionContext
    ) -> ExecutionResult:
        """Executa um step individual via handler apropriado."""
        try:
            # Obter handler
            handler = get_handler(step.type.value)
            if not handler:
                return ExecutionResult(
                    step_id=step.id,
                    status=ActionStatus.FAILED,
                    error=f"Handler não encontrado para tipo {step.type.value}",
                )

            # Executar com timeout
            result = await asyncio.wait_for(
                handler.execute(step),
                timeout=step.timeout_seconds,
            )

            return result

        except asyncio.TimeoutError:
            logger.error(f"[executor] Step {step.id} timeout after {step.timeout_seconds}s")
            return ExecutionResult(
                step_id=step.id,
                status=ActionStatus.FAILED,
                error=f"Timeout após {step.timeout_seconds}s",
            )

        except Exception as e:
            logger.error(f"[executor] Step {step.id} execution error: {e}")
            return ExecutionResult(
                step_id=step.id,
                status=ActionStatus.FAILED,
                error=str(e),
            )

    async def _rollback_step(
        self, step: ActionStep, result: ExecutionResult
    ) -> bool:
        """Tenta fazer rollback de um step."""
        try:
            handler = get_handler(step.type.value)
            if not handler:
                logger.error(f"[executor] Handler não encontrado para rollback {step.id}")
                return False

            # Chama rollback do handler
            success = await handler.rollback(step, result)

            if success:
                logger.info(f"[executor] Rollback successful for step {step.id}")
            else:
                logger.error(f"[executor] Rollback failed for step {step.id}")

            return success

        except Exception as e:
            logger.error(f"[executor] Rollback exception for {step.id}: {e}")
            return False

    def _build_dependencies_map(self, plan: ExecutionPlan) -> Dict[str, List[str]]:
        """Constrói mapa completo de dependências a partir de plan.steps."""
        deps = {}
        for step in plan.steps:
            deps[step.id] = step.depends_on.copy() if step.depends_on else []
        return deps

    def _topological_sort(self, dependencies: Dict[str, List[str]]) -> List[str]:
        """
        Resolve ordem topológica de steps (respeita dependências).

        Se step_2 depends_on [step_1], então step_1 executa antes.
        Usa algoritmo Kahn com edge list.
        """
        if not dependencies:
            return []

        # Construir grafo: node → dependentes (reverse edges)
        # se step_2 depends_on [step_1], então step_1 → [step_2]
        graph = {node: [] for node in dependencies}
        in_degree = {node: len(dependencies[node]) for node in dependencies}

        for node, deps in dependencies.items():
            for dep in deps:
                if dep in graph:
                    graph[dep].append(node)

        # Kahn's algorithm
        queue = [node for node in dependencies if in_degree[node] == 0]
        result = []

        while queue:
            # Processa nodo com in-degree 0
            node = queue.pop(0)
            result.append(node)

            # Reduzir in-degree de dependentes
            for dependent in graph[node]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(dependencies):
            logger.warning("[executor] Ciclo detectado nas dependências")
            # Fallback: retorna ordem por aparição (esperando que plano foi validado)
            return list(dependencies.keys())

        return result

    def _dependencies_met(
        self, step_id: str, depends_on: List[str], results: Dict[str, ExecutionResult]
    ) -> bool:
        """Verifica se todas dependências foram executadas com sucesso."""
        for dep_id in depends_on:
            if dep_id not in results:
                return False  # Dependência não foi executada ainda
            if results[dep_id].status != ActionStatus.SUCCESS:
                return False  # Dependência falhou

        return True

    def get_execution_log(self) -> List[dict]:
        """Retorna log de execução."""
        return self.execution_log.copy()

    def clear_execution_log(self):
        """Limpa log de execução."""
        self.execution_log = []

    def summarize_results(
        self, results: Dict[str, ExecutionResult]
    ) -> Dict:
        """Sumário dos resultados de execução."""
        total_cost = sum(r.cost_usd for r in results.values())
        total_duration_ms = sum(r.duration_ms for r in results.values())
        success_count = sum(
            1 for r in results.values() if r.status == ActionStatus.SUCCESS
        )
        failed_count = sum(
            1 for r in results.values() if r.status == ActionStatus.FAILED
        )
        rollback_count = sum(
            1 for r in results.values() if r.status == ActionStatus.ROLLED_BACK
        )

        return {
            "total_steps": len(results),
            "successful": success_count,
            "failed": failed_count,
            "rolled_back": rollback_count,
            "total_cost_usd": total_cost,
            "total_duration_ms": total_duration_ms,
            "success_rate": (
                success_count / len(results) if results else 0
            ),
        }
