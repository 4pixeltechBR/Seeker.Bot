"""Performance Metrics - Data Classes for Profiling"""

from dataclasses import dataclass, field
from typing import Dict
from datetime import datetime
import asyncio


@dataclass
class PerformanceMetrics:
    """Métricas de performance agregadas"""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    goal_id: str = ""
    phase_name: str = ""  # "Reflex", "Deliberate", "Deep"

    # Timing
    start_time: float = 0.0
    end_time: float = 0.0

    # Resources
    memory_mb: float = 0.0  # Peak memory usage
    cpu_percent: float = 0.0  # CPU time
    llm_calls: int = 0

    # Token/Cost
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    # Provider info
    provider: str = ""  # "nvidia", "groq", "gemini", etc
    model: str = ""

    # Status
    success: bool = True
    error_msg: str = ""

    @property
    def latency_ms(self) -> float:
        """Latência em millisegundos"""
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "goal_id": self.goal_id,
            "phase": self.phase_name,
            "latency_ms": self.latency_ms,
            "memory_mb": self.memory_mb,
            "cpu_percent": self.cpu_percent,
            "llm_calls": self.llm_calls,
            "tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "provider": self.provider,
            "model": self.model,
            "success": self.success,
        }


@dataclass
class GoalMetrics:
    """Agregação de métricas por goal"""
    goal_id: str
    goal_name: str = ""

    # Counters
    cycles_total: int = 0
    cycles_success: int = 0
    cycles_failed: int = 0

    # Aggregates
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    min_latency_ms: float = float('inf')

    total_tokens: int = 0
    total_memory_mb: float = 0.0

    # Per-provider breakdown
    provider_costs: Dict[str, float] = field(default_factory=dict)
    provider_calls: Dict[str, int] = field(default_factory=dict)

    # Phase breakdown
    phase_latencies: Dict[str, float] = field(default_factory=dict)  # "Reflex", "Deliberate", "Deep"

    @property
    def success_rate(self) -> float:
        if self.cycles_total == 0:
            return 0.0
        return (self.cycles_success / self.cycles_total) * 100

    @property
    def cost_per_success(self) -> float:
        if self.cycles_success == 0:
            return 0.0
        return self.total_cost_usd / self.cycles_success

    def to_dict(self) -> Dict:
        return {
            "goal_id": self.goal_id,
            "goal_name": self.goal_name,
            "cycles": self.cycles_total,
            "success_rate": f"{self.success_rate:.1f}%",
            "total_cost": f"${self.total_cost_usd:.4f}",
            "avg_latency_ms": f"{self.avg_latency_ms:.0f}",
            "tokens": self.total_tokens,
        }
