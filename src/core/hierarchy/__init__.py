"""
Seeker.Bot v1.0 - Hierarchical Architecture

LangGraph Supervisor + 6 Specialized Crews

Imports all components for easy access.
"""

from .interfaces import (
    CognitiveDepth,
    CrewRequest,
    CrewResult,
    Crew,
    CrewPriority,
    SupervisorDecision,
    ProviderRequest,
    ProviderResponse,
)

from .supervisor import Supervisor, SupervisorState

from .memory.events import GoalEventLog, GoalEvent, GoalEventType

from .crews import (
    BaseCrew,
    executor_crew,
    analyst_crew,
)

__all__ = [
    # Interfaces
    "CognitiveDepth",
    "CrewRequest",
    "CrewResult",
    "Crew",
    "CrewPriority",
    "SupervisorDecision",
    "ProviderRequest",
    "ProviderResponse",
    # Supervisor
    "Supervisor",
    "SupervisorState",
    # Memory
    "GoalEventLog",
    "GoalEvent",
    "GoalEventType",
    # Crews
    "BaseCrew",
    "executor_crew",
    "analyst_crew",
]
