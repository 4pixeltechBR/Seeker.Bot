"""Rate Limit Manager - Orchestrate and Track Rate Limiting Across Providers"""

import asyncio
import logging
import random
import time
from typing import Optional, Dict
from collections import defaultdict

from .limiter import SmartQueuedLimiter, QueuePriority
from .metrics import RateLimitMetrics, RateLimitStats

log = logging.getLogger("seeker.rate_limiting")


class RateLimitManager:
    """
    Gerencia rate limiting para múltiplos providers/modelos.
    Implementa exponential backoff com jitter e Retry-After support.
    """

    def __init__(self):
        self._limiters: Dict[str, SmartQueuedLimiter] = {}
        self._stats: Dict[str, RateLimitStats] = defaultdict(
            lambda: RateLimitStats(provider="unknown", model="")
        )
        self._metrics_history = defaultdict(list)  # Por provider:model

        # Configuração de retry
        self.max_retries = 3
        self.base_delay = 0.5  # segundos
        self.max_delay = 30.0  # segundos
        self.jitter_range = (0.8, 1.2)  # 20% de jitter

    def get_limiter(self, provider: str, model: str, rpm: int = 60) -> SmartQueuedLimiter:
        """Obtém ou cria limiter para provider/modelo"""
        key = f"{provider}:{model}"
        if key not in self._limiters:
            self._limiters[key] = SmartQueuedLimiter(rpm=rpm, max_queue_size=100)
            log.debug(f"[rate-limit-mgr] Criado limiter para {key} ({rpm} RPM)")
        return self._limiters[key]

    async def wait_with_backoff(
        self,
        provider: str,
        model: str,
        attempt: int = 1,
        retry_after: Optional[float] = None,
    ) -> float:
        """
        Aguarda com exponential backoff + jitter.

        Args:
            provider: Nome do provider
            model: ID do modelo
            attempt: Número da tentativa (1-indexed)
            retry_after: Valor do header Retry-After (segundos)

        Returns:
            Tempo total de espera em segundos
        """
        if attempt > self.max_retries:
            log.error(f"[rate-limit-mgr] Max retries ({self.max_retries}) exceeded")
            raise Exception(f"Max retries exceeded after {self.max_retries} attempts")

        limiter = self.get_limiter(provider, model)

        # Se temos Retry-After, respeita
        if retry_after and retry_after > 0:
            limiter.set_retry_after_header(int(retry_after))

        # Calcula backoff com jitter
        if attempt > 1:
            # Exponential: 0.5 * 2^(attempt-1) * jitter
            delay = self.base_delay * (2 ** (attempt - 2))
            delay = min(delay, self.max_delay)
            jitter = random.uniform(self.jitter_range[0], self.jitter_range[1])
            delay *= jitter

            log.info(
                f"[rate-limit-mgr] Retry {attempt}/{self.max_retries} "
                f"para {provider}:{model} (aguardando {delay:.2f}s com jitter)"
            )
            await asyncio.sleep(delay)
        else:
            delay = 0.0

        # Adquire slot do rate limiter
        wait_time, retry_after_wait = await limiter.acquire(
            priority=QueuePriority.CRITICAL if attempt > 1 else QueuePriority.NORMAL
        )

        total_delay = delay + wait_time + retry_after_wait

        # Registra métrica
        self._record_metric(provider, model, attempt, total_delay, retry_after or 0)

        return total_delay

    def _record_metric(
        self, provider: str, model: str, retry_count: int, delay: float, retry_after: float
    ):
        """Registra métrica de uma tentativa"""
        key = f"{provider}:{model}"
        stats = self._stats[key]
        stats.provider = provider
        stats.model = model

        # Update counters
        stats.total_requests += 1
        if retry_count > 0:
            stats.total_rate_limits_hit += 1
            stats.total_retries += retry_count
            stats.total_backoff_time += delay

        stats.total_wait_time += delay
        if stats.total_rate_limits_hit > 0:
            stats.avg_wait_time = stats.total_wait_time / stats.total_requests
        stats.max_wait_time = max(stats.max_wait_time, delay)
        stats.max_retry_after = max(stats.max_retry_after, retry_after)

        # Métrica detalhada
        metric = RateLimitMetrics(
            provider=provider,
            model=model,
            retry_count=retry_count,
            backoff_delays=[delay] if delay > 0 else [],
            retry_after=retry_after,
            success=True,
        )
        self._metrics_history[key].append(metric)

        # Limpar histórico antigo (manter últimas 100)
        if len(self._metrics_history[key]) > 100:
            self._metrics_history[key].pop(0)

    def mark_success(self, provider: str, model: str):
        """Marca sucesso (limpa Retry-After)"""
        key = f"{provider}:{model}"
        stats = self._stats[key]
        stats.total_successes += 1

    def mark_failure(self, provider: str, model: str):
        """Marca falha"""
        key = f"{provider}:{model}"
        stats = self._stats[key]
        stats.total_failures += 1

    def mark_rate_limited(
        self, provider: str, model: str, retry_after: Optional[float] = None
    ):
        """Marca que foi rate limitado (429 recebido)"""
        limiter = self.get_limiter(provider, model)
        if retry_after:
            limiter.set_retry_after_header(int(retry_after))

    def get_stats(self, provider: Optional[str] = None) -> Dict:
        """Retorna estatísticas de um provider ou todos"""
        if provider:
            key = f"{provider}:*"
            keys = [k for k in self._stats.keys() if k.startswith(provider)]
        else:
            keys = list(self._stats.keys())

        result = {}
        for key in keys:
            result[key] = self._stats[key].to_dict()

        return result

    def get_limiter_status(self, provider: str, model: str) -> dict:
        """Retorna status atual do limiter"""
        limiter = self.get_limiter(provider, model)
        return {
            "provider": provider,
            "model": model,
            "queue_size": limiter.queue_size,
            "queue_usage_pct": limiter.queue_usage_pct,
            "base_metrics": limiter.get_metrics(),
            "stats": self._stats[f"{provider}:{model}"].to_dict(),
        }

    def get_all_stats(self) -> dict:
        """Retorna estatísticas de todos os providers/modelos"""
        summary = {
            "total_providers": len(self._limiters),
            "providers": {},
            "overall": {
                "total_rate_limits_hit": sum(s.total_rate_limits_hit for s in self._stats.values()),
                "total_retries": sum(s.total_retries for s in self._stats.values()),
                "total_requests": sum(s.total_requests for s in self._stats.values()),
                "avg_success_rate_pct": sum(s.success_rate for s in self._stats.values())
                / len(self._stats) if self._stats else 100.0,
            }
        }

        for key, stats in self._stats.items():
            summary["providers"][key] = stats.to_dict()

        return summary

    def format_rate_limit_report(self) -> str:
        """Formata relatório de rate limiting para Telegram"""
        all_stats = self.get_all_stats()
        overall = all_stats["overall"]
        providers = all_stats["providers"]

        report = (
            "<b>🚷 RATE LIMITING REPORT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>Overall Stats</b>\n"
            f"├ Providers: {all_stats['total_providers']}\n"
            f"├ Rate Limits Hit: {overall['total_rate_limits_hit']}\n"
            f"├ Total Retries: {overall['total_retries']}\n"
            f"├ Total Requests: {overall['total_requests']}\n"
            f"└ Avg Success Rate: {overall['avg_success_rate_pct']:.1f}%\n\n"
        )

        if providers:
            report += "<b>Per Provider</b>\n"
            for provider, stats in sorted(providers.items()):
                report += (
                    f"<b>{provider}</b>\n"
                    f"  Success Rate: {stats['success_rate_pct']}\n"
                    f"  Rate Limit Freq: {stats['rate_limit_frequency_pct']}\n"
                    f"  Avg Wait: {stats['avg_wait_time_ms']}\n"
                    f"  Retry Rate: {stats['retry_rate_pct']}\n\n"
                )

        return report
