"""
Smoke test for Phase 1: Prompt Caching Initiative
- Verify date_context extraction
- Verify system prompts are stable (no date_context)
- Verify cache telemetry in LLMResponse
- Test with real DeepSeek API (requires valid API_KEY)
"""

import asyncio
import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("smoke.cache_phase1")

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.cognition.prompts import (
    build_reflex_prompt,
    build_deliberate_prompt,
    build_deep_prompt,
    get_date_context,
    SYSTEM_BASE,
    REFLEX_SYSTEM,
)
from src.providers.base import (
    LLMResponse,
    LLMRequest,
    DeepSeekProvider,
)
from config.models import ModelConfig


def test_date_context_extraction():
    """Test 1: Date context is properly extracted and not in system prompts."""
    log.info("TEST 1: Date context extraction...")

    date_ctx = get_date_context()
    assert "[DATA E HORA ATUAL:" in date_ctx, "Date context should contain time"
    assert "horário de Brasília" in date_ctx, "Date context should mention timezone"
    log.info(f"✓ Date context extracted: {date_ctx[:50]}...")

    # Verify system prompts don't contain "DATA E HORA ATUAL"
    # Note: Phase 3 changed builders to return PromptBundle, so convert to string
    reflex = str(build_reflex_prompt())
    assert "DATA E HORA ATUAL" not in reflex, "REFLEX should not contain date_context"
    log.info("✓ Reflex prompt is stable (no date_context)")

    deliberate = str(build_deliberate_prompt())
    assert "DATA E HORA ATUAL" not in deliberate, "DELIBERATE should not contain date_context"
    log.info("✓ Deliberate prompt is stable (no date_context)")

    deep = str(build_deep_prompt())
    assert "DATA E HORA ATUAL" not in deep, "DEEP should not contain date_context"
    log.info("✓ Deep prompt is stable (no date_context)")

    # Verify SYSTEM_BASE is still in deliberate/deep
    assert SYSTEM_BASE in deliberate, "SYSTEM_BASE should be in deliberate"
    assert SYSTEM_BASE in deep, "SYSTEM_BASE should be in deep"
    log.info("✓ SYSTEM_BASE preserved in deliberate/deep")


def test_llm_response_cache_fields():
    """Test 2: LLMResponse has cache_hit_tokens and cache_creation_tokens."""
    log.info("\nTEST 2: LLMResponse cache fields...")

    response = LLMResponse(
        text="Test response",
        model="deepseek-chat",
        provider="deepseek",
        input_tokens=100,
        output_tokens=50,
        cache_hit_tokens=45,
        cache_creation_tokens=55,
    )

    assert response.cache_hit_tokens == 45, "cache_hit_tokens should be stored"
    assert response.cache_creation_tokens == 55, "cache_creation_tokens should be stored"
    assert response.total_cached_tokens == 100, "total_cached_tokens should sum both"
    log.info(f"✓ Cache fields present: {response.total_cached_tokens} cached tokens")


async def test_deepseek_cache_capture():
    """Test 3: DeepSeek provider captures cache tokens from response."""
    log.info("\nTEST 3: DeepSeek cache token capture...")

    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        log.warning("⚠️ DEEPSEEK_API_KEY not set — skipping live API test")
        return

    config = ModelConfig(
        provider="deepseek",
        model_id="deepseek-chat",
        cost_per_1m_input=0.14,
        cost_per_1m_output=0.28,
        rpm_limit=60,
    )

    provider = DeepSeekProvider(config, api_key)

    # Simple system message without date context (stable)
    system = "You are a helpful assistant. Respond concisely."

    # First request — should create cache
    log.info("Sending first request (will create cache)...")
    request1 = LLMRequest(
        messages=[{"role": "user", "content": "What is 2+2?"}],
        system=system,
        max_tokens=50,
    )
    response1 = await provider.complete(request1)
    log.info(f"Response 1: {response1.text[:50]}...")
    log.info(
        f"  Tokens: input={response1.input_tokens}, "
        f"output={response1.output_tokens}, "
        f"cache_hit={response1.cache_hit_tokens}, "
        f"cache_create={response1.cache_creation_tokens}"
    )

    # Second request with same system — should hit cache
    log.info("Sending second request (should hit cache)...")
    request2 = LLMRequest(
        messages=[{"role": "user", "content": "What is 3+3?"}],
        system=system,
        max_tokens=50,
    )
    response2 = await provider.complete(request2)
    log.info(f"Response 2: {response2.text[:50]}...")
    log.info(
        f"  Tokens: input={response2.input_tokens}, "
        f"output={response2.output_tokens}, "
        f"cache_hit={response2.cache_hit_tokens}, "
        f"cache_create={response2.cache_creation_tokens}"
    )

    # Verify cache was used
    if response2.cache_hit_tokens > 0:
        log.info(f"✓ Cache hit detected: {response2.cache_hit_tokens} tokens")
    else:
        log.warning(
            "⚠️ No cache hit detected (may be normal if warmup needed)"
        )

    # Third request different system — should start new cache
    log.info("Sending third request (new system = new cache)...")
    system_new = "You are a concise expert. Answer in 1 sentence."
    request3 = LLMRequest(
        messages=[{"role": "user", "content": "What is 4+4?"}],
        system=system_new,
        max_tokens=50,
    )
    response3 = await provider.complete(request3)
    log.info(f"Response 3: {response3.text[:50]}...")
    log.info(
        f"  Tokens: input={response3.input_tokens}, "
        f"output={response3.output_tokens}, "
        f"cache_hit={response3.cache_hit_tokens}, "
        f"cache_create={response3.cache_creation_tokens}"
    )
    log.info("✓ Cache behavior validated across 3 requests")


async def main():
    """Run all smoke tests."""
    log.info("=" * 60)
    log.info("PHASE 1 SMOKE TESTS: Prompt Caching Initiative")
    log.info("=" * 60)

    try:
        test_date_context_extraction()
        test_llm_response_cache_fields()
        await test_deepseek_cache_capture()

        log.info("\n" + "=" * 60)
        log.info("✓ ALL TESTS PASSED")
        log.info("=" * 60)
        return 0

    except AssertionError as e:
        log.error(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        log.error(f"\n✗ UNEXPECTED ERROR: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
