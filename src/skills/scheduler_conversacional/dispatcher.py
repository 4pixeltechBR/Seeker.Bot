"""
Scheduler Conversacional — TaskDispatcher

Executa tarefas agendadas que venceram.
"""

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from src.skills.scheduler_conversacional.models import (
    ScheduledTask,
    ScheduledTaskRun,
    TaskStatus,
)
from src.skills.scheduler_conversacional.store import SchedulerStore
from src.skills.scheduler_conversacional.calculator import NextRunCalculator

log = logging.getLogger("seeker.scheduler.dispatcher")


class TaskDispatcher:
    """Executa tarefas agendadas que venceram"""

    def __init__(self, store: SchedulerStore, cascade_adapter=None):
        """
        Args:
            store: SchedulerStore instance
            cascade_adapter: CascadeAdapter para executar instrução (opcional)
        """
        self.store = store
        self.cascade_adapter = cascade_adapter

    async def dispatch_overdue_tasks(self) -> dict:
        """
        Encontra e executa tarefas vencidas

        Returns:
            dict com estatísticas de execução
        """
        overdue_tasks = await self.store.find_overdue_tasks()

        stats = {
            "found": len(overdue_tasks),
            "executed": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        for task in overdue_tasks:
            try:
                result = await self._execute_task(task)
                if result["success"]:
                    stats["executed"] += 1
                else:
                    stats["skipped"] += 1
                    stats["errors"].append(result.get("error", "Unknown error"))
            except Exception as e:
                log.error(f"[scheduler.dispatcher] Error executing task {task.id}: {e}")
                stats["failed"] += 1
                stats["errors"].append(str(e))

        log.info(
            f"[scheduler.dispatcher] Dispatch complete: "
            f"Found={stats['found']}, Executed={stats['executed']}, "
            f"Skipped={stats['skipped']}, Failed={stats['failed']}"
        )

        return stats

    async def _execute_task(self, task: ScheduledTask) -> dict:
        """
        Executa uma tarefa individual

        Returns:
            dict com resultado (success, error, execution_id)
        """
        # Verificar idempotência
        idempotency_key = self._make_idempotency_key(task.id, task.next_run_at)
        if await self.store.check_idempotency(idempotency_key):
            log.warning(f"[scheduler.dispatcher] Task {task.id} already executed (idempotency)")
            return {"success": False, "error": "Already executed (idempotency)"}

        # Criar record de execução
        run = ScheduledTaskRun(
            id=str(uuid.uuid4()),
            task_id=task.id,
            scheduled_for=task.next_run_at,
            idempotency_key=idempotency_key,
            status="running",
        )

        try:
            # Registrar que começou
            run.started_at = datetime.utcnow()
            await self.store.create_run(run)

            # Executar instrução (via Cascade)
            if self.cascade_adapter:
                try:
                    response = await self.cascade_adapter.call(
                        role="FAST",
                        messages=[{"role": "user", "content": task.instruction_text}],
                        temperature=0.1,
                        max_tokens=200,
                    )
                    execution_id = str(uuid.uuid4())
                    run.execution_id = execution_id
                    run.status = "success"
                    log.info(
                        f"[scheduler.dispatcher] Task {task.id} executed successfully"
                    )
                except Exception as e:
                    run.status = "failed"
                    run.error = str(e)
                    log.error(f"[scheduler.dispatcher] Task {task.id} failed: {e}")
            else:
                # Modo degradado (sem cascade)
                run.status = "success"
                run.execution_id = "degraded_mode"
                log.warning(f"[scheduler.dispatcher] Task {task.id} executed in degraded mode")

            # Atualizar task
            task.last_run_at = datetime.utcnow()
            task.last_status = run.status
            task.next_run_at = NextRunCalculator.calculate_next_run(task)

            if run.status == "failed":
                task.failure_count += 1
                task.last_error = run.error
            else:
                task.failure_count = 0
                task.last_error = None

            # Salvar atualizações
            run.finished_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            await self.store.update_run(run)
            await self.store.update_task(task)

            return {
                "success": True,
                "execution_id": run.execution_id,
                "status": run.status,
            }

        except Exception as e:
            log.error(f"[scheduler.dispatcher] Exception executing task {task.id}: {e}")
            run.status = "failed"
            run.error = str(e)
            run.finished_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()

            try:
                await self.store.update_run(run)
            except Exception as update_error:
                log.error(f"[scheduler.dispatcher] Failed to update run: {update_error}")

            return {"success": False, "error": str(e)}

    async def execute_task_manually(self, task_id: str) -> dict:
        """
        Executa tarefa manualmente (não é agendada, só imediata)

        Returns:
            dict com resultado
        """
        task = await self.store.get_task(task_id)
        if task is None:
            return {"success": False, "error": "Task not found"}

        return await self._execute_task(task)

    @staticmethod
    def _make_idempotency_key(task_id: str, scheduled_for: datetime) -> str:
        """Cria chave de idempotência"""
        timestamp = scheduled_for.isoformat() if scheduled_for else "unknown"
        return f"{task_id}_{timestamp}"
