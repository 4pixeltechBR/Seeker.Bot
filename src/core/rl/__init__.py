"""
Seeker.Bot — Reinforcement Learning Infrastructure
src/core/rl/

Sprint 1 — Instrumentação (2026-04-17)

Módulos:
  reward_collector.py — Captura sinais de reward do Victor e do sistema
  state_encoder.py    — Transforma o estado do bot em feature vector
  backfill.py         — Retroalimenta histórico de logs em formato RL-ready

Ideias planejadas (Sprints 2-3):
  bandits/cascade.py  — LinUCB para seleção de tier do Cascade
  bandits/router.py   — Thompson Sampling para CognitiveLoadRouter
  irl/victor.py       — Inverse RL para aprender o que Victor valoriza
  dqn/budget.py       — Deep Q-Network para alocação de budget
"""

from .reward_collector import RewardCollector, RewardEvent, RewardSignal
from .state_encoder import StateEncoder, SeekerState
from .bandits import CascadeBandit, BanditDecision, BanditMode

__all__ = [
    "RewardCollector",
    "RewardEvent",
    "RewardSignal",
    "StateEncoder",
    "SeekerState",
    "CascadeBandit",
    "BanditDecision",
    "BanditMode",
]
