"""
Scheduler Conversacional — Telegram Interface

Interface conversacional via Telegram para criar e gerenciar tarefas agendadas.
"""

import logging
from typing import Optional

from src.skills.scheduler_conversacional.store import SchedulerStore
from src.skills.scheduler_conversacional.wizard import SchedulerWizard
from src.skills.scheduler_conversacional.models import WizardState, ScheduledTask

log = logging.getLogger("seeker.scheduler.telegram")


class SchedulerTelegramInterface:
    """Interface Telegram para Scheduler Conversacional"""

    def __init__(self, store: SchedulerStore):
        self.store = store
        self.wizard = SchedulerWizard(store)

    # ────────────────────────────────────────────────────────
    # Comandos
    # ────────────────────────────────────────────────────────

    async def cmd_agendar(self, chat_id: int, user_id: str) -> str:
        """Inicia wizard de agendamento"""
        session = await self.wizard.start_wizard(chat_id, user_id)
        prompt = self.wizard._prompt_for_state(session)
        return f"🎬 **Criar novo agendamento**\n\n{prompt}"

    async def cmd_listar(self, chat_id: int) -> str:
        """Lista tarefas do usuário"""
        tasks = await self.store.list_tasks(chat_id)

        if not tasks:
            return "📭 Nenhuma tarefa agendada.\n\nDigite /agendar para criar uma."

        msg = "📋 **Suas tarefas agendadas:**\n\n"

        for task in tasks:
            status_emoji = "✅" if task.is_enabled else "⏸️"
            schedule_str = self._format_schedule(task)
            msg += f"{status_emoji} **{task.title}**\n"
            msg += f"  ⏰ {schedule_str}\n"
            msg += f"  🕐 {task.hour}:00\n"
            msg += f"  ID: `{task.id[:8]}`\n\n"

        msg += "\n💡 Digite /detalhe <ID> para ver mais informações."
        return msg

    async def cmd_detalhe(self, chat_id: int, task_id: str) -> str:
        """Mostra detalhe de uma tarefa"""
        task = await self.store.get_task(task_id)

        if task is None or task.chat_id != chat_id:
            return "❌ Tarefa não encontrada."

        status_text = "✅ Ativada" if task.is_enabled else "⏸️ Pausada"
        schedule_str = self._format_schedule(task)

        msg = f"📋 **{task.title}**\n\n"
        msg += f"Status: {status_text}\n"
        msg += f"Frequência: {schedule_str}\n"
        msg += f"Hora: {task.hour}:00\n"
        msg += f"Timezone: {task.timezone}\n\n"

        msg += f"📝 **Instrução:**\n```\n{task.instruction_text}\n```\n\n"

        if task.last_run_at:
            msg += f"⏱️ Última execução: {task.last_run_at.isoformat()}\n"
        if task.next_run_at:
            msg += f"⏳ Próxima execução: {task.next_run_at.isoformat()}\n"

        msg += f"\n💡 Você pode /pausar ou /editar esta tarefa."
        return msg

    async def cmd_pausar(self, chat_id: int, task_id: str) -> str:
        """Pausa uma tarefa"""
        task = await self.store.get_task(task_id)

        if task is None or task.chat_id != chat_id:
            return "❌ Tarefa não encontrada."

        if not task.is_enabled:
            return f"⏸️ **{task.title}** já está pausada."

        task.is_enabled = False
        await self.store.update_task(task)

        return f"⏸️ **{task.title}** foi pausada."

    async def cmd_reativar(self, chat_id: int, task_id: str) -> str:
        """Reativa uma tarefa"""
        task = await self.store.get_task(task_id)

        if task is None or task.chat_id != chat_id:
            return "❌ Tarefa não encontrada."

        if task.is_enabled:
            return f"✅ **{task.title}** já está ativada."

        task.is_enabled = True
        await self.store.update_task(task)

        return f"✅ **{task.title}** foi reativada."

    async def cmd_remover(self, chat_id: int, task_id: str) -> str:
        """Remove uma tarefa"""
        task = await self.store.get_task(task_id)

        if task is None or task.chat_id != chat_id:
            return "❌ Tarefa não encontrada."

        await self.store.delete_task(task_id)

        return f"🗑️ **{task.title}** foi removida."

    async def cmd_executar_agora(self, chat_id: int, task_id: str) -> str:
        """Executa tarefa manualmente agora"""
        task = await self.store.get_task(task_id)

        if task is None or task.chat_id != chat_id:
            return "❌ Tarefa não encontrada."

        return (
            f"▶️ Executando **{task.title}**...\n\n"
            f"Resultado será notificado em breve."
        )

    async def cmd_cancelar_wizard(self, chat_id: int) -> str:
        """Cancela wizard ativo"""
        msg = await self.wizard.cancel_wizard(chat_id)
        return msg

    # ────────────────────────────────────────────────────────
    # Processamento de mensagens
    # ────────────────────────────────────────────────────────

    async def handle_message(self, chat_id: int, user_id: str, text: str) -> str:
        """
        Processa mensagem do usuário

        Pode ser:
        - Input para wizard ativo
        - Comando
        - Input para voltar step
        """
        text = text.strip()

        # Verificar se há wizard ativo
        session = await self.wizard.get_session(chat_id)

        if session is not None:
            # Wizard ativo - processar input
            if text.lower() in ("voltar", "/voltar", "<<"):
                success, msg, updated_session = await self.wizard.back_step(chat_id)
                return msg

            if text.lower() in ("cancelar", "/cancelar", "x"):
                msg = await self.wizard.cancel_wizard(chat_id)
                return msg

            # Coletar input normal
            success, msg, updated_session = await self.wizard.collect_input(chat_id, text)

            # Se completou, processar tarefa
            if updated_session and updated_session.state == WizardState.COMPLETED:
                task_creation_msg = await self._create_task_from_wizard(chat_id, updated_session)
                await self.store.delete_wizard_session(chat_id)
                return task_creation_msg

            return msg

        # Nenhum wizard ativo - pode ser comando
        if text.startswith("/"):
            return await self._handle_command(chat_id, user_id, text)

        return (
            "ℹ️ Nenhum comando ativo. Digite /help para listar comandos ou /agendar para criar uma tarefa."
        )

    async def _handle_command(self, chat_id: int, user_id: str, text: str) -> str:
        """Processa comando"""
        parts = text.split()
        cmd = parts[0].lower()

        if cmd == "/agendar":
            return await self.cmd_agendar(chat_id, user_id)

        elif cmd == "/listar":
            return await self.cmd_listar(chat_id)

        elif cmd == "/detalhe" and len(parts) > 1:
            task_id = parts[1]
            return await self.cmd_detalhe(chat_id, task_id)

        elif cmd == "/pausar" and len(parts) > 1:
            task_id = parts[1]
            return await self.cmd_pausar(chat_id, task_id)

        elif cmd == "/reativar" and len(parts) > 1:
            task_id = parts[1]
            return await self.cmd_reativar(chat_id, task_id)

        elif cmd == "/remover" and len(parts) > 1:
            task_id = parts[1]
            return await self.cmd_remover(chat_id, task_id)

        elif cmd == "/executar" and len(parts) > 1:
            task_id = parts[1]
            return await self.cmd_executar_agora(chat_id, task_id)

        elif cmd == "/help":
            return self._get_help_message()

        else:
            return f"❌ Comando desconhecido: {cmd}\n\nDigite /help para ver comandos."

    # ────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────

    async def _create_task_from_wizard(self, chat_id: int, session) -> str:
        """Cria tarefa a partir de dados do wizard"""
        try:
            from src.skills.scheduler_conversacional.models import ScheduleType, ScheduledTask
            from src.skills.scheduler_conversacional.calculator import NextRunCalculator

            title = session.get_collected_value("title")
            schedule_type_str = session.get_collected_value("schedule_type")
            hour = session.get_collected_value("hour")
            instruction_text = session.get_collected_value("instruction_text")
            day_of_week = session.get_collected_value("day_of_week")
            day_of_month = session.get_collected_value("day_of_month")
            month = session.get_collected_value("month")

            # Criar task
            task = ScheduledTask(
                id=str(session.id),
                title=title,
                schedule_type=ScheduleType(schedule_type_str),
                hour=hour,
                instruction_text=instruction_text,
                day_of_week=day_of_week,
                day_of_month=day_of_month,
                month=month,
                chat_id=chat_id,
                created_by=session.user_id,
            )

            # Calcular próxima execução
            task.next_run_at = NextRunCalculator.calculate_next_run(task)

            # Salvar
            await self.store.create_task(task)

            schedule_str = self._format_schedule(task)
            return (
                f"✅ **Tarefa criada com sucesso!**\n\n"
                f"📝 **{title}**\n"
                f"⏰ {schedule_str} às {hour}:00\n"
                f"⏳ Próxima: {task.next_run_at.strftime('%d/%m/%Y %H:%M')}\n\n"
                f"Use /listar para ver suas tarefas."
            )

        except Exception as e:
            log.error(f"[scheduler.telegram] Error creating task: {e}")
            return f"❌ Erro ao criar tarefa: {str(e)}"

    @staticmethod
    def _format_schedule(task: ScheduledTask) -> str:
        """Formata texto de frequência"""
        if task.schedule_type.value == "daily":
            return "📅 Diariamente"
        elif task.schedule_type.value == "weekly":
            days = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
            day = days[task.day_of_week] if task.day_of_week is not None else "?"
            return f"📅 Semanal ({day})"
        elif task.schedule_type.value == "monthly":
            return f"📅 Mensalmente (dia {task.day_of_month})"
        elif task.schedule_type.value == "annual":
            return f"📅 Anualmente ({task.day_of_month}/{task.month})"
        return "❓ Frequência desconhecida"

    @staticmethod
    def _get_help_message() -> str:
        """Mensagem de ajuda"""
        return (
            "🤖 **Scheduler Conversacional — Ajuda**\n\n"
            "**Comandos principais:**\n"
            "📌 `/agendar` — Criar nova tarefa agendada\n"
            "📋 `/listar` — Ver suas tarefas\n"
            "📝 `/detalhe <ID>` — Ver detalhe de tarefa\n"
            "▶️ `/executar <ID>` — Executar tarefa agora\n"
            "⏸️ `/pausar <ID>` — Pausar tarefa\n"
            "✅ `/reativar <ID>` — Reativar tarefa\n"
            "🗑️ `/remover <ID>` — Remover tarefa\n\n"
            "**Durante o wizard:**\n"
            "↩️ Responda as perguntas passo a passo\n"
            "🔙 Digite `voltar` para voltar um passo\n"
            "❌ Digite `cancelar` para desistir\n\n"
            "💡 Todas as tarefas respeitam as politicas de aprovação do Seeker."
        )
