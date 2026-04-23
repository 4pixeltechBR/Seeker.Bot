"""
Scheduler Conversacional — Wizard

State machine para coleta conversacional de dados de tarefa agendada.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Tuple

from src.skills.scheduler_conversacional.models import (
    WizardSession,
    WizardState,
    ScheduleType,
)
from src.skills.scheduler_conversacional.store import SchedulerStore

log = logging.getLogger("seeker.scheduler.wizard")


class SchedulerWizard:
    """Wizard conversacional para criar tarefas agendadas"""

    WIZARD_TIMEOUT_MINUTES = 30

    def __init__(self, store: SchedulerStore):
        self.store = store

    async def start_wizard(self, chat_id: int, user_id: str) -> WizardSession:
        """Inicia novo wizard"""
        # Encerrar qualquer sessão anterior
        await self.store.delete_wizard_session(chat_id)

        session = WizardSession(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            user_id=user_id,
            state=WizardState.COLLECTING_TITLE,
            expires_at=datetime.utcnow() + timedelta(minutes=self.WIZARD_TIMEOUT_MINUTES),
        )

        await self.store.create_wizard_session(session)
        log.info(f"[scheduler.wizard] Started for chat {chat_id}")
        return session

    async def get_session(self, chat_id: int) -> Optional[WizardSession]:
        """Obtém sessão ativa"""
        session = await self.store.get_wizard_session(chat_id)

        if session is None:
            return None

        if session.is_expired():
            await self.store.delete_wizard_session(chat_id)
            log.warning(f"[scheduler.wizard] Session expired for chat {chat_id}")
            return None

        return session

    async def collect_input(
        self, chat_id: int, user_input: str
    ) -> Tuple[bool, str, Optional[WizardSession]]:
        """
        Coleta input do usuário e avança o wizard

        Retorna: (sucesso, mensagem_resposta, sessao_atualizada)
        """
        session = await self.get_session(chat_id)
        if session is None:
            return False, "❌ Nenhum wizard ativo. Digite /agendar para começar.", None

        # Processar input baseado no estado atual
        if session.state == WizardState.COLLECTING_TITLE:
            return await self._collect_title(session, user_input)

        elif session.state == WizardState.COLLECTING_SCHEDULE_TYPE:
            return await self._collect_schedule_type(session, user_input)

        elif session.state == WizardState.COLLECTING_DAY_OF_WEEK:
            return await self._collect_day_of_week(session, user_input)

        elif session.state == WizardState.COLLECTING_DAY_OF_MONTH:
            return await self._collect_day_of_month(session, user_input)

        elif session.state == WizardState.COLLECTING_MONTH_DAY:
            return await self._collect_month_day(session, user_input)

        elif session.state == WizardState.COLLECTING_HOUR:
            return await self._collect_hour(session, user_input)

        elif session.state == WizardState.COLLECTING_INSTRUCTION:
            return await self._collect_instruction(session, user_input)

        elif session.state == WizardState.CONFIRMATION:
            return await self._confirm(session, user_input)

        return False, "❌ Estado desconhecido", None

    async def back_step(self, chat_id: int) -> Tuple[bool, str, Optional[WizardSession]]:
        """Volta um passo no wizard"""
        session = await self.get_session(chat_id)
        if session is None:
            return False, "❌ Nenhum wizard ativo.", None

        # Estados que têm voltar
        state_transitions = {
            WizardState.COLLECTING_SCHEDULE_TYPE: WizardState.COLLECTING_TITLE,
            WizardState.COLLECTING_DAY_OF_WEEK: WizardState.COLLECTING_SCHEDULE_TYPE,
            WizardState.COLLECTING_DAY_OF_MONTH: WizardState.COLLECTING_SCHEDULE_TYPE,
            WizardState.COLLECTING_MONTH_DAY: WizardState.COLLECTING_SCHEDULE_TYPE,
            WizardState.COLLECTING_HOUR: WizardState.COLLECTING_SCHEDULE_TYPE,
            WizardState.COLLECTING_INSTRUCTION: WizardState.COLLECTING_HOUR,
            WizardState.CONFIRMATION: WizardState.COLLECTING_INSTRUCTION,
        }

        new_state = state_transitions.get(session.state)
        if new_state is None:
            return False, "❌ Não é possível voltar daqui.", session

        session.previous_state = session.state
        session.state = new_state
        session.updated_at = datetime.utcnow()
        await self.store.update_wizard_session(session)

        msg = self._prompt_for_state(session)
        return True, msg, session

    async def cancel_wizard(self, chat_id: int) -> str:
        """Cancela wizard"""
        await self.store.delete_wizard_session(chat_id)
        log.info(f"[scheduler.wizard] Cancelled for chat {chat_id}")
        return "❌ Agendamento cancelado."

    # ────────────────────────────────────────────────────────
    # Collection Methods
    # ────────────────────────────────────────────────────────

    async def _collect_title(self, session: WizardSession, user_input: str) -> Tuple[bool, str, WizardSession]:
        """Coleta título da tarefa"""
        title = user_input.strip()

        if not title or len(title) < 3:
            return (
                False,
                "⚠️ Título muito curto (mín. 3 caracteres). Tente novamente:",
                session,
            )

        if len(title) > 100:
            return (
                False,
                "⚠️ Título muito longo (máx. 100 caracteres). Tente novamente:",
                session,
            )

        session.set_collected_value("title", title)
        session.state = WizardState.COLLECTING_SCHEDULE_TYPE
        session.updated_at = datetime.utcnow()
        await self.store.update_wizard_session(session)

        msg = self._prompt_for_state(session)
        return True, msg, session

    async def _collect_schedule_type(self, session: WizardSession, user_input: str) -> Tuple[bool, str, WizardSession]:
        """Coleta tipo de periodicidade"""
        choice = user_input.strip().lower()

        schedule_map = {
            "1": ScheduleType.DAILY,
            "2": ScheduleType.WEEKLY,
            "3": ScheduleType.MONTHLY,
            "4": ScheduleType.ANNUAL,
        }

        if choice not in schedule_map:
            return (
                False,
                "⚠️ Opção inválida. Digite 1, 2, 3 ou 4:",
                session,
            )

        schedule_type = schedule_map[choice]
        session.set_collected_value("schedule_type", schedule_type.value)

        # Determinar próximo estado baseado no tipo
        if schedule_type == ScheduleType.DAILY:
            session.state = WizardState.COLLECTING_HOUR
        elif schedule_type == ScheduleType.WEEKLY:
            session.state = WizardState.COLLECTING_DAY_OF_WEEK
        elif schedule_type == ScheduleType.MONTHLY:
            session.state = WizardState.COLLECTING_DAY_OF_MONTH
        elif schedule_type == ScheduleType.ANNUAL:
            session.state = WizardState.COLLECTING_MONTH_DAY

        session.updated_at = datetime.utcnow()
        await self.store.update_wizard_session(session)

        msg = self._prompt_for_state(session)
        return True, msg, session

    async def _collect_day_of_week(self, session: WizardSession, user_input: str) -> Tuple[bool, str, WizardSession]:
        """Coleta dia da semana (0-6: seg-dom)"""
        try:
            day = int(user_input.strip())
            if day < 0 or day > 6:
                raise ValueError
        except ValueError:
            return (
                False,
                "⚠️ Digite um número de 0 (segunda) a 6 (domingo):",
                session,
            )

        session.set_collected_value("day_of_week", day)
        session.state = WizardState.COLLECTING_HOUR
        session.updated_at = datetime.utcnow()
        await self.store.update_wizard_session(session)

        msg = self._prompt_for_state(session)
        return True, msg, session

    async def _collect_day_of_month(self, session: WizardSession, user_input: str) -> Tuple[bool, str, WizardSession]:
        """Coleta dia do mês (1-31)"""
        try:
            day = int(user_input.strip())
            if day < 1 or day > 31:
                raise ValueError
        except ValueError:
            return (
                False,
                "⚠️ Digite um número de 1 a 31:",
                session,
            )

        session.set_collected_value("day_of_month", day)
        session.state = WizardState.COLLECTING_HOUR
        session.updated_at = datetime.utcnow()
        await self.store.update_wizard_session(session)

        msg = self._prompt_for_state(session)
        return True, msg, session

    async def _collect_month_day(self, session: WizardSession, user_input: str) -> Tuple[bool, str, WizardSession]:
        """Coleta mês e dia para anual"""
        try:
            parts = user_input.strip().split("/")
            if len(parts) != 2:
                raise ValueError
            day = int(parts[0])
            month = int(parts[1])
            if day < 1 or day > 31 or month < 1 or month > 12:
                raise ValueError
        except ValueError:
            return (
                False,
                "⚠️ Formato inválido. Digite DIA/MÊS (ex: 25/12):",
                session,
            )

        session.set_collected_value("day_of_month", day)
        session.set_collected_value("month", month)
        session.state = WizardState.COLLECTING_HOUR
        session.updated_at = datetime.utcnow()
        await self.store.update_wizard_session(session)

        msg = self._prompt_for_state(session)
        return True, msg, session

    async def _collect_hour(self, session: WizardSession, user_input: str) -> Tuple[bool, str, WizardSession]:
        """Coleta hora (0-23)"""
        try:
            hour = int(user_input.strip())
            if hour < 0 or hour > 23:
                raise ValueError
        except ValueError:
            return (
                False,
                "⚠️ Digite uma hora de 0 a 23:",
                session,
            )

        session.set_collected_value("hour", hour)
        session.state = WizardState.COLLECTING_INSTRUCTION
        session.updated_at = datetime.utcnow()
        await self.store.update_wizard_session(session)

        msg = self._prompt_for_state(session)
        return True, msg, session

    async def _collect_instruction(self, session: WizardSession, user_input: str) -> Tuple[bool, str, WizardSession]:
        """Coleta texto da instrução"""
        instruction = user_input.strip()

        if not instruction or len(instruction) < 5:
            return (
                False,
                "⚠️ Instrução muito curta (mín. 5 caracteres). Tente novamente:",
                session,
            )

        if len(instruction) > 1000:
            return (
                False,
                "⚠️ Instrução muito longa (máx. 1000 caracteres). Tente novamente:",
                session,
            )

        session.set_collected_value("instruction_text", instruction)
        session.state = WizardState.CONFIRMATION
        session.updated_at = datetime.utcnow()
        await self.store.update_wizard_session(session)

        msg = self._prompt_for_state(session)
        return True, msg, session

    async def _confirm(self, session: WizardSession, user_input: str) -> Tuple[bool, str, Optional[WizardSession]]:
        """Confirma criação ou cancela"""
        choice = user_input.strip().lower()

        if choice in ("sim", "s", "yes", "y"):
            # Marcar como concluído (será processado pelo dispatcher)
            session.state = WizardState.COMPLETED
            session.updated_at = datetime.utcnow()
            await self.store.update_wizard_session(session)

            msg = (
                "✅ Agendamento criado com sucesso! "
                "Use /listar para ver suas tarefas agendadas."
            )
            return True, msg, session

        elif choice in ("não", "n", "no"):
            await self.store.delete_wizard_session(session.chat_id)
            msg = "❌ Agendamento cancelado."
            return True, msg, None

        else:
            return (
                False,
                "⚠️ Digite 'sim' ou 'não':",
                session,
            )

    # ────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────

    @staticmethod
    def _prompt_for_state(session: WizardSession) -> str:
        """Gera prompt para o estado atual"""
        title = session.get_collected_value("title", "")

        if session.state == WizardState.COLLECTING_TITLE:
            return "📝 **Nome da tarefa:**\n(ex: Backup do banco de dados)"

        elif session.state == WizardState.COLLECTING_SCHEDULE_TYPE:
            return (
                f"⏰ **Frequência:**\n"
                f"1️⃣ Diária\n"
                f"2️⃣ Semanal\n"
                f"3️⃣ Mensal\n"
                f"4️⃣ Anual\n"
                f"\nDigite o número:"
            )

        elif session.state == WizardState.COLLECTING_DAY_OF_WEEK:
            return (
                "📅 **Qual dia da semana?**\n"
                "0=Segunda, 1=Terça, ..., 6=Domingo\n"
                "\nDigite (0-6):"
            )

        elif session.state == WizardState.COLLECTING_DAY_OF_MONTH:
            return "📅 **Qual dia do mês? (1-31):**"

        elif session.state == WizardState.COLLECTING_MONTH_DAY:
            return "📅 **Qual dia e mês? (DIA/MÊS, ex: 25/12):**"

        elif session.state == WizardState.COLLECTING_HOUR:
            return "🕐 **Qual hora? (0-23):**"

        elif session.state == WizardState.COLLECTING_INSTRUCTION:
            return "📋 **Qual é a instrução? (comando/descrição):**"

        elif session.state == WizardState.CONFIRMATION:
            schedule_type = session.get_collected_value("schedule_type", "unknown")
            hour = session.get_collected_value("hour", "?")
            instruction = session.get_collected_value("instruction_text", "")[:50]

            return (
                f"✅ **Confirmar?**\n\n"
                f"📝 **Nome:** {title}\n"
                f"⏰ **Tipo:** {schedule_type}\n"
                f"🕐 **Hora:** {hour}:00\n"
                f"📋 **Instrução:** {instruction}...\n\n"
                f"Digite 'sim' para salvar ou 'não' para cancelar:"
            )

        return "❓ Estado desconhecido"
