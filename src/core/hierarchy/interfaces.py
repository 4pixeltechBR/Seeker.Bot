"""
Seeker.Bot v1.0 - Hierarchy Interfaces
LangGraph Supervisor + Crews Architecture

Core protocol definitions for hierarchical agents.

NOTE: CognitiveDepth is imported from router.cognitive_load to maintain consistency
"""

from typing import Protocol, Optional, Any, runtime_checkable
from dataclasses import dataclass
from enum import Enum

# Import unified CognitiveDepth from existing router
from ..router.cognitive_load import CognitiveDepth


@dataclass
class CrewRequest:
    """Input to any crew"""
    user_input: str
    cognitive_depth: CognitiveDepth
    memory_context: list[str]  # Top-k similar facts from semantic search
    user_id: int
    session_id: str
    timeout_sec: float = 30.0
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class CrewResult:
    """Output from any crew"""
    response: str
    crew_id: str
    cost_usd: float
    llm_calls: int
    confidence: float  # 0-1
    latency_ms: int
    sources: list[str]
    should_save_fact: bool = False
    internal_state: dict[str, Any] = None

    def __post_init__(self):
        if self.internal_state is None:
            self.internal_state = {}


class CrewPriority(str, Enum):
    """Execution priority levels"""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


@runtime_checkable
class Crew(Protocol):
    """Protocol for hierarchical crew agents"""

    crew_id: str
    priority: CrewPriority

    async def execute(self, request: CrewRequest) -> CrewResult:
        """Execute crew with given request"""
        ...

    async def health_check(self) -> bool:
        """Check if crew is operational"""
        ...

    def get_status(self) -> dict[str, Any]:
        """Get crew status/metrics"""
        ...


@dataclass
class SupervisorDecision:
    """Supervisor's routing decision"""
    target_crews: list[str]  # Which crews to invoke
    parallelizable: bool  # Can crews run in parallel?
    cognitive_depth: CognitiveDepth
    estimated_cost: float
    estimated_latency_ms: int
    reasoning: str


@dataclass
class ProviderRequest:
    """Request to LLM provider"""
    prompt: str
    max_tokens: int
    temperature: float
    crew_id: str
    task_type: str  # "monitor", "hunt", "execute", "analyze", "vision", "admin"
    model_preference: str = "auto"


@dataclass
class ProviderResponse:
    """Response from LLM provider"""
    text: str
    tokens_used: int
    cost: float
    provider: str
    latency_ms: float
    model: str
