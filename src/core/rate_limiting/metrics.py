"""Rate Limit Metrics and Statistics"""

from dataclasses import dataclass, field
from typing import Dict
from datetime import datetime
from collections import deque


@dataclass
class RateLimitMetrics:
    """Métricas de uma tentativa de rate limit"""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    provider: str = ""
    model: str = ""

    # Timing
    request_time: float = 0.0  # Quando foi requisitado
    wait_time: float = 0.0      # Quanto aguardou (0 se nenhum)
    retry_count: int = 0        # Quantas vezes foi retentado
    backoff_delays: list = field(default_factory=list)  # Delays de cada retry

    # Headers
    retry_after: float = 0.0    # Retry-After header value (segundos)

    # Status
    success: bool = True
    error_msg: str = ""

    def total_delay_ms(self) -> float:
        """Total delay em milliseconds"""
        return (self.wait_time + sum(self.backoff_delays)) * 1000

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "provider": self.provider,
            "model": self.model,
            "wait_time_ms": self.wait_time * 1000,
            "retry_count": self.retry_count,
            "total_delay_ms": self.total_delay_ms(),
            "retry_after": self.retry_after,
            "success": self.success,
        }


@dataclass
class RateLimitStats:
    """Agregação de estatísticas de rate limiting"""
    provider: str
    model: str = ""

    # Counters
    total_requests: int = 0
    total_rate_limits_hit: int = 0
    total_retries: int = 0
    total_successes: int = 0
    total_failures: int = 0

    # Timing
    total_wait_time: float = 0.0       # Segundos
    avg_wait_time: float = 0.0
    max_wait_time: float = 0.0
    total_backoff_time: float = 0.0
    avg_backoff_time: float = 0.0

    # Retry-After
    max_retry_after: float = 0.0       # Maior Retry-After visto

    # Queue metrics
    max_queue_size: int = 0            # Maior tamanho da queue observado

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 100.0
        return (self.total_successes / self.total_requests) * 100

    @property
    def rate_limit_frequency(self) -> float:
        """% de requisições que foram rate limitadas"""
        if self.total_requests == 0:
            return 0.0
        return (self.total_rate_limits_hit / self.total_requests) * 100

    @property
    def retry_rate(self) -> float:
        """% de requisições que precisaram ser retentadas"""
        if self.total_requests == 0:
            return 0.0
        return (self.total_retries / self.total_requests) * 100

    @property
    def avg_retry_count(self) -> float:
        """Média de retries por rate limit hit"""
        if self.total_rate_limits_hit == 0:
            return 0.0
        return self.total_retries / self.total_rate_limits_hit

    def to_dict(self) -> Dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "total_requests": self.total_requests,
            "rate_limits_hit": self.total_rate_limits_hit,
            "rate_limit_frequency_pct": f"{self.rate_limit_frequency:.1f}%",
            "success_rate_pct": f"{self.success_rate:.1f}%",
            "avg_wait_time_ms": f"{self.avg_wait_time * 1000:.0f}",
            "max_wait_time_ms": f"{self.max_wait_time * 1000:.0f}",
            "total_backoff_time_ms": f"{self.total_backoff_time * 1000:.0f}",
            "retry_rate_pct": f"{self.retry_rate:.1f}%",
            "max_retry_after_s": f"{self.max_retry_after:.1f}",
        }
