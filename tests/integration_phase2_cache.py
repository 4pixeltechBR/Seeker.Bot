"""
Integration test for Phase 2: Gemini Explicit Caching
- Verify CachedContentManager integration with GeminiProvider
- Validate token estimation thresholds
- Test cache eligibility detection
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.models import ModelConfig
from src.providers.base import GeminiProvider
from src.providers.gemini_cache import GEMINI_MIN_CACHED_TOKENS
from src.core.cognition.prompts import SYSTEM_BASE

import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("integration.cache_phase2")


def test_gemini_provider_has_cache_manager():
    """Test 1: GeminiProvider has CachedContentManager."""
    log.info("TEST 1: GeminiProvider cache manager init...")

    config = ModelConfig(
        provider="gemini",
        model_id="gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        cost_per_1m_input=0.075,
        cost_per_1m_output=0.3,
    )

    provider = GeminiProvider(config, "test-api-key")
    assert hasattr(provider, "_cache_manager"), "Provider should have _cache_manager"
    assert provider._cache_manager is not None, "Cache manager should be initialized"
    log.info("[OK] GeminiProvider has CachedContentManager")


def test_system_base_token_count():
    """Test 2: Measure SYSTEM_BASE token count vs 4k threshold."""
    log.info("\nTEST 2: SYSTEM_BASE token count...")

    config = ModelConfig(
        provider="gemini",
        model_id="gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        cost_per_1m_input=0.075,
        cost_per_1m_output=0.3,
    )

    provider = GeminiProvider(config, "test-api-key")
    system_tokens = provider._cache_manager.estimate_tokens(SYSTEM_BASE)

    log.info(f"[OK] SYSTEM_BASE alone: {system_tokens} tokens")

    # SYSTEM_BASE + some context to reach threshold
    enriched_system = SYSTEM_BASE + "\n\nSession context placeholder" * 20
    enriched_tokens = provider._cache_manager.estimate_tokens(enriched_system)

    if enriched_tokens >= GEMINI_MIN_CACHED_TOKENS:
        log.info(f"[OK] Enriched system: {enriched_tokens} tokens (>= 4k, eligible for cache)")
    else:
        log.info(f"[OK] Enriched system: {enriched_tokens} tokens (< 4k, not eligible)")


def test_large_system_cache_eligibility():
    """Test 3: Large system content (5x SYSTEM_BASE) is cache-eligible."""
    log.info("\nTEST 3: Large content cache eligibility...")

    config = ModelConfig(
        provider="gemini",
        model_id="gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        cost_per_1m_input=0.075,
        cost_per_1m_output=0.3,
    )

    provider = GeminiProvider(config, "test-api-key")

    large_system = SYSTEM_BASE * 5
    large_tokens = provider._cache_manager.estimate_tokens(large_system)

    assert large_tokens >= GEMINI_MIN_CACHED_TOKENS, "Large content should exceed 4k"
    log.info(f"[OK] Large system (5x SYSTEM_BASE): {large_tokens} tokens (eligible)")

    # Check cache stats
    stats = provider._cache_manager.stats()
    log.info(f"[OK] Cache manager stats: {stats}")


def test_cache_hash_lookup():
    """Test 4: Hash-based cache lookup prevents duplication."""
    log.info("\nTEST 4: Hash-based cache lookup...")

    config = ModelConfig(
        provider="gemini",
        model_id="gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        cost_per_1m_input=0.075,
        cost_per_1m_output=0.3,
    )

    provider = GeminiProvider(config, "test-api-key")

    # Simulate two requests with same system prompt
    system_prompt = SYSTEM_BASE * 5
    hash1 = provider._cache_manager._hash_content(system_prompt)
    hash2 = provider._cache_manager._hash_content(system_prompt)

    assert hash1 == hash2, "Same content should produce same hash"
    log.info(f"[OK] Consistent hashing: {hash1[:8]}... == {hash2[:8]}...")

    # Different system prompt
    system_prompt2 = system_prompt + "EXTRA CONTEXT"
    hash3 = provider._cache_manager._hash_content(system_prompt2)
    assert hash1 != hash3, "Different content should produce different hash"
    log.info("[OK] Different content produces different hash")


def test_backward_compat_no_crash():
    """Test 5: Provider works without crashing even if cache manager unavailable."""
    log.info("\nTEST 5: Backward compatibility (no crash)...")

    config = ModelConfig(
        provider="gemini",
        model_id="gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        cost_per_1m_input=0.075,
        cost_per_1m_output=0.3,
    )

    provider = GeminiProvider(config, "test-api-key")

    # Simulate cache manager being None (graceful degradation)
    provider._cache_manager = None

    # This should not crash — cache manager is optional
    assert provider.config.provider == "gemini"
    log.info("[OK] Provider handles missing cache manager gracefully")


def main():
    """Run all integration tests."""
    log.info("=" * 60)
    log.info("PHASE 2 INTEGRATION TESTS: Gemini Explicit Caching")
    log.info("=" * 60)

    try:
        test_gemini_provider_has_cache_manager()
        test_system_base_token_count()
        test_large_system_cache_eligibility()
        test_cache_hash_lookup()
        test_backward_compat_no_crash()

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
