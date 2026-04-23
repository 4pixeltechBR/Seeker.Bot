"""Graceful Degradation Strategy"""

import logging
from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass

log = logging.getLogger("seeker.degradation")


class DegradationLevel(Enum):
    """Degradation levels"""
    NORMAL = 0        # Full functionality
    REDUCED = 1       # Some features disabled
    MINIMAL = 2       # Basic functionality only
    OFFLINE = 3       # No service


@dataclass
class DegradationConfig:
    """Configuration for degradation behavior"""
    min_confidence: float = 0.5  # Min confidence to use data
    skip_expensive_ops: bool = False  # Skip expensive operations
    use_cache_only: bool = False  # Only use cached data
    disable_features: List[str] = None  # Features to disable


class GracefulDegradation:
    """
    Manage graceful degradation of service features
    when providers become unhealthy.
    """

    def __init__(self):
        self._provider_degradation: Dict[str, DegradationLevel] = {}
        self._feature_status: Dict[str, bool] = {}
        self._fallback_chains: Dict[str, List[str]] = {}

    def set_provider_status(self, provider: str, level: DegradationLevel):
        """Update degradation level for provider"""
        old_level = self._provider_degradation.get(provider, DegradationLevel.NORMAL)
        self._provider_degradation[provider] = level

        if level != old_level:
            log.warning(
                f"[degradation] {provider}: {old_level.name} → {level.name}"
            )

    def get_provider_status(self, provider: str) -> DegradationLevel:
        """Get degradation level for provider"""
        return self._provider_degradation.get(provider, DegradationLevel.NORMAL)

    def register_fallback_chain(self, name: str, providers: List[str]):
        """
        Register fallback chain for feature.

        Example:
            register_fallback_chain(
                "search",
                ["tavily", "brave", "duckduckgo"]
            )
        """
        self._fallback_chains[name] = providers
        log.info(f"[degradation] Registered fallback chain: {name} → {providers}")

    def get_available_provider(self, chain_name: str) -> Optional[str]:
        """
        Get first available (non-degraded) provider from chain.

        Returns:
            First healthy provider, or None if all degraded
        """
        providers = self._fallback_chains.get(chain_name, [])

        for provider in providers:
            level = self.get_provider_status(provider)
            if level == DegradationLevel.NORMAL:
                return provider

        # If all degraded, return the least degraded
        best_provider = min(
            providers,
            key=lambda p: self.get_provider_status(p).value,
            default=None
        )

        if best_provider:
            level = self.get_provider_status(best_provider)
            log.warning(
                f"[degradation] All providers in '{chain_name}' degraded. "
                f"Using {best_provider} at {level.name}"
            )

        return best_provider

    def enable_feature(self, feature_name: str):
        """Enable feature"""
        self._feature_status[feature_name] = True
        log.info(f"[degradation] Feature enabled: {feature_name}")

    def disable_feature(self, feature_name: str):
        """Disable feature for graceful degradation"""
        self._feature_status[feature_name] = False
        log.warning(f"[degradation] Feature disabled: {feature_name}")

    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if feature is enabled"""
        return self._feature_status.get(feature_name, True)

    def get_degradation_config(
        self, provider: str
    ) -> DegradationConfig:
        """Get configuration based on provider degradation level"""
        level = self.get_provider_status(provider)

        if level == DegradationLevel.NORMAL:
            return DegradationConfig()

        elif level == DegradationLevel.REDUCED:
            return DegradationConfig(
                min_confidence=0.7,  # Higher threshold
                skip_expensive_ops=True,
            )

        elif level == DegradationLevel.MINIMAL:
            return DegradationConfig(
                min_confidence=0.8,
                skip_expensive_ops=True,
                use_cache_only=True,
            )

        else:  # OFFLINE
            return DegradationConfig(
                use_cache_only=True,
                disable_features=["realtime_search", "embeddings"],
            )

    def get_status_report(self) -> str:
        """Get degradation status report"""
        report = "<b>🔻 DEGRADATION STATUS</b>\n"

        healthy_count = sum(
            1 for level in self._provider_degradation.values()
            if level == DegradationLevel.NORMAL
        )
        total_count = len(self._provider_degradation)

        report += f"Healthy Providers: {healthy_count}/{total_count}\n\n"

        # Per-provider status
        if self._provider_degradation:
            report += "<b>Provider Status</b>\n"
            for provider, level in sorted(self._provider_degradation.items()):
                emoji = {
                    DegradationLevel.NORMAL: "🟢",
                    DegradationLevel.REDUCED: "🟡",
                    DegradationLevel.MINIMAL: "🟠",
                    DegradationLevel.OFFLINE: "🔴",
                }[level]

                report += f"{emoji} {provider}: {level.name}\n"

        # Feature status
        if any(not status for status in self._feature_status.values()):
            report += "\n<b>Disabled Features</b>\n"
            for feature, enabled in self._feature_status.items():
                if not enabled:
                    report += f"❌ {feature}\n"

        return report
