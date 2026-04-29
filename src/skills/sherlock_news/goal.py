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

from src.skills.sherlock_news.targets_manager import list_all_targets

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

    def load_targets(self) -> list[dict]:
        try:
            return [t for t in list_all_targets() if t.get("status") == "pending"]
        except Exception as e:
            log.error(f"[sherlock] Erro ao carregar targets: {e}")
            return []

    async def run_cycle(self, force: bool = False) -> GoalResult:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        if self._last_run_date == today_str and not force:
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="SherlockNews já executado hoje", cost_usd=0.0)

        self._status = GoalStatus.RUNNING
        targets = self.load_targets()
        
        if not targets:
            self._last_run_date = today_str if not force else self._last_run_date
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Nenhum alvo pendente no SherlockNews", cost_usd=0.0)

        log.info(f"[sherlock] Verificando {len(targets)} alvos agrupados por categoria")

        # Agrupa targets por categoria
        categories = {}
        for t in targets:
            cat = t.get("category", "LLM").lower()
            categories.setdefault(cat, []).append(t.get("name"))

        total_cost = 0.0
        notifications = []
        
        # Faz uma busca para cada categoria para evitar poluição semântica
        for cat, names in categories.items():
            names_str = ", ".join(names)
            
            # Ajuste de query por categoria
            if "voice" in cat or "tts" in cat:
                search_query = f"launch release update {names_str} text-to-speech voice model"
            elif "image" in cat or "video" in cat:
                search_query = f"launch release update {names_str} generation AI model"
            elif "tool" in cat or "ferramenta" in cat:
                search_query = f"launch release update {names_str} AI tool"
            elif "agent" in cat:
                search_query = f"launch release update {names_str} AI agent framework"
            else:
                search_query = f"launch release status {names_str} AI model"

            try:
                search_results = await self.pipeline.searcher.search(search_query, max_results=4)
                
                if not search_results or not search_results.results:
                    continue

                search_snippet = "\n".join([
                    f"- {r.title}: {r.snippet}"
                    for r in search_results.results
                ])

                from src.providers.cascade import CascadeRole
                analysis_prompt = SYSTEM_PROMPT.format(targets=names_str)
                user_message = f"{search_query}\n\nResultados ({cat}):\n{search_snippet}"

                result = await self.pipeline.cascade_adapter.call(
                    role=CascadeRole.FAST,
                    messages=[
                        {"role": "system", "content": analysis_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.7,
                    max_tokens=1024
                )
                
                content = result.get("content", "").strip()
                if content and len(content) > 20:
                    notifications.append(f"<b>🕵️ Sherlock ({cat.upper()}):</b>\n{content}")
                
                total_cost += result.get("cost_usd", 0.0)
                
            except Exception as cat_e:
                log.error(f"[sherlock] Erro na categoria {cat}: {cat_e}")

        if not force:
            self._last_run_date = today_str
            
        self._status = GoalStatus.IDLE

        if not notifications:
            return GoalResult(
                success=True,
                summary=f"SherlockNews: Checagem concluída para {len(targets)} alvos. Sem novidades relevantes.",
                cost_usd=total_cost
            )
        return GoalResult(
            success=True,
            summary=f"SherlockNews: Checagem concluída para {len(targets)} modelos",
            notification="\n\n---\n\n".join(notifications),
            cost_usd=total_cost
        )

def create_goal(pipeline: SeekerPipeline) -> AutonomousGoal:
    return SherlockNewsGoal(pipeline)
