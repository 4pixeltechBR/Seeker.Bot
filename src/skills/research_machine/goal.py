from __future__ import annotations

import logging
from datetime import datetime

from src.core.goals.protocol import (
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)
from src.skills.research_machine.pipeline import ResearchPipeline

log = logging.getLogger("seeker.research_machine")


class ResearchMachineGoal:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self._pipeline = ResearchPipeline(pipeline)
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.30, max_daily_usd=2.0)

    @property
    def name(self) -> str:
        return "research_machine"

    @property
    def interval_seconds(self) -> int:
        return 86400  # Roda ciclo no-op uma vez por dia

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    def serialize_state(self) -> dict:
        return {}

    def load_state(self, state: dict) -> None:
        pass

    async def run_cycle(self) -> GoalResult:
        return GoalResult(success=True, summary="Pesquisa manual — use /research <query> no Telegram")

    async def execute_research(self, query: str) -> GoalResult:
        self._status = GoalStatus.RUNNING
        try:
            data = await self._pipeline.research(query)
            if "error" in data:
                self._status = GoalStatus.ERROR
                return GoalResult(success=False, summary=data["error"])
            obs = data.get("obsidian_path", "")
            nb = data.get("notebook_url", "")
            n_videos = len(data.get("videos", []))
            cost = data.get("cost_usd", 0.0)
            dur = data.get("duration_s", 0.0)
            notif = (
                f"🔬 <b>Research Machine</b>\n\n"
                f"<b>Query:</b> {query}<br/>"
                f"<b>Vídeos:</b> {n_videos}<br/>"
                f"<b>Custo:</b> ${cost:.4f}<br/>"
                f"<b>Duração:</b> {dur:.1f}s<br/>"
            )
            if obs:
                notif += f"📝 <a href='file:///{obs}'>Ver no Obsidian</a><br/>"
            if nb:
                notif += f"📓 <a href='{nb}'>NotebookLM</a>"
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary=f"Pesquisa '{query}' concluída", notification=notif, cost_usd=cost)
        except Exception as e:
            self._status = GoalStatus.ERROR
            log.error(f"[research_machine] execute_research falhou: {e}", exc_info=True)
            return GoalResult(success=False, summary=f"Erro na pesquisa: {e}")


def create_goal(pipeline) -> ResearchMachineGoal:
    return ResearchMachineGoal(pipeline)
