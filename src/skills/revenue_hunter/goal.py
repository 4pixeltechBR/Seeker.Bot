"""
Seeker.Bot — Revenue Hunter Goal Factory
src/skills/revenue_hunter/goal.py

Factory function para o Goal Registry.
Convenção: create_goal(pipeline) -> AutonomousGoal
"""

from src.skills.revenue_hunter.miner import RevenueMiner


def create_goal(pipeline):
    """Factory chamada pelo Goal Registry."""
    return RevenueMiner(pipeline)
