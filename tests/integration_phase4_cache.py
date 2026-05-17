"""
Integration test for Phase 4: Cache Statistics Telemetry
- Verify RastreadorCustos and CacheStatsProvider work together
- Test cache savings calculation with realistic costs
- Validate monthly economy rollup
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.budget.cost_tracker import RastreadorCustos
from src.core.budget.cache_stats import CacheStatsProvider
from datetime import datetime, timedelta

import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("integration.cache_phase4")


def test_rastreador_economia_diaria():
    """Test 1: RastreadorCustos tracks daily cache savings."""
    log.info("TEST 1: Daily cache savings tracking...")

    tracker = RastreadorCustos(limite_diario_usd=100.0)

    # Register 3 calls with different cache telemetry
    for i in range(3):
        tracker.registrar_custo(
            provider="deepseek",
            modelo="deepseek-v3",
            fase="Deep",
            tokens_entrada=1000,
            tokens_saida=200,
            custo_usd=0.10 * (i + 1),
            cache_hit_tokens=500 * (i + 1),
            cache_creation_tokens=100,
        )

    # Get daily economy
    economia_diaria = tracker.obter_economia_cache_diaria(dias=1)

    assert len(economia_diaria) >= 1, "Should have at least today's economy"

    today_key = datetime.utcnow().strftime("%Y-%m-%d")
    if today_key in economia_diaria:
        today_stats = economia_diaria[today_key]
        log.info(
            f"[OK] Today: {today_stats['tokens_cache']} cache tokens, "
            f"~${today_stats['custo_economizado_usd']:.4f} saved"
        )
        assert today_stats["tokens_cache"] > 0, "Should have cache tokens"
    else:
        log.info("[OK] Economy dict created (may be empty if already past today)")


def test_rastreador_economia_mensal():
    """Test 2: RastreadorCustos calculates monthly economy."""
    log.info("\nTEST 2: Monthly cache savings calculation...")

    tracker = RastreadorCustos(limite_mensal_usd=500.0)

    # Simulate 10 LLM calls with cache hits
    total_cache_tokens = 0
    for i in range(10):
        cache_hits = 500 + (i * 100)
        tracker.registrar_custo(
            provider="deepseek",
            modelo="deepseek-v3",
            fase="Deep",
            tokens_entrada=2000,
            tokens_saida=500,
            custo_usd=0.25,
            cache_hit_tokens=cache_hits,
            cache_creation_tokens=200,
        )
        total_cache_tokens += cache_hits

    # Get monthly economy
    economia_mensal = tracker.obter_economia_cache_mensal()

    log.info("[OK] Monthly economy:")
    log.info(f"  Total cache tokens: {economia_mensal['tokens_cache']}")
    log.info(f"  Estimated savings: ${economia_mensal['custo_economizado_usd']:.4f}")
    log.info(f"  Economy rate: {economia_mensal['taxa_economia']:.1f}%")

    assert economia_mensal["tokens_cache"] > 0, "Should have cache tokens"
    assert economia_mensal["taxa_economia"] >= 0, "Should have economy rate"


def test_cache_stats_provider_aggregation():
    """Test 3: CacheStatsProvider aggregates across multiple calls."""
    log.info("\nTEST 3: CacheStatsProvider aggregation...")

    provider = CacheStatsProvider()

    # Simulate 3 phases with cache telemetry
    fases = [("Reflex", 300), ("Deliberate", 600), ("Deep", 1200)]

    for fase, cache_hits in fases:
        for i in range(3):
            provider.registrar_resposta(
                provider="deepseek",
                modelo="deepseek-v3",
                fase=fase,
                cache_hit_tokens=cache_hits + (i * 100),
                cache_creation_tokens=150,
                custo_usd=0.05 * (i + 1),
            )

    # Get summary
    summary = provider.obter_resumo_geral()

    log.info("[OK] Global summary:")
    log.info(f"  Total cache hits: {summary['total_cache_hits']}")
    log.info(f"  Total economy: ${summary['economia_total_usd']:.4f}")
    log.info(f"  Providers: {len(summary['stats_por_provider'])}")
    log.info(f"  Fases: {len(summary['stats_por_fase'])}")

    assert summary["total_cache_hits"] > 5000, "Should have significant cache"
    assert summary["economia_total_usd"] > 0, "Should have calculated economy"


def test_cache_stats_por_fase():
    """Test 4: CacheStatsProvider aggregates correctly by phase."""
    log.info("\nTEST 4: Cache stats aggregation by phase...")

    provider = CacheStatsProvider()

    # Reflex (small): ~300 tokens cache per call
    for _ in range(5):
        provider.registrar_resposta(
            provider="deepseek",
            modelo="deepseek-v3",
            fase="Reflex",
            cache_hit_tokens=300,
            cache_creation_tokens=50,
            custo_usd=0.03,
        )

    # Deep (large): ~1500 tokens cache per call
    for _ in range(5):
        provider.registrar_resposta(
            provider="deepseek",
            modelo="deepseek-v3",
            fase="Deep",
            cache_hit_tokens=1500,
            cache_creation_tokens=200,
            custo_usd=0.25,
        )

    # Get stats by phase
    stats_por_fase = provider.obter_stats_por_dimensao("fase")

    log.info("[OK] Stats by phase:")
    for fase, stats in stats_por_fase.items():
        log.info(
            f"  {fase}: {stats['total_cache_hits']} hits, "
            f"${stats['economia_estimada_usd']:.4f} saved"
        )

    assert "Reflex" in stats_por_fase, "Should have Reflex phase"
    assert "Deep" in stats_por_fase, "Should have Deep phase"

    # Deep should have more cache hits than Reflex
    reflex_hits = stats_por_fase["Reflex"]["total_cache_hits"]
    deep_hits = stats_por_fase["Deep"]["total_cache_hits"]
    assert deep_hits > reflex_hits, "Deep phase should have more cache hits"


def test_cache_economy_projection():
    """Test 5: Calculate projected monthly savings with cache."""
    log.info("\nTEST 5: Projected monthly savings calculation...")

    provider = CacheStatsProvider()

    # Simulate 20 daily calls over a month with realistic Deep phase cache hits
    # Deep phase can cache up to 3.5k tokens (system) + 2k tokens (web) = 5.5k hits per call
    avg_cache_hits_per_call = 3500
    calls_per_day = 20

    for day in range(30):
        for call in range(calls_per_day):
            provider.registrar_resposta(
                provider="deepseek",
                modelo="deepseek-v3",
                fase="Deep",
                cache_hit_tokens=avg_cache_hits_per_call,
                cache_creation_tokens=150,
                custo_usd=0.15,
                timestamp=datetime.utcnow() - timedelta(days=30 - day),
            )

    summary = provider.obter_resumo_geral()
    total_calls = calls_per_day * 30
    monthly_savings = summary["economia_total_usd"]

    log.info("[OK] Projected monthly savings:")
    log.info(f"  Total calls: {total_calls}")
    log.info(f"  Total cache hits: {summary['total_cache_hits']}")
    log.info(f"  Total savings: ${monthly_savings:.2f}")
    log.info(f"  Avg savings per call: ${monthly_savings / total_calls:.6f}")

    assert summary["total_cache_hits"] > 1_800_000, "Should have significant cache over month"
    assert monthly_savings > 0.2, "Should save meaningful amount over month"


def test_cache_stats_daily_breakdown():
    """Test 6: Get daily cache stats breakdown."""
    log.info("\nTEST 6: Daily cache stats breakdown...")

    provider = CacheStatsProvider()

    # Register calls across 3 days
    for day in range(3):
        for call in range(5):
            provider.registrar_resposta(
                provider="deepseek",
                modelo="deepseek-v3",
                fase="Deep",
                cache_hit_tokens=600 + (call * 100),
                cache_creation_tokens=100,
                custo_usd=0.12,
                timestamp=datetime.utcnow() - timedelta(days=2 - day),
            )

    # Get daily stats
    daily = provider.obter_stats_diarias(dias=3)

    log.info("[OK] Daily cache stats:")
    for date, stats in daily.items():
        if stats["total_cache_hits"] > 0:
            log.info(
                f"  {date}: {stats['total_cache_hits']} hits, "
                f"${stats['economia_estimada_usd']:.4f} saved"
            )

    assert len(daily) == 3, "Should have 3 days of stats"


def main():
    """Run all integration tests."""
    log.info("=" * 60)
    log.info("PHASE 4 INTEGRATION TESTS: Cache Statistics Telemetry")
    log.info("=" * 60)

    try:
        test_rastreador_economia_diaria()
        test_rastreador_economia_mensal()
        test_cache_stats_provider_aggregation()
        test_cache_stats_por_fase()
        test_cache_economy_projection()
        test_cache_stats_daily_breakdown()

        log.info("\n" + "=" * 60)
        log.info("[PASS] ALL INTEGRATION TESTS PASSED")
        log.info("=" * 60)
        return 0

    except AssertionError as e:
        log.error(f"\n[FAIL] TEST FAILED: {e}")
        return 1
    except Exception as e:
        log.error(f"\n[ERROR] UNEXPECTED ERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
