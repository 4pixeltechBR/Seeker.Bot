#!/usr/bin/env python3
"""Test Rate Limiting System"""

import asyncio
import time
from src.core.rate_limiting import RateLimitManager, QueuePriority


async def test_rate_limiting():
    """Teste o sistema de rate limiting"""
    print("\n" + "=" * 60)
    print("RATE LIMITING SYSTEM — TEST")
    print("=" * 60 + "\n")

    manager = RateLimitManager()

    print("[1] Teste de Rate Limiting Básico\n")

    # Simular 5 requisições rápidas (deve fazer 3 esperar)
    provider, model = "nvidia", "nemotron"
    rpm_limit = 3  # 3 requisições por minuto
    limiter = manager.get_limiter(provider, model, rpm=rpm_limit)

    start = time.time()
    for i in range(5):
        result = await limiter.acquire()
        # Handle both AsyncRateLimiter (float) and SmartQueuedLimiter (tuple)
        wait_time = result[0] if isinstance(result, tuple) else result
        elapsed = time.time() - start
        status = "WAIT" if wait_time > 0 else "OK  "
        print(f"  Request {i+1}: [{status}] waited {wait_time:.2f}s (total: {elapsed:.2f}s)")

    print("\n[2] Teste de Retry com Exponential Backoff\n")

    # Simular retries
    for attempt in range(1, 4):
        delay = await manager.wait_with_backoff(
            "groq", "mixtral", attempt=attempt, retry_after=None
        )
        print(f"  Attempt {attempt}: backoff {delay:.2f}s")

    print("\n[3] Teste de Retry-After Header\n")

    # Simular 429 com Retry-After
    print("  Marking as rate limited (Retry-After: 5s)...")
    manager.mark_rate_limited("gemini", "gemini-2.0-flash", retry_after=5.0)

    delay = await manager.wait_with_backoff(
        "gemini", "gemini-2.0-flash", attempt=1
    )
    print(f"  Wait time with Retry-After: {delay:.2f}s")

    print("\n[4] Estatísticas Agregadas\n")

    stats = manager.get_all_stats()
    print(f"  Total Providers: {stats['total_providers']}")
    print(f"  Overall Rate Limits Hit: {stats['overall']['total_rate_limits_hit']}")
    print(f"  Overall Retries: {stats['overall']['total_retries']}")
    print(f"  Overall Success Rate: {stats['overall']['avg_success_rate_pct']:.1f}%\n")

    print("  Per-Provider Stats:")
    for provider_key, stats_data in stats["providers"].items():
        print(f"    {provider_key}:")
        print(f"      - Rate Limits: {stats_data['rate_limit_frequency_pct']}")
        print(f"      - Avg Wait: {stats_data['avg_wait_time_ms']}")
        print(f"      - Retry Rate: {stats_data['retry_rate_pct']}")

    print("\n[5] Relatório para Telegram\n")

    report = manager.format_rate_limit_report()
    print(report)

    print("=" * 60)
    print("TEST COMPLETED SUCCESSFULLY")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(test_rate_limiting())
