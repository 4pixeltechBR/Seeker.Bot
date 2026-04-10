"""
Seeker.Bot — Email Monitor Goal
src/skills/email_monitor/goal.py

Lê emails não lidos via IMAP diariamente às 08:45.
Filtra ruído, sumariza ativamente através da Matriz de Triagem (Urgente, Informativo, Ruído) e notifica.
"""

import logging
import os
from datetime import datetime, timedelta

from src.core.pipeline import SeekerPipeline
from src.core.utils import parse_llm_json
from src.providers.base import LLMRequest, invoke_with_fallback
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel,
)
from src.channels.email.imap_reader import IMAPReader
from config.models import CognitiveRole

log = logging.getLogger("seeker.email_monitor")

# Remetentes/assuntos que indicam email automático (skip)
_DEFAULT_SKIP_SUBJECTS = [
    "unsubscribe", "noreply", "no-reply", "newsletter", "notification",
    "alert", "automated", "do not reply", "confirmação", "confirmation",
    "verify", "verificar", "invoice", "fatura", "recibo", "receipt",
]

SUMMARIZE_PROMPT = """\
Você é um assistente executivo e triador de caixa de entrada de altíssimo nível.
Analise os emails não lidos abaixo. Seu objetivo é COMPRIMIR a informação para economizar o tempo do usuário.

EMAILS BRUTOS:
{emails_block}

INSTRUÇÕES DE TRIAGEM RÍGIDAS:
1. Classifique na Matriz: URGENTE (requer ação humana), INFORMATIVO (útil ler), RUÍDO (marketing/spam).
2. Para Urgentes: De | Assunto | Resumo 1 linha | Ação Exigida.
3. Para Informativos: Agrupe em tópicos curtos de 1 linha.
4. Para Ruído: Apenas CONTE. Nunca descreva newsletters, a menos que haja ação importante (ex: aviso de cancelamento). Apenas diga "X emails de lojas / newsletters ignorados" e liste botões/links de unsubscribe se encontrar.

Retorne APENAS o briefing formatado em HTML/Markdown do Telegram, usando estritamente este layout:

🔴 <b>URGENTE / AÇÃO NECESSÁRIA</b>
[Liste emails urgentes]

🟡 <b>INFORMATIVO ÚTIL</b>
[Liste informativos úteis em 1 linha]

⚪ <b>RUÍDO & NEWSLETTERS</b>
[Resumo ninja agregado]
"""

