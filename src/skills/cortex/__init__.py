"""
Cortex Memory Pipeline
Consolida os insights do Seeker e faz o digest diário do Vault do Obsidian.
"""
from .goal import CortexConsolidatorGoal, create_goal

__all__ = ["CortexConsolidatorGoal", "create_goal"]
