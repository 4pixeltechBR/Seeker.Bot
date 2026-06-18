"""
Scheduler Conversacional — TaskDispatcher

Executa tarefas agendadas que venceram.
"""

import logging
import uuid
from datetime import datetime, timezone

from src.skills.scheduler_conversacional.models import (
    ScheduledTask,
    ScheduledTaskRun,
)
from src.skills.scheduler_conversacional.store import SchedulerStore
from src.skills.scheduler_conversacional.calculator import NextRunCalculator

log = logging.getLogger("seeker.scheduler.dispatcher")


class TaskDispatcher:
    """Executa tarefas agendadas que venceram"""

    def __init__(self, store: SchedulerStore, cascade_adapter=None, notifier=None):
        """
        Args:
            store: SchedulerStore instance
            cascade_adapter: CascadeAdapter para executar instrução (opcional)
            notifier: GoalNotifier para enviar resultados (opcional)
        """
        self.store = store
        self.cascade_adapter = cascade_adapter
        self.notifier = notifier

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
            log.warning(
                f"[scheduler.dispatcher] Task {task.id} already executed (idempotency)"
            )
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
            run.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await self.store.create_run(run)

            # Lembrete (notify_only): apenas envia o texto, sem rodar LLM.
            if getattr(task, "notify_only", False):
                run.execution_id = "reminder"
                run.status = "success"
                if self.notifier and getattr(self.notifier, "bot", None) and task.chat_id:
                    msg = f"🔔 <b>Lembrete</b>\n\n{task.instruction_text or task.title}"
                    try:
                        await self.notifier.bot.send_message(task.chat_id, msg, parse_mode="HTML")
                        log.info(f"[scheduler.dispatcher] Lembrete enviado para chat_id {task.chat_id}")
                    except Exception as ne:
                        run.status = "failed"
                        run.error = str(ne)
                        log.error(f"[scheduler.dispatcher] Falha ao enviar lembrete: {ne}")
                else:
                    log.warning("[scheduler.dispatcher] Lembrete sem notifier/bot — modo degradado")

            # Executar instrução (via Cascade)
            elif self.cascade_adapter:
                try:
                    resp = await self.cascade_adapter.call(
                        role="FAST",
                        messages=[{"role": "user", "content": task.instruction_text}],
                        temperature=0.1,
                        max_tokens=200,
                    )
                    content = resp.get("content", "")
                    execution_id = str(uuid.uuid4())
                    run.execution_id = execution_id
                    run.status = "success"
                    log.info(
                        f"[scheduler.dispatcher] Task {task.id} executed successfully"
                    )

                    # Envia a notificação individual da tarefa para o chat_id que a agendou
                    if content and self.notifier and getattr(self.notifier, "bot", None) and task.chat_id:
                        msg = (
                            f"🔔 <b>Tarefa Executada: {task.title}</b>\n\n"
                            f"{content}"
                        )
                        try:
                            await self.notifier.bot.send_message(
                                task.chat_id,
                                msg,
                                parse_mode="HTML"
                            )
                            log.info(f"[scheduler.dispatcher] Notificação enviada para chat_id {task.chat_id}")
                        except Exception as ne:
                            log.error(f"[scheduler.dispatcher] Falha ao notificar chat_id {task.chat_id}: {ne}")
                except Exception as e:
                    run.status = "failed"
                    run.error = str(e)
                    log.error(f"[scheduler.dispatcher] Task {task.id} failed: {e}")
            else:
                # Modo degradado (sem cascade)
                run.status = "success"
                run.execution_id = "degraded_mode"
                log.warning(
                    f"[scheduler.dispatcher] Task {task.id} executed in degraded mode"
                )

            # Atualizar task
            task.last_run_at = datetime.now(timezone.utc).replace(tzinfo=None)
            task.last_status = run.status

            # ONCE: disparo único — não reagenda; desativa após executar.
            from src.skills.scheduler_conversacional.models import ScheduleType
            if task.schedule_type == ScheduleType.ONCE:
                task.is_enabled = False
                task.next_run_at = None
            else:
                task.next_run_at = NextRunCalculator.calculate_next_run(task)

            if run.status == "failed":
                task.failure_count += 1
                task.last_error = run.error
            else:
                task.failure_count = 0
                task.last_error = None

            # Salvar atualizações
            run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            run.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
            run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            run.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

            try:
                await self.store.update_run(run)
            except Exception as update_error:
                log.error(
                    f"[scheduler.dispatcher] Failed to update run: {update_error}"
                )

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