class EmailMonitorGoal:
    """
    Monitora inbox diariamente às 08:45.
    Filtra ruído, sumariza ativamente e notifica no Telegram.
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.03, max_daily_usd=0.10)
        self._seen_ids: set[str] = set()

        self.target_hour = 8
        self.target_minute = 45
        self._last_run_date = ""

        # Filtros de prioridade
        priority_raw = os.getenv("EMAIL_PRIORITY_SENDERS", "")
        self._priority_senders = {
            s.strip().lower() for s in priority_raw.split(",") if s.strip()
        }
        skip_raw = os.getenv("EMAIL_SKIP_SUBJECTS", "")
        custom_skips = {s.strip().lower() for s in skip_raw.split(",") if s.strip()}
        self._skip_subjects = set(_DEFAULT_SKIP_SUBJECTS) | custom_skips

    # ── Protocol ──────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "email_monitor"

    @property
    def interval_seconds(self) -> int:
        now = datetime.now()
        target = now.replace(
            hour=self.target_hour, minute=self.target_minute,
            second=0, microsecond=0,
        )
        if now >= target:
            target += timedelta(days=1)
        wait = (target - now).total_seconds()
        # Cap interval to 1 hour max so we can shutdown bot gracefully if needed
        return max(60, min(3600, int(wait)))

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    def serialize_state(self) -> dict:
        return {
            "seen_ids": list(self._seen_ids)[-1000:],
            "last_run_date": self._last_run_date,
        }

    def load_state(self, state: dict) -> None:
        self._seen_ids = set(state.get("seen_ids", []))
        self._last_run_date = state.get("last_run_date", "")
        log.info(f"[email_monitor] Estado carregado. Última execução: {self._last_run_date}")

    # ── Ciclo principal ────────────────────────────────────────

    async def run_cycle(self) -> GoalResult:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        if self._last_run_date == today_str:
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Inbox Digest já executado hoje.", cost_usd=0.0)

        target_today = now.replace(
            hour=self.target_hour, minute=self.target_minute,
            second=0, microsecond=0,
        )
        if now < target_today:
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary=f"Aguardando {self.target_hour:02d}:{self.target_minute:02d}",
                cost_usd=0.0,
            )

        self._status = GoalStatus.RUNNING
        cycle_cost = 0.0

        try:
            # Tenta via Gmail API (mais confiável que IMAP)
            emails = await self._fetch_unread_gmail_api()

            if emails is None:
                # Fallback para IMAP se API não disponível
                reader = IMAPReader.from_env()
                if not reader:
                    self._status = GoalStatus.IDLE
                    return GoalResult(
                        success=True,
                        summary="Gmail API e IMAP não configurados — skipping.",
                        cost_usd=0.0,
                    )
                emails = await reader.fetch_unread_emails(max_emails=30)

            # Busca max 30 não lidos (já feito acima)
            if emails is None:
                emails = []

            if not emails:
                self._last_run_date = today_str
                self._status = GoalStatus.IDLE
                return GoalResult(
                    success=True,
                    summary="Nenhum email não lido no inbox hoje.",
                    notification="<b>📬 Daily Inbox Digest</b>\n\n<i>Sua caixa de entrada está limpa! Nenhum email novo aguardando.</i>",
                    cost_usd=0.0,
                )

            # Filtra já vistos nesta máquina de estado
            new_emails = [e for e in emails if e["id"] not in self._seen_ids]

            if not new_emails:
                self._last_run_date = today_str
                self._status = GoalStatus.IDLE
                return GoalResult(
                    success=True,
                    summary=f"{len(emails)} emails lidos, nenhum novo para o digest.",
                    cost_usd=0.0,
                )

            # Marca como vistos na memória local do bot
            for e in new_emails:
                self._seen_ids.add(e["id"])

            # Envia p/ LLM sumarizar
            emails_block = self._format_for_llm(new_emails)
            response = await invoke_with_fallback(
                CognitiveRole.FAST,  # Gemini Flash
                LLMRequest(
                    messages=[{"role": "user", "content": SUMMARIZE_PROMPT.format(
                        emails_block=emails_block
                    )}],
                    system="Você é um assistente executivo implacável. Aplique a Matriz de Triagem rigorosamente.",
                    max_tokens=800,
                    temperature=0.1,
                ),
                self.pipeline.model_router,
                self.pipeline.api_keys,
            )
            cycle_cost += response.cost_usd
            summary_text = response.text.strip()

            count = len(new_emails)
            notification = (
                f"<b>📬 Daily Inbox Digest</b>\n"
                f"<i>Analisados {count} email(s) da madrugada</i>\n\n"
                f"{summary_text}"
            )

            # Registra sucesso e hoje como rodado
            self._last_run_date = today_str
            self._status = GoalStatus.IDLE
            
            return GoalResult(
                success=True,
                summary=f"Inbox Digest entregue para {count} emails",
                notification=notification,
                cost_usd=cycle_cost,
            )

        except Exception as e:
            self._status = GoalStatus.ERROR
            log.error(f"[email_monitor] Erro no ciclo: {e}", exc_info=True)
            return GoalResult(
                success=False,
                summary=f"Falha: {e}",
                cost_usd=cycle_cost,
            )

    # ── Helpers ───────────────────────────────────────────────

    async def _fetch_unread_gmail_api(self) -> list[dict] | None:
        """
        Busca emails não lidos via Gmail API (alternativa ao IMAP).
        Mais confiável e sem problemas de SSL/Windows.
        """
        try:
            from mcp__b23351a3_c0fc_4272_b199_a78590884214__gmail_search_messages import (
                gmail_search_messages
            )
        except ImportError:
            log.debug("[email_monitor] Gmail API MCP não disponível, usando IMAP")
            return None

        try:
            # Importa a função MCP direto
            import sys
            sys.path.insert(0, str(__file__).rsplit('\\', 4)[0])  # Vai para src/

            # Busca emails não lidos via Gmail API
            # Usar a mcp__b23351a3_c0fc_4272_b199_a78590884214__gmail_search_messages
            log.debug("[email_monitor] Tentando buscar via Gmail API...")

            # Por enquanto, retorna None para usar fallback IMAP
            # TODO: Integrar MCP Gmail API quando disponível
            return None

        except Exception as e:
            log.debug(f"[email_monitor] Gmail API fallback: {e}")
            return None

    def _format_for_llm(self, emails: list[dict]) -> str:
        lines = []
        for i, e in enumerate(emails, 1):
            body_trunc = e['body'][:1000]
            lines.append(
                f"--- [EMAIL {i}] ---\n"
                f"De: {e['sender']}\n"
                f"Assunto: {e['subject']}\n"
                f"Data: {e['date']}\n"
                f"Preview: {body_trunc}\n"
            )
        return "\n".join(lines)

def create_goal(pipeline: SeekerPipeline) -> EmailMonitorGoal:
    return EmailMonitorGoal(pipeline)
