"""
Seeker.Bot — Bug Analyzer Telegram Interface
src/skills/bug_analyzer/telegram_interface.py

Interface Telegram para comando /bug e wizard de análise.
"""

import logging
from enum import Enum

log = logging.getLogger("seeker.bug_analyzer")


class BugWizardState(str, Enum):
    """Estados do wizard de análise de bug"""
    IDLE = "idle"
    ASKING_DESCRIPTION = "asking_description"
    COLLECTING_CONTEXT = "collecting_context"
    ANALYZING = "analyzing"
    RESULTS = "results"
    APPROVAL = "approval"
    CANCELLED = "cancelled"


class BugAnalyzerTelegramInterface:
    """Interface Telegram para análise de bugs"""

    def __init__(self, bug_analyzer):
        """
        Inicializa interface.

        Args:
            bug_analyzer: Instância de BugAnalyzer
        """
        self.bug_analyzer = bug_analyzer
        # Armazena sessões de wizard em memória (chat_id -> estado)
        self._sessions = {}

    async def cmd_bug(self, chat_id: int, user_id: str) -> str:
        """
        Inicia comando /bug.

        Retorna:
            Mensagem inicial pedindo descrição do bug
        """
        log.info(f"[bug_analyzer_ui] /bug iniciado por user {user_id}")

        # Inicia sessão
        self._sessions[chat_id] = {
            "state": BugWizardState.ASKING_DESCRIPTION,
            "user_id": user_id,
            "bug_description": "",
            "chat_history": [],
        }

        return (
            "<b>🐛 Bug Analyzer Seeker.Bot</b>\n\n"
            "Descreva o bug que você encontrou:\n\n"
            "<i>Ex: 'O bot não está reiniciando quando há crash' ou "
            "'Email monitor retorna caixa vazia mas há emails novos'</i>\n\n"
            "Digite sua descrição (próxima mensagem será considerada como contexto)."
        )

    async def process_bug_input(
        self,
        chat_id: int,
        user_message: str,
        chat_history: list[dict],
    ) -> tuple[str, bool]:  # (response, is_complete)
        """
        Processa entrada do usuário no wizard de bug.

        Args:
            chat_id: ID do chat
            user_message: Mensagem do usuário
            chat_history: Histórico completo do chat (últimas N mensagens)

        Returns:
            (resposta para usuário, análise_completa)
        """
        if chat_id not in self._sessions:
            return "❌ Sessão de bug expirou. Digite /bug novamente.", False

        session = self._sessions[chat_id]
        state = session["state"]

        # ESTADO 1: Esperando descrição
        if state == BugWizardState.ASKING_DESCRIPTION:
            session["bug_description"] = user_message
            session["chat_history"] = chat_history[-5:]  # Últimas 5
            session["state"] = BugWizardState.COLLECTING_CONTEXT

            return (
                "⏳ <b>Coletando contexto...</b>\n\n"
                "Analisando chat, logs e identificando padrões de erro...",
                False,
            )

        # ESTADO 2: Fazendo análise
        if state == BugWizardState.COLLECTING_CONTEXT:
            session["state"] = BugWizardState.ANALYZING

            # Inicia análise
            analysis = await self.bug_analyzer.analyze_bug(
                bug_description=session["bug_description"],
                chat_history=session["chat_history"],
                user_id=session["user_id"],
            )

            session["analysis"] = analysis

            # Formata resultado
            result_msg = analysis.get_summary_text()

            # Adiciona opções de próximos passos
            if analysis.has_actionable_fixes():
                result_msg += (
                    "\n\n<b>Próximos passos:</b>\n"
                    "/bug_approve — Avaliar e aplicar correções\n"
                    "/bug_cancel — Descartar análise"
                )
                session["state"] = BugWizardState.RESULTS
            else:
                result_msg += "\n\n<i>Sem correções automáticas disponíveis.</i>"
                session["state"] = BugWizardState.RESULTS

            return (result_msg, True)

        return "❌ Estado desconhecido. Digite /bug novamente.", False

    async def cmd_bug_approve(self, chat_id: int) -> str:
        """
        Aprova e aplica correções sugeridas.

        Fase 2 - será implementada após aprovação do usuário.
        """
        if chat_id not in self._sessions:
            return "❌ Nenhuma análise de bug em progresso. Digite /bug para começar."

        session = self._sessions[chat_id]

        if "analysis" not in session:
            return "❌ Nenhuma análise disponível para aprovação."

        analysis = session["analysis"]

        if not analysis.has_actionable_fixes():
            return "❌ Nenhuma correção automática disponível nesta análise."

        # Fase 2: Aprovação + Aplicação
        # Por enquanto, retorna as sugestões para o usuário revisar manualmente
        return (
            "<b>✅ Correções Sugeridas (Fase 2 - em desenvolvimento)</b>\n\n"
            "As seguintes correções foram identificadas e aguardam aprovação:\n\n"
            + self._format_suggestions_for_approval(analysis)
        )

    def _format_suggestions_for_approval(self, analysis) -> str:
        """Formata sugestões para aprovação manual"""
        lines = []

        for i, sugg in enumerate(analysis.suggestions, 1):
            lines.append(f"<b>{i}. {sugg.file_path}</b>")
            lines.append(f"   Risco: {sugg.risk_level}")
            lines.append(f"   Explicação: {sugg.explanation}")
            lines.append(f"   <code>Antes:</code>")
            lines.append(f"   <code>{sugg.current_code[:80]}...</code>")
            lines.append(f"   <code>Depois:</code>")
            lines.append(f"   <code>{sugg.suggested_code[:80]}...</code>\n")

        lines.append("\n<i>⚠️ Fase 2 implementará aplicação automática com Git backup.</i>")

        return "\n".join(lines)

    async def cmd_bug_cancel(self, chat_id: int) -> str:
        """Cancela análise de bug em progresso"""
        if chat_id in self._sessions:
            session = self._sessions[chat_id]
            session["state"] = BugWizardState.CANCELLED
            del self._sessions[chat_id]

            return "❌ Análise de bug cancelada. Digite /bug para começar nova análise."

        return "❌ Nenhuma análise em progresso."

    def get_session_state(self, chat_id: int) -> BugWizardState:
        """Retorna estado atual da sessão"""
        if chat_id in self._sessions:
            return self._sessions[chat_id]["state"]
        return BugWizardState.IDLE

    def is_in_wizard(self, chat_id: int) -> bool:
        """Verifica se chat está em wizard de bug"""
        return chat_id in self._sessions and self._sessions[chat_id]["state"] not in [
            BugWizardState.IDLE,
            BugWizardState.CANCELLED,
        ]
