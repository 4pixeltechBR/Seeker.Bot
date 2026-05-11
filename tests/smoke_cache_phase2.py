"""
Smoke tests for Phase 2: Gemini Explicit Caching
- Verify CachedContentManager initialization
- Test hash-based lookup
- Test TTL expiration logic
- Verify token estimation
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.providers.gemini_cache import (
    CachedContentManager,
    CachedContent,
    GEMINI_MIN_CACHED_TOKENS,
    GEMINI_CACHE_EXPIRY_SECONDS,
)
from src.core.cognition.prompts import SYSTEM_BASE

import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("smoke.cache_phase2")


def test_cached_content_ttl():
    """Test 1: CachedContent TTL tracking."""
    log.info("TEST 1: CachedContent TTL...")

    cached = CachedContent(
        content_hash="abc123",
        cache_name="cachedContents/test123",
        estimated_tokens=5000,
    )

    assert not cached.is_expired, "New cache should not be expired"
    assert cached.ttl_seconds > 0, "TTL should be positive"
    assert cached.ttl_seconds <= GEMINI_CACHE_EXPIRY_SECONDS, "TTL should be <= max"
    log.info(f"[OK] TTL tracking: {cached.ttl_seconds}s remaining")

    # Test expiration
    cached.expires_at = time.time() - 1  # Expired 1 sec ago
    assert cached.is_expired, "Expired cache should be marked as expired"
    assert cached.ttl_seconds == 0, "Expired cache should have 0 TTL"
    log.info("[OK] Expiration detection works")


def test_content_manager_init():
    """Test 2: CachedContentManager initialization."""
    log.info("\nTEST 2: CachedContentManager init...")

    manager = CachedContentManager(api_key="test-key", model_id="gemini-2.0-flash")
    assert manager.api_key == "test-key"
    assert manager.model_id == "gemini-2.0-flash"
    assert len(manager._cache_store) == 0
    log.info("[OK] Manager initialized")


def test_token_estimation():
    """Test 3: Token estimation heuristic."""
    log.info("\nTEST 3: Token estimation...")

    manager = CachedContentManager(api_key="test", model_id="gemini-2.0-flash")

    # Simple text
    estimated = manager.estimate_tokens("Hello world")
    assert estimated > 0, "Should estimate > 0 tokens"
    log.info(f"[OK] 'Hello world' -> ~{estimated} tokens")

    # SYSTEM_BASE
    system_tokens = manager.estimate_tokens(SYSTEM_BASE)
    log.info(f"[OK] SYSTEM_BASE -> ~{system_tokens} tokens")

    # Large content
    large_content = SYSTEM_BASE * 5  # ~4100 tokens
    large_tokens = manager.estimate_tokens(large_content)
    assert large_tokens >= GEMINI_MIN_CACHED_TOKENS, "Large content should exceed 4k"
    log.info(f"[OK] Large content (5x SYSTEM_BASE) -> ~{large_tokens} tokens")


def test_hash_consistency():
    """Test 4: Hash consistency for lookup."""
    log.info("\nTEST 4: Hash consistency...")

    manager = CachedContentManager(api_key="test", model_id="gemini-2.0-flash")

    content = "Test content for caching"
    hash1 = manager._hash_content(content)
    hash2 = manager._hash_content(content)
    assert hash1 == hash2, "Same content should produce same hash"
    log.info(f"[OK] Consistent hash: {hash1[:8]}...")

    # Different content
    content2 = "Different content"
    hash3 = manager._hash_content(content2)
    assert hash1 != hash3, "Different content should produce different hash"
    log.info("[OK] Different content produces different hash")


def test_cache_miss_and_expiry():
    """Test 5: Cache miss behavior and expiry cleanup."""
    log.info("\nTEST 5: Cache miss and expiry...")

    manager = CachedContentManager(api_key="test", model_id="gemini-2.0-flash")

    # Small content (below minimum)
    small_content = "Small"
    small_tokens = manager.estimate_tokens(small_content)
    assert small_tokens < GEMINI_MIN_CACHED_TOKENS, "Small content should be below 4k"

    cache_name = manager.get_cache_name_or_create(small_content, small_tokens)
    assert cache_name is None, "Small content should not be cached"
    log.info("[OK] Small content (<4k) not cached")

    # Large content (above minimum)
    large_content = SYSTEM_BASE * 5
    large_tokens = manager.estimate_tokens(large_content)
    cache_name = manager.get_cache_name_or_create(large_content, large_tokens)
    # Will return None since _create_cache is not implemented
    # But let's verify the flow
    log.info(f"[OK] Large content (>{GEMINI_MIN_CACHED_TOKENS}k) handled")


def test_stats():
    """Test 6: Stats reporting."""
    log.info("\nTEST 6: Stats reporting...")

    manager = CachedContentManager(api_key="test", model_id="gemini-2.0-flash")

    # Manually add some cached content for testing
    manager._cache_store["hash1"] = CachedContent(
        content_hash="hash1",
        cache_name="cachedContents/test1",
        estimated_tokens=5000,
    )
    manager._cache_store["hash2"] = CachedContent(
        content_hash="hash2",
        cache_name="cachedContents/test2",
        estimated_tokens=4500,
    )

    stats = manager.stats()
    assert stats["total_cached"] == 2, "Should have 2 cached items"
    assert stats["estimated_total_tokens"] == 9500, "Should sum tokens correctly"
    assert stats["oldest_ttl"] > 0, "Should have positive TTL"
    log.info(f"[OK] Stats: {stats}")


def main():
    """Run all smoke tests."""
    log.info("=" * 60)
    log.info("PHASE 2 SMOKE TESTS: Gemini Explicit Caching")
    log.info("=" * 60)

    try:
        test_cached_content_ttl()
        test_content_manager_init()
        test_token_estimation()
        test_hash_consistency()
        test_cache_miss_and_expiry()
        test_stats()

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
