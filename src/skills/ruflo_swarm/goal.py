from __future__ import annotations

import logging
from datetime import datetime

from src.core.goals.protocol import (
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)
from src.skills.ruflo_swarm import store
from src.skills.ruflo_swarm.policy import ARMS, ArmConfig, BanditPolicy
from src.skills.ruflo_swarm.swarm import SwarmRunner, SwarmTask

log = logging.getLogger("seeker.ruflo_swarm")


class RufloSwarmGoal:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.bandit = BanditPolicy()
        self.runner = SwarmRunner(pipeline, max_agents=12)
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.50, max_daily_usd=2.0)
        self._last_run = ""

    @property
    def name(self) -> str:
        return "ruflo_swarm"

    @property
    def interval_seconds(self) -> int:
        return 3600

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
            "bandit": self.bandit.serialize(),
            "last_run": self._last_run,
            "last_calibration": getattr(self, "_last_calibration", ""),
        }

    def load_state(self, state: dict) -> None:
        bdata = state.get("bandit", {})
        if bdata:
            self.bandit = BanditPolicy.deserialize(bdata)
        self._last_run = state.get("last_run", "")

    async def run_cycle(self) -> GoalResult:
        today = datetime.now().isoformat()[:10]
        if self._last_run == today:
            return GoalResult(success=True, summary="Já calibrado hoje")

        self._status = GoalStatus.RUNNING
        bstate = store.load_state()
        bstate["bandit"] = self.bandit.serialize()

        calib_tasks = [
            SwarmTask(id="cal_1", goal='Resuma em 3 linhas: "O que é um agente autônomo?"', role=arm.role, max_turns=arm.max_turns)
            for arm in ARMS[:3]
        ]
        results = await self.runner.dispatch(calib_tasks, semaphore=3, learn=True, policy=self.bandit)

        bstate["bandit"] = self.bandit.serialize()
        bstate["last_calibration"] = today
        bstate["calibration_runs"] = bstate.get("calibration_runs", [])
        bstate["calibration_runs"].append({
            "date": today,
            "rounds": self.bandit.state.rounds,
            "best_arm": self.bandit.best_arm_key(),
        })
        store.save_state(bstate)

        self._last_run = today
        self._status = GoalStatus.IDLE

        best = self.bandit.best_arm_key()
        success_count = sum(1 for r in results if r.success)
        cost = sum(r.cost_usd for r in results)
        notif = (
            f"🎯 <b>Ruflo Swarm — Calibração</b>\n\n"
            f"<b>Braço vencedor:</b> {best}<br/>"
            f"<b>Sucesso:</b> {success_count}/{len(results)}<br/>"
            f"<b>Custo:</b> ${cost:.4f}<br/>"
            f"<b>Rodadas totais:</b> {self.bandit.state.rounds}"
        )

        return GoalResult(
            success=True,
            summary=f"Calibração: braço={best} sucesso={success_count}/{len(results)}",
            notification=notif,
            cost_usd=cost,
        )


def create_goal(pipeline) -> RufloSwarmGoal:
    return RufloSwarmGoal(pipeline)
