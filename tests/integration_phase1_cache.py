"""
Integration test for Phase 1: Verify phase execution still works correctly
after prompt caching refactoring.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.cognition.prompts import (
    build_reflex_prompt,
    build_deliberate_prompt,
    build_deep_prompt,
    get_date_context,
)
from src.providers.base import LLMRequest, LLMResponse


def test_prompt_composition():
    """Verify that prompts compose correctly with date_context in user message."""
    print("[TEST] Prompt composition...")

    # Get stable system prompts (Phase 3 returns PromptBundle, convert to string)
    system_reflex = str(build_reflex_prompt(
        memory_context="Test memory",
        session_context="Test session"
    ))
    system_deliberate = str(build_deliberate_prompt(
        memory_context="Test memory",
        session_context="Test session"
    ))
    system_deep = str(build_deep_prompt(
        evidence_context="Test evidence",
        memory_context="Test memory",
        session_context="Test session"
    ))

    # Get dynamic date context
    date_ctx = get_date_context()

    # Verify system prompts are stable (no dynamic content)
    assert "DATA E HORA ATUAL" not in system_reflex, "Reflex should be stable"
    assert "DATA E HORA ATUAL" not in system_deliberate, "Deliberate should be stable"
    assert "DATA E HORA ATUAL" not in system_deep, "Deep should be stable"
    print("  [OK] System prompts are stable (no date_context)")

    # Verify date context is extracted
    assert "[DATA E HORA ATUAL:" in date_ctx, "Date context should be extracted"
    print("  [OK] Date context properly extracted")

    # Simulate user message composition (as phases do)
    user_input = "What is the weather?"
    user_message = date_ctx + user_input
    assert "[DATA E HORA ATUAL:" in user_message, "User message should have date context"
    print("  [OK] User message correctly composed with date_context")


def test_llm_request_structure():
    """Verify LLMRequest can be constructed correctly."""
    print("\n[TEST] LLMRequest structure...")

    system = build_deliberate_prompt()
    date_ctx = get_date_context()
    user_input = "Test query"
    user_message = date_ctx + user_input

    request = LLMRequest(
        messages=[{"role": "user", "content": user_message}],
        system=system,
        max_tokens=4000,
        temperature=0.15,
    )

    assert len(request.messages) == 1, "Should have 1 message"
    assert request.messages[0]["role"] == "user", "Should be user message"
    assert "[DATA E HORA ATUAL:" in request.messages[0]["content"], "Should contain date context"
    assert request.system == system, "System should match"
    print("  [OK] LLMRequest structures correctly")


def test_cache_telemetry_fields():
    """Verify cache telemetry fields work correctly."""
    print("\n[TEST] Cache telemetry fields...")

    # Test DeepSeek response with cache tokens
    response_deepseek = LLMResponse(
        text="Response text",
        model="deepseek-chat",
        provider="deepseek",
        input_tokens=1000,
        output_tokens=200,
        cache_hit_tokens=450,
        cache_creation_tokens=50,
    )

    assert response_deepseek.cache_hit_tokens == 450
    assert response_deepseek.cache_creation_tokens == 50
    assert response_deepseek.total_cached_tokens == 500
    print("  [OK] Cache telemetry fields functional for DeepSeek")

    # Test Gemini response with cache tokens
    response_gemini = LLMResponse(
        text="Response text",
        model="gemini-2.0-flash",
        provider="gemini",
        input_tokens=1000,
        output_tokens=200,
        cache_hit_tokens=800,  # Gemini only has cache_hit
    )

    assert response_gemini.cache_hit_tokens == 800
    assert response_gemini.cache_creation_tokens == 0
    assert response_gemini.total_cached_tokens == 800
    print("  [OK] Cache telemetry fields functional for Gemini")


def test_backward_compat():
    """Verify old code (no cache fields) still works."""
    print("\n[TEST] Backward compatibility...")

    # Old-style response creation (without cache fields)
    response = LLMResponse(
        text="Response",
        model="groq-llama",
        provider="groq",
        input_tokens=100,
        output_tokens=50,
    )

    # Should still have cache fields (defaulting to 0)
    assert response.cache_hit_tokens == 0
    assert response.cache_creation_tokens == 0
    assert response.total_cached_tokens == 0
    print("  [OK] Backward compatibility maintained (cache fields default to 0)")


def main():
    """Run all integration tests."""
    print("=" * 60)
    print("PHASE 1 INTEGRATION TESTS")
    print("=" * 60)

    try:
        test_prompt_composition()
        test_llm_request_structure()
        test_cache_telemetry_fields()
        test_backward_compat()

        print("\n" + "=" * 60)
        print("[PASS] ALL INTEGRATION TESTS PASSED")
        print("=" * 60)
        return 0

    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n[ERROR] UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
