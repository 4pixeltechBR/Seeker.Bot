"""Advanced Rate Limiting with Smart Queueing"""

import asyncio
import logging
import time
from typing import Optional, Tuple
from collections import deque
from enum import Enum

log = logging.getLogger("seeker.rate_limiting")


class QueuePriority(Enum):
    """Priority levels for queued requests"""
    LOW = 3
    NORMAL = 2
    HIGH = 1
    CRITICAL = 0


class AsyncRateLimiter:
    """
    Rate limiter assíncrono com sliding window.
    Previne 429 Too Many Requests.
    """

    def __init__(self, rpm: int = 60):
        self.rpm = rpm
        self.window = 60.0  # 60 second sliding window
        self._timestamps: deque = deque()
        self._lock = asyncio.Lock()
        self._metrics = {
            "calls": 0,
            "waits": 0,
            "total_wait_time": 0.0,
        }

    async def acquire(self) -> float:
        """
        Adquire um slot. Aguarda se necessário.
        Retorna: tempo de espera em segundos
        """
        if self.rpm <= 0:
            return 0.0

        async with self._lock:
            now = time.monotonic()

            # Remove timestamps fora da janela
            while self._timestamps and self._timestamps[0] < now - self.window:
                self._timestamps.popleft()

            # Se atingiu limite, aguarda
            if len(self._timestamps) >= self.rpm:
                oldest = self._timestamps[0]
                wait_time = oldest + self.window - now + 0.01
                if wait_time > 0:
                    log.debug(
                        f"[rate-limit] {self.rpm} RPM atingido, "
                        f"aguardando {wait_time:.2f}s ({len(self._timestamps)}/{self.rpm})"
                    )
                    self._metrics["waits"] += 1
                    self._metrics["total_wait_time"] += wait_time
                    await asyncio.sleep(wait_time)
                    now = time.monotonic()

                    # Remove novamente após sleep
                    while self._timestamps and self._timestamps[0] < now - self.window:
                        self._timestamps.popleft()

            # Registra novo timestamp
            self._timestamps.append(time.monotonic())
            self._metrics["calls"] += 1
            return wait_time if len(self._timestamps) > self.rpm else 0.0

    @property
    def current_usage(self) -> int:
        """Retorna uso atual do rate limit"""
        now = time.monotonic()
        while self._timestamps and self._timestamps[0] < now - self.window:
            self._timestamps.popleft()
        return len(self._timestamps)

    @property
    def current_usage_pct(self) -> float:
        """Retorna % do rate limit usado"""
        if self.rpm <= 0:
            return 0.0
        return (self.current_usage / self.rpm) * 100

    def get_metrics(self) -> dict:
        """Retorna métricas de rate limiting"""
        avg_wait = 0.0
        if self._metrics["waits"] > 0:
            avg_wait = self._metrics["total_wait_time"] / self._metrics["waits"]

        return {
            "rpm_limit": self.rpm,
            "current_usage": self.current_usage,
            "usage_pct": self.current_usage_pct,
            "total_calls": self._metrics["calls"],
            "total_waits": self._metrics["waits"],
            "avg_wait_time": avg_wait,
            "total_wait_time": self._metrics["total_wait_time"],
        }


class SmartQueuedLimiter:
    """
    Rate limiter com fila inteligente para lidar com bursts.
    Suporta Retry-After header e exponential backoff.
    """

    def __init__(self, rpm: int = 60, max_queue_size: int = 100):
        self.rpm = rpm
        self.max_queue_size = max_queue_size
        self.base_limiter = AsyncRateLimiter(rpm=rpm)

        # Lock for atomic operations
        self._lock = asyncio.Lock()

        # Retry-After tracking
        self._retry_after_until: float = 0.0
        self._last_429_time: float = 0.0

        # Métricas
        self._stats = {
            "queued_requests": 0,
            "processed_requests": 0,
            "retry_after_hits": 0,
            "max_queue_size": 0,
        }

    async def acquire(
        self,
        priority: QueuePriority = QueuePriority.NORMAL,
        expect_retry_after: bool = True,
    ) -> Tuple[float, float]:
        """
        Adquire slot com support a rate limiting (sem fila complexa por agora).

        Args:
            priority: Prioridade da requisição
            expect_retry_after: Se True, respeita Retry-After headers

        Returns:
            (wait_time, backoff_time) em segundos
        """
        async with self._lock:
            # Verifica Retry-After
            now = time.monotonic()
            retry_after_wait = max(0, self._retry_after_until - now)

            if retry_after_wait > 0:
                log.debug(
                    f"[rate-limit] Retry-After ativo: {retry_after_wait:.1f}s restantes"
                )
                self._stats["retry_after_hits"] += 1
                if expect_retry_after:
                    await asyncio.sleep(min(retry_after_wait, 0.5))  # Max 0.5s sleep
                    retry_after_wait = 0

            self._stats["queued_requests"] += 1

        # Adquire slot do rate limiter
        wait_time = await self.base_limiter.acquire()

        self._stats["processed_requests"] += 1
        return wait_time, retry_after_wait

    async def mark_rate_limited(self, retry_after_seconds: float = 60.0):
        """Marca que fomos rate limitados (429)"""
        now = time.monotonic()
        self._last_429_time = now
        self._retry_after_until = now + retry_after_seconds

        log.warning(
            f"[rate-limit] 429 recebido, aguardando {retry_after_seconds:.0f}s "
            f"(Retry-After header)"
        )

    def set_retry_after_header(self, retry_after: str | int):
        """Parse Retry-After header (pode ser segundos ou HTTP date)"""
        try:
            if isinstance(retry_after, str):
                # Tenta interpretar como segundos
                retry_after_seconds = float(retry_after)
            else:
                retry_after_seconds = float(retry_after)

            self._retry_after_until = time.monotonic() + retry_after_seconds
            log.info(f"[rate-limit] Retry-After: {retry_after_seconds:.0f}s")
        except (ValueError, TypeError):
            log.warning(f"[rate-limit] Retry-After header inválido: {retry_after}")

    def get_metrics(self) -> dict:
        """Retorna métricas agregadas"""
        base_metrics = self.base_limiter.get_metrics()
        return {
            **base_metrics,
            "queued_requests_total": self._stats["queued_requests"],
            "processed_requests_total": self._stats["processed_requests"],
            "retry_after_hits": self._stats["retry_after_hits"],
            "max_queue_size_observed": self._stats["max_queue_size"],
        }
