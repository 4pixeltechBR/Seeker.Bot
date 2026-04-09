"""Error Telemetry and Alerting"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Dict
from collections import defaultdict, deque

log = logging.getLogger("seeker.error_telemetry")


class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = 1          # Recoverable, no impact
    MEDIUM = 2       # Degraded service
    HIGH = 3         # Service down
    CRITICAL = 4     # System failure


class ErrorCategory(Enum):
    """Error categories"""
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    NOT_FOUND = "not_found"
    SERVER_ERROR = "server_error"
    NETWORK = "network"
    UNKNOWN = "unknown"


@dataclass
class ErrorEvent:
    """Single error event"""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    category: ErrorCategory = ErrorCategory.UNKNOWN
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    provider: str = ""
    model: str = ""
    error_message: str = ""
    error_code: Optional[int] = None
    traceback: str = ""
    context: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "category": self.category.value,
            "severity": self.severity.name,
            "provider": self.provider,
            "model": self.model,
            "message": self.error_message[:100],
            "code": self.error_code,
        }


@dataclass
class ErrorAlert:
    """Alert triggered by error threshold"""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    alert_type: str = ""  # "threshold_exceeded", "circuit_open", etc
    provider: str = ""
    message: str = ""
    severity: ErrorSeverity = ErrorSeverity.HIGH
    count: int = 0
    threshold: int = 0

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "type": self.alert_type,
            "provider": self.provider,
            "message": self.message,
            "severity": self.severity.name,
            "count": self.count,
            "threshold": self.threshold,
        }


class ErrorTelemetry:
    """Track and aggregate error statistics"""

    def __init__(self, alert_threshold: int = 5, alert_window_minutes: int = 5):
        self.alert_threshold = alert_threshold
        self.alert_window_minutes = alert_window_minutes

        # Error tracking
        self._events: deque = deque(maxlen=500)  # Last 500 errors
        self._alerts: deque = deque(maxlen=100)  # Last 100 alerts

        # Per-provider tracking
        self._provider_errors: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self._provider_counts: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

    def record_error(
        self,
        category: ErrorCategory,
        provider: str,
        model: str,
        error_message: str,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        error_code: Optional[int] = None,
        traceback: str = "",
        context: Optional[Dict] = None,
    ) -> Optional[ErrorAlert]:
        """
        Record an error event and check for alerts

        Returns:
            Alert if threshold exceeded, None otherwise
        """
        event = ErrorEvent(
            category=category,
            severity=severity,
            provider=provider,
            model=model,
            error_message=error_message,
            error_code=error_code,
            traceback=traceback,
            context=context or {},
        )

        self._events.append(event)
        self._provider_errors[provider].append(event)
        self._provider_counts[provider][category.value] += 1

        log.warning(
            f"[telemetry] {category.value.upper()} on {provider}/{model}: {error_message[:80]}"
        )

        # Check for alerts
        return self._check_thresholds(provider)

    def _check_thresholds(self, provider: str) -> Optional[ErrorAlert]:
        """Check if error threshold exceeded for provider"""
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=self.alert_window_minutes)

        # Count recent errors
        recent_count = sum(
            1
            for event in self._provider_errors[provider]
            if event.timestamp > cutoff
        )

        if recent_count >= self.alert_threshold:
            alert = ErrorAlert(
                alert_type="threshold_exceeded",
                provider=provider,
                message=f"{recent_count} errors in last {self.alert_window_minutes}m",
                severity=ErrorSeverity.HIGH,
                count=recent_count,
                threshold=self.alert_threshold,
            )
            self._alerts.append(alert)

            log.error(
                f"[telemetry] ALERT: {provider} exceeded error threshold "
                f"({recent_count}/{self.alert_threshold})"
            )

            return alert

        return None

    def get_provider_stats(self, provider: str) -> Dict:
        """Get error statistics for provider"""
        errors = self._provider_errors.get(provider, [])
        counts = self._provider_counts.get(provider, {})

        total_errors = len(errors)
        critical_count = sum(1 for e in errors if e.severity == ErrorSeverity.CRITICAL)
        high_count = sum(1 for e in errors if e.severity == ErrorSeverity.HIGH)

        return {
            "provider": provider,
            "total_errors": total_errors,
            "critical_errors": critical_count,
            "high_errors": high_count,
            "error_breakdown": dict(counts),
            "recent_errors": [e.to_dict() for e in list(errors)[-5:]],
        }

    def get_all_stats(self) -> Dict:
        """Get aggregated error statistics"""
        total_errors = len(self._events)
        critical_count = sum(1 for e in self._events if e.severity == ErrorSeverity.CRITICAL)

        provider_stats = {}
        for provider in self._provider_errors.keys():
            provider_stats[provider] = self.get_provider_stats(provider)

        return {
            "total_events": total_errors,
            "critical_events": critical_count,
            "total_alerts": len(self._alerts),
            "providers": provider_stats,
            "recent_alerts": [a.to_dict() for a in list(self._alerts)[-5:]],
        }

    def format_alert_report(self) -> str:
        """Format error telemetry for Telegram"""
        stats = self.get_all_stats()

        report = (
            "<b>🚨 ERROR TELEMETRY</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>Overall Stats</b>\n"
            f"├ Total Events: {stats['total_events']}\n"
            f"├ Critical: {stats['critical_events']}\n"
            f"└ Alerts: {stats['total_alerts']}\n\n"
        )

        if stats["providers"]:
            report += "<b>Per Provider</b>\n"
            for provider, pstats in stats["providers"].items():
                report += (
                    f"<b>{provider}</b>\n"
                    f"  Errors: {pstats['total_errors']} "
                    f"(🔴 {pstats['critical_errors']} critical)\n"
                )

        if stats["recent_alerts"]:
            report += "\n<b>Recent Alerts</b>\n"
            for alert in stats["recent_alerts"]:
                report += f"  🚀 {alert['provider']}: {alert['message']}\n"

        return report
