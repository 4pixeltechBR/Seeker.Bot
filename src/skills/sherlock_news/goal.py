"""
Seeker.Bot — SherlockNews Goal
src/skills/sherlock_news/goal.py

Monitoramento diário de modelos de IA de interesse.
Executa às 08:00 todos os dias.
"""

import asyncio
import logging
import json
import os
from datetime import datetime, timedelta

from src.core.pipeline import SeekerPipeline
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel,
)
from src.skills.sherlock_news.prompts import SYSTEM_PROMPT, USER_PROMPT

log = logging.getLogger("seeker.sherlock")

TARGETS_FILE = os.path.join(os.path.dirname(__file__), "targets.json")


class SherlockNewsGoal:
    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(
            max_per_cycle_usd=0.05,
            max_daily_usd=0.10,
        )

        self.target_hour = 8
        self.target_minute = 0
        self._last_run_date = ""

    @property
    def name(self) -> str:
        return "sherlock_news"

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
            "last_run_date": self._last_run_date,
        }

    def load_state(self, state: dict) -> None:
        self._last_run_date = state.get("last_run_date", "")

    def load_targets(self) -> list[str]:
        if not os.path.exists(TARGETS_FILE):
            return []
        try:
            with open(TARGETS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [t["name"] for t in data if t.get("status") == "pending"]
        except Exception as e:
            log.error(f"[sherlock] Erro ao carregar targets: {e}")
            return []

    async def run_cycle(self) -> GoalResult:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        if self._last_run_date == today_str:
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="SherlockNews já executado hoje", cost_usd=0.0)

        self._status = GoalStatus.RUNNING
        targets = self.load_targets()
        
        if not targets:
            self._last_run_date = today_str
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Nenhum alvo pendente no SherlockNews", cost_usd=0.0)

        log.info(f"[sherlock] Verificando {len(targets)} alvos: {targets}")
        
        # Constrói query de busca combinada
        targets_str = ", ".join(targets)
        search_query = f"launch status {targets_str} model"
        
        # Executa descoberta via Pipeline (Web Search + LLM Reasoning)
        # Usamos o pipeline para fazer o "trabalho sujo" de decidir profundidade
        try:
            # Forçamos busca web e análise detalhada
            result = await self.pipeline.execute(
                user_input=f"SherlockNews: {search_query}",
                depth_override="deliberate", # Focado em fatos/web
                system_override=SYSTEM_PROMPT.format(targets=targets_str)
            )
            
            self._last_run_date = today_str
            self._status = GoalStatus.IDLE
            
            # Limpa o resultado (markdown para HTML simples que o Telegram aceita)
            # No Seeker.Bot, o Notifier costuma usar md_to_telegram_html
            
            return GoalResult(
                success=result.success,
                summary=f"Checagem SherlockNews para {len(targets)} modelos",
                notification=result.content,
                cost_usd=result.total_cost_usd
            )

        except Exception as e:
            self._status = GoalStatus.ERROR
            log.error(f"[sherlock] Erro no ciclo: {e}")
            return GoalResult(success=False, summary=f"Erro no SherlockNews: {e}", cost_usd=0.0)


def create_goal(pipeline: SeekerPipeline) -> AutonomousGoal:
    return SherlockNewsGoal(pipeline)
