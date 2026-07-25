"""
Darwinian Evolver Goal — auto-evolução de prompts baseada em sinais de RL.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.core.goals.protocol import (
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)
from src.core.pipeline import SeekerPipeline

logger = logging.getLogger("seeker.darwinian_evolver")


class DarwinianEvolverGoal:
    """Evolve prompts and heuristics based on RL reward signals and error patterns."""

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(
            max_per_cycle_usd=0.30,
            max_daily_usd=2.0,
        )
        base = Path(__file__).resolve().parent.parent.parent.parent
        self.genome_path = base / "data" / "darwinian_genome.json"
        self.history_path = base / "data" / "darwinian_history.jsonl"
        self.genome_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "darwinian_evolver"

    @property
    def interval_seconds(self) -> int:
        return 86400

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
        self._status = GoalStatus.RUNNING
        try:
            genome = self._compute_genome()
            previous = self._load_previous_genome()
            mutations = self._detect_mutations(genome, previous)
            recommendations = self._build_recommendations(mutations, genome)

            genome["last_run"] = datetime.now().isoformat()
            self._save_genome(genome)
            self._save_history(genome)

            if recommendations:
                notification = (
                    f"🧬 <b>Darwinian Evolver — {len(recommendations)} recomendacoes</b>\n\n"
                    + "\n".join(recommendations)
                )
                summary = f"{len(recommendations)} recomendacoes de evolucao"
            else:
                notification = None
                summary = "Sistema estavel — nenhuma mutacao necessaria"

            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary=summary,
                notification=notification,
                cost_usd=0.0,
            )
        except Exception as e:
            logger.error(f"[darwinian_evolver] Erro no ciclo: {e}", exc_info=True)
            self._status = GoalStatus.ERROR
            return GoalResult(success=False, summary=f"Erro: {e}")

    def _compute_genome(self) -> dict:
        genome = {"fitness": {}, "recommendations": [], "confidence": 0}
        try:
            stats = self.pipeline.reward_collector.get_stats()
            genome["rl"] = {
                "total_events": stats.get("total_events", 0),
                "avg_reward": stats.get("avg_reward", 0.0),
                "by_action": {
                    k: {"count": v.get("count", 0), "avg_reward": v.get("avg_reward", 0.0)}
                    for k, v in stats.get("by_action", {}).items()
                },
            }
        except Exception as e:
            logger.warning(f"[darwinian] RL stats failed: {e}")
            genome["rl"] = {"total_events": 0}

        try:
            bandit_stats = self.pipeline.cascade_bandit.get_stats()
            genome["bandit"] = {
                "mode": bandit_stats.get("mode", "shadow"),
                "agreement_rate": bandit_stats.get("agreement_rate", 0.0),
                "ready_for_active": bandit_stats.get("ready_for_active", False),
                "updates": sum(bandit_stats.get("updates_per_arm", {}).values()),
            }
        except Exception as e:
            logger.warning(f"[darwinian] Bandit stats failed: {e}")
            genome["bandit"] = {"mode": "shadow"}

        genome["timestamp"] = datetime.now().isoformat()
        return genome

    def _detect_mutations(self, genome: dict, previous: Optional[dict]) -> list[str]:
        mutations = []
        rl = genome.get("rl", {})
        bandit = genome.get("bandit", {})
        avg_reward = rl.get("avg_reward", 0.0)
        by_action = rl.get("by_action", {})

        reflex = by_action.get("reflex", {}).get("avg_reward", 0.0)
        deliberate = by_action.get("deliberate", {}).get("avg_reward", 0.0)

        if avg_reward != 0 and reflex > avg_reward + 0.2:
            mutations.append("REFLEX overperforma — router usa DELIBERATE desnecessariamente")
        if avg_reward != 0 and deliberate < avg_reward - 0.2:
            mutations.append("DELIBERATE underperforma — REFLEX bastaria para mais queries")
        if bandit.get("agreement_rate", 0) < 0.2 and avg_reward < -0.1:
            mutations.append("Router e bandit divergem + reward baixo — revisar decisor")
        if bandit.get("agreement_rate", 0) > 0.8 and avg_reward > 0.2:
            mutations.append("Router e bandit alinhados + reward alto — sistema convergindo")
        if bandit.get("ready_for_active", False) and bandit.get("mode") != "ACTIVE":
            mutations.append("Bandit pronto para ACTIVE — ativar economia de 50%+")

        confidence = min(100, max(0, int(abs(bandit.get("agreement_rate", 0) or 0) * 100)))
        genome["confidence"] = confidence
        genome["fitness"] = {"reflex": reflex, "deliberate": deliberate, "avg": avg_reward}
        return mutations

    def _build_recommendations(self, mutations: list[str], genome: dict) -> list[str]:
        recs = []
        for m in mutations:
            if "overperforma" in m:
                recs.append("💡 Reduzir threshold REFLEX no CognitiveLoadRouter")
            elif "underperforma" in m:
                recs.append("💡 Aumentar threshold DELIBERATE — preferir REFLEX")
            elif "divergem" in m:
                recs.append("⚠️ Revisar pesos do CognitiveLoadRouter vs reward collector")
            elif "convergindo" in m:
                recs.append("✅ Sistema convergindo bem — continuar coleta de rewards")
            elif "pronto para ACTIVE" in m:
                recs.append("⚡ Ativar bandit em modo ACTIVE para economizar queries simples")
        if recs:
            recs.append(f"\n🎯 Confiança da evolução: {genome.get('confidence', 0)}%")
        return recs

    def _load_previous_genome(self) -> Optional[dict]:
        if not self.genome_path.exists():
            return None
        try:
            with open(self.genome_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[darwinian] Failed to load previous genome: {e}")
            return None

    def _save_genome(self, genome: dict):
        with open(self.genome_path, "w", encoding="utf-8") as f:
            json.dump(genome, f, indent=2, ensure_ascii=False)

    def _save_history(self, genome: dict):
        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(genome, ensure_ascii=False) + "\n")


def create_goal(pipeline) -> DarwinianEvolverGoal:
    return DarwinianEvolverGoal(pipeline)
