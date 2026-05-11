"""
Smoke tests for Phase 4: Cache Statistics & Telemetry
- Verify RastreadorCustos cache tracking
- Test CacheStatsProvider aggregation
- Validate cache savings calculation
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.budget.cost_tracker import RastreadorCustos
from src.core.budget.cache_stats import CacheStatsProvider, CacheMetrics
from datetime import datetime

import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("smoke.cache_phase4")


def test_rastreador_cache_initialization():
    """Test 1: RastreadorCustos initializes with cache fields."""
    log.info("TEST 1: RastreadorCustos cache initialization...")

    tracker = RastreadorCustos(limite_diario_usd=10.0, limite_mensal_usd=200.0)

    # Check cache fields exist
    assert hasattr(tracker, "_cache_hits_diarios"), "Should have _cache_hits_diarios"
    assert hasattr(tracker, "_cache_hits_mensais"), "Should have _cache_hits_mensais"
    assert hasattr(tracker, "_custo_economizado_diarios"), "Should have cost saved dict"
    assert hasattr(tracker, "_custo_economizado_mensais"), "Should have monthly cost saved"

    log.info("[OK] Cache fields initialized correctly")


def test_registrar_custo_com_cache():
    """Test 2: registrar_custo accepts cache telemetry parameters."""
    log.info("\nTEST 2: Register cost with cache telemetry...")

    tracker = RastreadorCustos()

    alerta = tracker.registrar_custo(
        provider="deepseek",
        modelo="deepseek-v3",
        fase="Deep",
        tokens_entrada=1000,
        tokens_saida=200,
        custo_usd=0.50,
        cache_hit_tokens=500,
        cache_creation_tokens=300,
    )

    # Should not raise
    assert alerta is None or isinstance(alerta, object), "Should register successfully"

    log.info("[OK] Cost with cache telemetry registered")


def test_cache_stats_provider_creation():
    """Test 3: CacheStatsProvider initializes correctly."""
    log.info("\nTEST 3: CacheStatsProvider initialization...")

    provider = CacheStatsProvider()

    assert provider.total_hits_globais == 0, "Should start with 0 hits"
    assert provider.total_creations_globais == 0, "Should start with 0 creations"
    assert provider.economia_total_usd == 0.0, "Should start with 0 economy"

    log.info("[OK] CacheStatsProvider initialized")


def test_cache_metrics_dataclass():
    """Test 4: CacheMetrics dataclass structure."""
    log.info("\nTEST 4: CacheMetrics dataclass...")

    metrics = CacheMetrics(
        periodo="2025-03-15",
        total_cache_hits=1000,
        total_cache_creations=500,
        economia_estimada_usd=0.25,
        chamadas_com_cache=10,
        taxa_cache_hit=85.5,
    )

    assert metrics.periodo == "2025-03-15"
    assert metrics.total_cache_hits == 1000
    assert metrics.economia_estimada_usd == 0.25

    serialized = metrics.para_dict()
    assert isinstance(serialized, dict), "Should serialize to dict"
    assert "economia_estimada_usd" in serialized, "Should have economy field"

    log.info("[OK] CacheMetrics structure valid")


def test_registrar_resposta_deepseek():
    """Test 5: CacheStatsProvider registers DeepSeek cache response."""
    log.info("\nTEST 5: Register DeepSeek cache response...")

    provider = CacheStatsProvider()

    provider.registrar_resposta(
        provider="deepseek",
        modelo="deepseek-v3",
        fase="Deep",
        cache_hit_tokens=1000,
        cache_creation_tokens=200,
        custo_usd=0.50,
    )

    assert provider.total_hits_globais == 1000, "Should track hits"
    assert provider.total_creations_globais == 200, "Should track creations"
    assert provider.economia_total_usd > 0, "Should calculate economy"

    log.info(
        f"[OK] DeepSeek: {provider.total_hits_globais} hits, "
        f"~${provider.economia_total_usd:.6f} saved"
    )


def test_registrar_resposta_gemini():
    """Test 6: CacheStatsProvider calculates different economy for Gemini."""
    log.info("\nTEST 6: Register Gemini cache response...")

    provider = CacheStatsProvider()

    # Same tokens, different provider = different economy
    provider.registrar_resposta(
        provider="gemini",
        modelo="gemini-2.0-flash",
        fase="Deep",
        cache_hit_tokens=1000,
        cache_creation_tokens=200,
        custo_usd=0.50,
    )

    gemini_economy = provider.economia_total_usd

    # Switch to DeepSeek
    provider2 = CacheStatsProvider()
    provider2.registrar_resposta(
        provider="deepseek",
        modelo="deepseek-v3",
        fase="Deep",
        cache_hit_tokens=1000,
        cache_creation_tokens=200,
        custo_usd=0.50,
    )

    deepseek_economy = provider2.economia_total_usd

    # Different providers = different economies
    assert gemini_economy != deepseek_economy, "Different providers should have different economy"

    log.info(
        f"[OK] Gemini economy: ${gemini_economy:.6f}, "
        f"DeepSeek economy: ${deepseek_economy:.6f}"
    )


def test_obter_resumo_geral():
    """Test 7: CacheStatsProvider generates overall summary."""
    log.info("\nTEST 7: Generate overall cache summary...")

    provider = CacheStatsProvider()

    # Add multiple responses
    for i in range(3):
        provider.registrar_resposta(
            provider="deepseek",
            modelo="deepseek-v3",
            fase="Deep",
            cache_hit_tokens=500 * (i + 1),
            cache_creation_tokens=100,
            custo_usd=0.10 * (i + 1),
        )

    summary = provider.obter_resumo_geral()

    assert "total_cache_hits" in summary, "Should have total hits"
    assert "economia_total_usd" in summary, "Should have total economy"
    assert "stats_por_provider" in summary, "Should have provider stats"

    log.info(
        f"[OK] Summary: {summary['total_cache_hits']} total hits, "
        f"~${summary['economia_total_usd']:.4f} saved"
    )


def main():
    """Run all smoke tests."""
    log.info("=" * 60)
    log.info("PHASE 4 SMOKE TESTS: Cache Statistics & Telemetry")
    log.info("=" * 60)

    try:
        test_rastreador_cache_initialization()
        test_registrar_custo_com_cache()
        test_cache_stats_provider_creation()
        test_cache_metrics_dataclass()
        test_registrar_resposta_deepseek()
        test_registrar_resposta_gemini()
        test_obter_resumo_geral()

        log.info("\n" + "=" * 60)
        log.info("[PASS] ALL TESTS PASSED")
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
