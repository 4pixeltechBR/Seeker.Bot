"""Improved Circuit Breaker Pattern Implementation"""

import logging
import time
from enum import Enum
from typing import Optional, Callable
from datetime import datetime, timedelta
from collections import deque

log = logging.getLogger("seeker.circuit_breaker")


class CircuitBreakerState(Enum):
    """States of circuit breaker"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Blocking requests
    HALF_OPEN = "half-open"  # Testing if service recovered


class CircuitBreaker:
    """
    Advanced circuit breaker with monitoring and recovery.

    States:
    - CLOSED: Normal operation, all requests pass through
    - OPEN: Too many failures, blocking all requests
    - HALF_OPEN: Testing recovery with limited requests
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type = Exception,
        half_open_max_calls: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.half_open_max_calls = half_open_max_calls

        # State tracking
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._opened_time: Optional[float] = None

        # Metrics
        self._all_failures: deque = deque(maxlen=100)  # Last 100 failures
        self._state_changes: deque = deque(maxlen=20)  # State change history

        log.info(f"[circuit-breaker] {name} initialized (threshold={failure_threshold})")

    @property
    def state(self) -> CircuitBreakerState:
        """Current state of circuit breaker"""
        if self._state == CircuitBreakerState.OPEN:
            # Check if recovery timeout expired
            if self._opened_time:
                elapsed = time.monotonic() - self._opened_time
                if elapsed >= self.recovery_timeout:
                    self._transition_to(CircuitBreakerState.HALF_OPEN)

        return self._state

    async def call(self, func: Callable, *args, **kwargs):
        """Execute function through circuit breaker"""
        if self.state == CircuitBreakerState.OPEN:
            raise Exception(
                f"[circuit-breaker] {self.name} is OPEN. "
                f"Service unavailable. Recovery in {self._time_until_retry():.0f}s"
            )

        try:
            result = await func(*args, **kwargs) if hasattr(func, "__await__") else func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure(str(e))
            raise

    def _on_success(self):
        """Handle successful call"""
        self._failure_count = 0

        if self._state == CircuitBreakerState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.half_open_max_calls:
                log.info(
                    f"[circuit-breaker] {self.name}: "
                    f"Service recovered ({self._success_count} successes), closing circuit"
                )
                self._transition_to(CircuitBreakerState.CLOSED)
                self._success_count = 0

    def _on_failure(self, error_msg: str):
        """Handle failed call"""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        self._all_failures.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "error": error_msg[:100],
                "count": self._failure_count,
            }
        )

        log.warning(
            f"[circuit-breaker] {self.name}: Failure {self._failure_count}/{self.failure_threshold}"
        )

        if self._failure_count >= self.failure_threshold:
            self._transition_to(CircuitBreakerState.OPEN)
            self._success_count = 0

    def _transition_to(self, new_state: CircuitBreakerState):
        """Transition to new state"""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state

            if new_state == CircuitBreakerState.OPEN:
                self._opened_time = time.monotonic()

            self._state_changes.append(
                {
                    "from": old_state.value,
                    "to": new_state.value,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

            log.info(
                f"[circuit-breaker] {self.name}: "
                f"{old_state.value.upper()} → {new_state.value.upper()}"
            )

    def _time_until_retry(self) -> float:
        """Time until OPEN circuit can retry"""
        if self._opened_time:
            elapsed = time.monotonic() - self._opened_time
            remaining = self.recovery_timeout - elapsed
            return max(0, remaining)
        return 0.0

    def reset(self):
        """Manually reset circuit breaker"""
        self._transition_to(CircuitBreakerState.CLOSED)
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        log.info(f"[circuit-breaker] {self.name}: Manually reset")

    def get_metrics(self) -> dict:
        """Return circuit breaker metrics"""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure": (
                datetime.fromtimestamp(self._last_failure_time).isoformat()
                if self._last_failure_time
                else None
            ),
            "time_until_retry_s": self._time_until_retry(),
            "failure_threshold": self.failure_threshold,
            "recent_failures": list(self._all_failures)[-5:],
            "state_changes": list(self._state_changes)[-5:],
        }
