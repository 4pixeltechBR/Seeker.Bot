"""Error Recovery Manager - Orchestrate Recovery Strategies"""

import logging
from enum import Enum
from typing import Optional, Dict, Callable, Any
from datetime import datetime

from .circuit_breaker import CircuitBreaker, CircuitBreakerState
from .telemetry import ErrorTelemetry, ErrorCategory, ErrorSeverity, ErrorAlert
from .degradation import GracefulDegradation, DegradationLevel

log = logging.getLogger("seeker.error_recovery")


class RecoveryStrategy(Enum):
    """Recovery strategies"""
    RETRY = "retry"                    # Retry with backoff
    FALLBACK = "fallback"              # Try alternative provider
    DEGRADE = "degrade"                # Reduce functionality
    CIRCUIT_BREAK = "circuit_break"    # Stop calling provider


class ErrorRecoveryManager:
    """
    Orchestrate error recovery across circuit breaker,
    telemetry, and graceful degradation.
    """

    def __init__(self):
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._telemetry = ErrorTelemetry(alert_threshold=5, alert_window_minutes=5)
        self._degradation = GracefulDegradation()

        # Recovery strategy mapping
        self._recovery_strategies: Dict[int, RecoveryStrategy] = {
            429: RecoveryStrategy.RETRY,         # Too Many Requests
            500: RecoveryStrategy.RETRY,         # Server error
            503: RecoveryStrategy.RETRY,         # Service Unavailable
            401: RecoveryStrategy.FALLBACK,      # Unauthorized
            404: RecoveryStrategy.FALLBACK,      # Not Found
            408: RecoveryStrategy.RETRY,         # Request Timeout
        }

        log.info("[recovery] ErrorRecoveryManager initialized")

    def get_circuit_breaker(
        self, provider: str, failure_threshold: int = 5, recovery_timeout: float = 60.0
    ) -> CircuitBreaker:
        """Get or create circuit breaker for provider"""
        if provider not in self._circuit_breakers:
            self._circuit_breakers[provider] = CircuitBreaker(
                name=f"{provider}-breaker",
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
        return self._circuit_breakers[provider]

    def handle_error(
        self,
        provider: str,
        model: str,
        error_code: Optional[int],
        error_message: str,
        error_category: ErrorCategory = ErrorCategory.UNKNOWN,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        traceback: str = "",
    ) -> RecoveryStrategy:
        """
        Handle error and determine recovery strategy.

        Returns:
            Recommended recovery strategy
        """
        # Record telemetry
        alert = self._telemetry.record_error(
            category=error_category,
            provider=provider,
            model=model,
            error_message=error_message,
            severity=severity,
            error_code=error_code,
            traceback=traceback,
        )

        # Handle alert if triggered
        if alert:
            self._handle_alert(alert)

        # Record in circuit breaker
        cb = self.get_circuit_breaker(provider)
        cb._on_failure(error_message)

        # Determine recovery strategy
        strategy = self._recovery_strategies.get(error_code, RecoveryStrategy.FALLBACK)

        # Escalate to circuit break if too many failures
        if cb.state == CircuitBreakerState.OPEN:
            strategy = RecoveryStrategy.CIRCUIT_BREAK
            self._degradation.set_provider_status(provider, DegradationLevel.OFFLINE)

        elif cb.state == CircuitBreakerState.HALF_OPEN:
            strategy = RecoveryStrategy.RETRY  # Limited retries
            self._degradation.set_provider_status(provider, DegradationLevel.REDUCED)

        log.warning(
            f"[recovery] {provider}/{model}: {error_code} → {strategy.value} "
            f"(circuit: {cb.state.value})"
        )

        return strategy

    def mark_success(self, provider: str):
        """Mark successful recovery"""
        cb = self.get_circuit_breaker(provider)
        cb._on_success()

        if cb.state == CircuitBreakerState.CLOSED:
            self._degradation.set_provider_status(provider, DegradationLevel.NORMAL)

    def _handle_alert(self, alert: ErrorAlert):
        """Handle triggered alert"""
        log.error(
            f"[recovery] ALERT: {alert.provider} - {alert.message} "
            f"(Severity: {alert.severity.name})"
        )

        # Escalate to minimal degradation on alert
        if alert.severity == ErrorSeverity.CRITICAL:
            self._degradation.set_provider_status(provider=alert.provider, level=DegradationLevel.OFFLINE)
        elif alert.severity == ErrorSeverity.HIGH:
            self._degradation.set_provider_status(provider=alert.provider, level=DegradationLevel.MINIMAL)

    def get_recovery_status(self) -> dict:
        """Get comprehensive recovery status"""
        circuit_status = {
            name: cb.get_metrics() for name, cb in self._circuit_breakers.items()
        }

        error_stats = self._telemetry.get_all_stats()
        degradation = self._degradation.get_status_report()

        return {
            "circuit_breakers": circuit_status,
            "error_stats": error_stats,
            "degradation_status": degradation,
        }

    def format_recovery_report(self) -> str:
        """Format recovery status for Telegram"""
        report = "<b>🔧 ERROR RECOVERY STATUS</b>\n"
        report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        # Circuit breaker status
        report += "<b>Circuit Breakers</b>\n"
        if self._circuit_breakers:
            for name, cb in self._circuit_breakers.items():
                state_emoji = {
                    CircuitBreakerState.CLOSED: "🟢",
                    CircuitBreakerState.OPEN: "🔴",
                    CircuitBreakerState.HALF_OPEN: "🟡",
                }[cb.state]

                report += (
                    f"{state_emoji} {cb.name}: {cb.state.value}\n"
                    f"   Failures: {cb._failure_count}/{cb.failure_threshold}\n"
                )
        else:
            report += "  (No circuit breakers yet)\n"

        # Error telemetry
        report += "\n" + self._telemetry.format_alert_report()

        # Degradation status
        report += "\n" + self._degradation.get_status_report()

        return report

    def reset_provider(self, provider: str):
        """Manually reset provider recovery state"""
        if provider in self._circuit_breakers:
            self._circuit_breakers[provider].reset()

        self._degradation.set_provider_status(provider, DegradationLevel.NORMAL)
        log.info(f"[recovery] Provider reset: {provider}")
