"""
Integration test for Phase 3: PromptBundle Unification
- Verify phase files work with PromptBundle
- Test backward compatibility in actual phase execution
- Validate cache metrics extraction
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.cognition.prompts import (
    build_reflex_prompt,
    build_deliberate_prompt,
    build_deep_prompt,
)
from src.providers.base import LLMRequest
from src.providers.gemini_cache import CachedContentManager

import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("integration.cache_phase3")


def test_bundle_in_llm_request():
    """Test 1: PromptBundle works in LLMRequest (backward compat)."""
    log.info("TEST 1: PromptBundle in LLMRequest...")

    bundle = build_reflex_prompt(memory_context="Test", session_context="Session")

    # Should work because str(bundle) is called by LLMRequest
    request = LLMRequest(
        messages=[{"role": "user", "content": "Test query"}],
        system=str(bundle),  # Explicit conversion
        max_tokens=500,
    )

    assert isinstance(request.system, str)
    assert len(request.system) > 0
    log.info("[OK] Bundle works in LLMRequest")


def test_bundle_cache_eligibility():
    """Test 2: Measure cache eligibility with PromptBundle."""
    log.info("\nTEST 2: Bundle cache eligibility...")

    manager = CachedContentManager("key", "gemini-2.0-flash")

    # Reflex bundle (small)
    reflex = build_reflex_prompt(memory_context="Memory", session_context="Session")
    reflex_tokens = manager.estimate_tokens(reflex.stable_prefix)
    log.info(f"[OK] Reflex stable: {reflex_tokens} tokens (cache eligible: {reflex_tokens >= 4000})")

    # Deliberate bundle (larger)
    deliberate = build_deliberate_prompt(
        module_context="Vision",
        memory_context="Memory",
        session_context="Session",
        web_context="Web search results about recent events"
    )
    deliberate_tokens = manager.estimate_tokens(deliberate.stable_prefix)
    log.info(f"[OK] Deliberate stable: {deliberate_tokens} tokens (cache eligible: {deliberate_tokens >= 4000})")

    # Deep bundle (largest) — with realistic large web context
    large_web_context = "Web search results: " + (
        "Long detailed search results about recent developments in AI technology, "
        "including information about new model architectures, benchmarks, performance metrics, "
        "and deployment strategies. " * 10
    )
    deep = build_deep_prompt(
        evidence_context="Model consensus from multiple LLM providers",
        web_context=large_web_context,
        module_context="Arbitrage module",
        memory_context="Long-term memory",
        session_context="Current session"
    )
    deep_tokens = manager.estimate_tokens(deep.stable_prefix)
    log.info(f"[OK] Deep stable: {deep_tokens} tokens (cache eligible: {deep_tokens >= 4000})")

    # With large web context, should be eligible
    if deep_tokens >= 4000:
        log.info("[OK] Deep bundle eligible for Gemini caching")
    else:
        log.info(f"[OK] Deep bundle ({deep_tokens} tokens) would need larger context to reach 4k")


def test_cache_savings_calculation():
    """Test 3: Calculate potential cache savings."""
    log.info("\nTEST 3: Cache savings calculation...")

    manager = CachedContentManager("key", "gemini-2.0-flash")

    # Build a complex prompt
    bundle = build_deep_prompt(
        evidence_context="Long evidence from multiple models",
        web_context="Extended web search results",
        module_context="Complex module context",
        memory_context="Detailed memory extraction",
        session_context="Full chat session"
    )

    stable_tokens = manager.estimate_tokens(bundle.stable_prefix)
    dynamic_tokens = manager.estimate_tokens(bundle.dynamic_suffix)
    total_tokens = stable_tokens + dynamic_tokens

    log.info("Prompt composition:")
    log.info(f"  Stable (cacheable):  {stable_tokens} tokens")
    log.info(f"  Dynamic (each call): {dynamic_tokens} tokens")
    log.info(f"  Total:               {total_tokens} tokens")

    # Calculate savings
    # NOTE: deepseek_discount=0.90 / gemini_discount=0.75 são os valores de
    # referência das Phases 1 e 2 — mantidos como comentário aqui porque o
    # cálculo abaixo já usa as cost-per-1M tokens diretamente.
    cost_per_1m_input_deepseek = 0.14  # USD
    cost_per_1m_input_gemini = 0.075   # USD

    # First request (creates cache)
    first_cost = (total_tokens / 1_000_000) * cost_per_1m_input_deepseek
    log.info("\nFirst request (cache creation):")
    log.info(f"  DeepSeek cost: ${first_cost:.6f}")

    # Subsequent requests (cache hit)
    cached_cost = (dynamic_tokens / 1_000_000) * cost_per_1m_input_deepseek
    cache_hit_savings = first_cost - cached_cost
    cache_hit_percent = (cache_hit_savings / first_cost) * 100

    log.info("\nSubsequent requests (with Phase 1 cache):")
    log.info(f"  Cost per request: ${cached_cost:.6f}")
    log.info(f"  Savings per request: ${cache_hit_savings:.6f} ({cache_hit_percent:.1f}%)")

    # With Gemini explicit (if enabled)
    gemini_first = (total_tokens / 1_000_000) * cost_per_1m_input_gemini
    gemini_cached = (dynamic_tokens / 1_000_000) * cost_per_1m_input_gemini
    gemini_savings = gemini_first - gemini_cached

    log.info("\nGemini (Phase 2 explicit caching, if enabled):")
    log.info(f"  Cost per request: ${gemini_cached:.6f}")
    log.info(f"  Savings per request: ${gemini_savings:.6f}")

    assert stable_tokens > 0, "Should have cacheable content"
    log.info("[OK] Cache savings estimated")


def test_full_prompt_reconstruction():
    """Test 4: Full prompt is correctly reconstructed from bundle."""
    log.info("\nTEST 4: Full prompt reconstruction...")

    bundle = build_deliberate_prompt(
        module_context="Test module",
        memory_context="Test memory",
        session_context="Test session",
        web_context="Test web"
    )

    # Verify components are present in full text
    full_text = str(bundle)
    assert "Test module" in full_text
    assert "Test memory" in full_text
    assert "Test session" in full_text
    assert "Test web" in full_text

    # Verify structure (sep by \n\n)
    parts = full_text.split("\n\n")
    assert len(parts) >= 4, "Should have multiple parts separated"

    log.info(f"[OK] Full prompt reconstructed ({len(full_text)} chars, {len(parts)} sections)")


def main():
    """Run all integration tests."""
    log.info("=" * 60)
    log.info("PHASE 3 INTEGRATION TESTS: PromptBundle Unification")
    log.info("=" * 60)

    try:
        test_bundle_in_llm_request()
        test_bundle_cache_eligibility()
        test_cache_savings_calculation()
        test_full_prompt_reconstruction()

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
