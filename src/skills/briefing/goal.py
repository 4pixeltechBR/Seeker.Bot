"""
Seeker.Bot — MailNews Goal
src/skills/briefing/goal.py

Assistente Pessoal Diário
Lê a caixa de entrada (emails UNSEEN) nos horários estipulados 
(ex: 07:30 e 16:00) e entrega um resumo via Telegram no formato de briefing.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from src.core.pipeline import SeekerPipeline
from src.providers.base import LLMRequest, invoke_with_fallback
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel
)
from src.channels.email.imap_reader import IMAPReader
from src.skills.briefing.prompts import BRIEFING_PROMPT
from config.models import CognitiveRole

log = logging.getLogger("seeker.dailynews")

class DailyNewsGoal:
    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        
        # Horários fixos para o DailyNews
        self.schedules = [(7, 30), (16, 0)]
        
        # Controle de quando rodou: string iterada como "YYYY-MM-DD:HH:MM"
        self._last_runs = set()

        # Pequeno budget para o ciclo
        self._budget = GoalBudget(
            max_per_cycle_usd=0.01,
            max_daily_usd=0.05,
        )

        self.reader = IMAPReader.from_env()

    @property
    def name(self) -> str:
        return "daily_news"

    @property
    def interval_seconds(self) -> int:
        """
        Retorna os segundos restantes até o próximo horário agendado.
        Se faltar mais de 1h, dorme 1h para rechecar.
        """
        now = datetime.now()
        next_target = None
        min_diff = float("inf")
        
        for hour, minute in self.schedules:
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
                
            diff = (target - now).total_seconds()
            if diff < min_diff:
                min_diff = diff
                next_target = target
        
        # Se min_diff > 3600 (1 hora), dorme no máximo 1 hora
        return max(60, min(3600, int(min_diff)))

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        # Só Telegram, conforme solicitado.
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    async def run_cycle(self) -> GoalResult:
        now = datetime.now()
        
        # Encontra o horário alvo que já passou no dia de hoje e que tá mais perto
        applicable_schedule = None
        for hour, minute in self.schedules:
            target_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # Damos uma janela de segurança de 1 hora para ele não rodar catch-up atrasadíssimo de ontem
            if 0 <= (now - target_today).total_seconds() < 3600:
                applicable_schedule = target_today
                break
                
        if not applicable_schedule:
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Aguardando horários agendados", cost_usd=0.0)
            
        run_identifier = applicable_schedule.strftime("%Y-%m-%d:%H:%M")
        
        if run_identifier in self._last_runs:
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="DailyNews já executado para este horário", cost_usd=0.0)

        # 🚀 HORA DO DAILYNEWS 🚀
        self._status = GoalStatus.RUNNING

        if not self.reader:
            self._status = GoalStatus.ERROR
            return GoalResult(success=False, summary="IMAP Config inválido", cost_usd=0.0)

        log.info(f"[dailynews] Baixando emails não lidos para {run_identifier}...")
        emails = await self.reader.fetch_unread_emails(max_emails=15)
        
        if not emails:
            # Salva que "rodou" 
            self._last_runs.add(run_identifier)
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True, 
                summary="Caixa de entrada vazia", 
                notification="<b>☀️ DailyNews Seeker</b>\n\n<i>Sua caixa de entrada está limpa agora! Sem e-mails pendentes.</i>"
            )

        # Estrutura contexto para envio ao LLM
        ctx_list = []
        for em in emails:
            ctx_list.append(
                f"De: {em['sender']}\n"
                f"Assunto: {em['subject']}\n"
                f"Conteúdo:\n{em['body']}\n"
                f"{'-'*40}"
            )
        
        prompt = BRIEFING_PROMPT.format(
            total_emails=len(emails),
            emails_context="\n\n".join(ctx_list)
        )

        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            system="Você é um Assistente Executivo Sênior analisando a caixa de entrada do seu chefe. Output HTML formatado pro Telegram.",
            temperature=0.3,
            max_tokens=1500
        )

        try:
            resp = await invoke_with_fallback(
                CognitiveRole.SYNTHESIS, # Fast / Synthesis pro processamento
                req,
                self.pipeline.model_router,
                self.pipeline.api_keys,
            )
        except Exception as e:
            self._status = GoalStatus.ERROR
            log.error(f"[dailynews] Falha cognitiva: {e}", exc_info=True)
            raise e

        # Finaliza com sucesso
        self._last_runs.add(run_identifier)
        self._status = GoalStatus.IDLE

        # Limpamos marcadores ruins do llm
        notificacao = resp.text.strip()
        if notificacao.startswith("```html"):
            notificacao = notificacao[7:]
        elif notificacao.startswith("```"):
            notificacao = notificacao[3:]
        if notificacao.endswith("```"):
            notificacao = notificacao[:-3]

        return GoalResult(
            success=True,
            summary=f"DailyNews rodado com {len(emails)} emails lidos.",
            notification=notificacao.strip(),
            cost_usd=resp.cost_usd
        )

    def serialize_state(self) -> dict:
        return {
            "last_runs": list(self._last_runs),
        }

    def load_state(self, state: dict) -> None:
        runs = state.get("last_runs", [])
        self._last_runs = set(runs)


def create_goal(pipeline) -> DailyNewsGoal:
    """Factory chamada pelo Goal Registry."""
    return DailyNewsGoal(pipeline)
