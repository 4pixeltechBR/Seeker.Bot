"""Error Recovery Module for Seeker.Bot"""

from .circuit_breaker import CircuitBreaker, CircuitBreakerState
from .recovery import ErrorRecoveryManager, RecoveryStrategy
from .telemetry import ErrorTelemetry, ErrorAlert, ErrorCategory, ErrorSeverity
from .degradation import GracefulDegradation, DegradationLevel

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerState",
    "ErrorRecoveryManager",
    "RecoveryStrategy",
    "ErrorTelemetry",
    "ErrorAlert",
    "ErrorCategory",
    "ErrorSeverity",
    "GracefulDegradation",
    "DegradationLevel",
]
