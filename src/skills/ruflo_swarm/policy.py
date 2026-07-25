from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field

from config.models import CognitiveRole

log = logging.getLogger("seeker.ruflo_swarm.policy")


@dataclass(frozen=True)
class ArmConfig:
    role: CognitiveRole
    max_turns: int
    temperature: float


ARMS: list[ArmConfig] = [
    ArmConfig(CognitiveRole.FAST, 2, 0.1),
    ArmConfig(CognitiveRole.FAST, 3, 0.1),
    ArmConfig(CognitiveRole.FAST, 3, 0.3),
    ArmConfig(CognitiveRole.DEEP, 2, 0.1),
    ArmConfig(CognitiveRole.DEEP, 3, 0.15),
    ArmConfig(CognitiveRole.SYNTHESIS, 3, 0.2),
]


@dataclass
class ArmStats:
    plays: int = 0
    total_reward: float = 0.0

    @property
    def mean_reward(self) -> float:
        return self.total_reward / self.plays if self.plays > 0 else 0.0


@dataclass
class BanditState:
    arms: dict[str, ArmStats] = field(default_factory=lambda: {a: ArmStats() for a in _arm_keys()})
    rounds: int = 0


def _arm_keys() -> list[str]:
    return [f"{a.role.value}_{a.max_turns}_{a.temperature}" for a in ARMS]


def _key_for(arm: ArmConfig) -> str:
    return f"{arm.role.value}_{arm.max_turns}_{arm.temperature}"


class BanditPolicy:
    def __init__(self, state: BanditState | None = None):
        self.state = state or BanditState()

    def select_arm(self) -> ArmConfig:
        n_arms = len(ARMS)
        for idx, arm in enumerate(ARMS):
            key = _arm_keys()[idx]
            if self.state.arms[key].plays == 0:
                return arm
        total_plays = self.state.rounds
        best_score = -float("inf")
        best_arm = ARMS[0]
        for idx, arm in enumerate(ARMS):
            key = _arm_keys()[idx]
            stats = self.state.arms[key]
            mean = stats.mean_reward
            bonus = math.sqrt(2 * math.log(total_plays + 1) / stats.plays)
            score = mean + bonus
            if score > best_score:
                best_score = score
                best_arm = arm
        return best_arm

    def update(self, arm: ArmConfig, reward: float) -> None:
        key = _key_for(arm)
        if key not in self.state.arms:
            self.state.arms[key] = ArmStats()
        self.state.arms[key].plays += 1
        self.state.arms[key].total_reward += reward
        self.state.rounds += 1

    def best_arm_key(self) -> str:
        best_key = max(self.state.arms, key=lambda k: self.state.arms[k].mean_reward)
        return best_key

    def summary(self) -> str:
        lines = []
        for key, stats in self.state.arms.items():
            label = f"s={stats.plays}, r={stats.mean_reward:.2f}"
            lines.append(f"  {key}: {label}")
        return f"Bandit ({self.state.rounds} rounds):\n" + "\n".join(lines)

    def serialize(self) -> dict:
        return {
            "arms": {k: {"plays": v.plays, "total_reward": v.total_reward} for k, v in self.state.arms.items()},
            "rounds": self.state.rounds,
        }

    @classmethod
    def deserialize(cls, data: dict) -> BanditPolicy:
        state = BanditState(rounds=data.get("rounds", 0))
        for key, stats_data in data.get("arms", {}).items():
            state.arms[key] = ArmStats(plays=stats_data.get("plays", 0), total_reward=stats_data.get("total_reward", 0.0))
        return cls(state)
