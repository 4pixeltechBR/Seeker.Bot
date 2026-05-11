"""
Smoke tests for Phase 3: PromptBundle Unification
- Verify PromptBundle dataclass works
- Test backward compatibility (str conversion)
- Verify stable/dynamic split logic
- Test all three builders return PromptBundle
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.cognition.prompts import (
    PromptBundle,
    build_reflex_prompt,
    build_deliberate_prompt,
    build_deep_prompt,
    SYSTEM_BASE,
)

import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("smoke.cache_phase3")


def test_prompt_bundle_dataclass():
    """Test 1: PromptBundle dataclass structure."""
    log.info("TEST 1: PromptBundle dataclass...")

    bundle = PromptBundle(
        stable_prefix="Base system message",
        dynamic_suffix="\n\nSession context"
    )

    assert bundle.stable_prefix == "Base system message"
    assert bundle.dynamic_suffix == "\n\nSession context"
    assert bundle.total_length > 0
    assert bundle.prefix_length == len("Base system message")
    log.info("[OK] PromptBundle structure valid")


def test_prompt_bundle_backward_compat():
    """Test 2: PromptBundle backward compatibility (str conversion)."""
    log.info("\nTEST 2: Backward compatibility...")

    bundle = PromptBundle(
        stable_prefix="System",
        dynamic_suffix="\n\nContext"
    )

    # Test __str__()
    as_string = str(bundle)
    assert as_string == "System\n\nContext"
    log.info(f"[OK] str(bundle) = {as_string[:30]}...")

    # Test to_string()
    to_str = bundle.to_string()
    assert to_str == as_string
    log.info("[OK] to_string() works")

    # Test that it works where str was expected
    assert isinstance(as_string, str)
    log.info("[OK] Can be used where str expected")


def test_reflex_builder_returns_bundle():
    """Test 3: build_reflex_prompt returns PromptBundle."""
    log.info("\nTEST 3: build_reflex_prompt returns PromptBundle...")

    bundle = build_reflex_prompt(
        memory_context="Test memory",
        session_context="Test session"
    )

    assert isinstance(bundle, PromptBundle), "Should return PromptBundle"
    assert len(bundle.stable_prefix) > 0, "Should have stable_prefix"
    assert bundle.dynamic_suffix, "Should have dynamic_suffix with context"
    log.info(f"[OK] Reflex bundle: {bundle.prefix_length} stable + {len(bundle.dynamic_suffix)} dynamic")


def test_deliberate_builder_returns_bundle():
    """Test 4: build_deliberate_prompt returns PromptBundle."""
    log.info("\nTEST 4: build_deliberate_prompt returns PromptBundle...")

    bundle = build_deliberate_prompt(
        module_context="Vision module",
        memory_context="User memory",
        session_context="Chat session",
        web_context="Search results"
    )

    assert isinstance(bundle, PromptBundle), "Should return PromptBundle"
    assert SYSTEM_BASE in bundle.stable_prefix, "Should have SYSTEM_BASE"
    assert "Vision module" in bundle.stable_prefix, "Module context in stable"
    assert "Chat session" in bundle.dynamic_suffix, "Session in dynamic"
    log.info(f"[OK] Deliberate bundle: {bundle.prefix_length} stable + {len(bundle.dynamic_suffix)} dynamic")


def test_deep_builder_returns_bundle():
    """Test 5: build_deep_prompt returns PromptBundle."""
    log.info("\nTEST 5: build_deep_prompt returns PromptBundle...")

    bundle = build_deep_prompt(
        evidence_context="Model consensus",
        web_context="Web results",
        module_context="Arbitrage module",
        memory_context="Long-term memory",
        session_context="Current session",
        god_mode=False
    )

    assert isinstance(bundle, PromptBundle), "Should return PromptBundle"
    assert SYSTEM_BASE in bundle.stable_prefix, "Should have SYSTEM_BASE"
    assert "Arbitrage module" in bundle.stable_prefix, "Module in stable"
    assert "Current session" in bundle.dynamic_suffix, "Session in dynamic"
    assert "Long-term memory" in bundle.dynamic_suffix, "Memory in dynamic"
    log.info(f"[OK] Deep bundle: {bundle.prefix_length} stable + {len(bundle.dynamic_suffix)} dynamic")


def test_stable_vs_dynamic_split():
    """Test 6: Stable vs dynamic content split logic."""
    log.info("\nTEST 6: Stable vs dynamic split...")

    # Build with various contexts
    bundle = build_deliberate_prompt(
        module_context="Important module",  # Should be stable
        memory_context="User facts",        # Should be dynamic
        session_context="This chat",        # Should be dynamic
        web_context="Search results"        # Should be dynamic
    )

    full_text = str(bundle)

    # Verify stable content is in stable_prefix
    assert "Important module" in bundle.stable_prefix, "Module should be stable"
    assert SYSTEM_BASE in bundle.stable_prefix, "SYSTEM_BASE should be stable"

    # Verify dynamic content is in dynamic_suffix
    assert "User facts" in bundle.dynamic_suffix, "Memory should be dynamic"
    assert "This chat" in bundle.dynamic_suffix, "Session should be dynamic"

    # Verify full text contains everything
    assert "Important module" in full_text
    assert "User facts" in full_text
    assert "This chat" in full_text

    log.info("[OK] Stable/dynamic split correct")


def main():
    """Run all smoke tests."""
    log.info("=" * 60)
    log.info("PHASE 3 SMOKE TESTS: PromptBundle Unification")
    log.info("=" * 60)

    try:
        test_prompt_bundle_dataclass()
        test_prompt_bundle_backward_compat()
        test_reflex_builder_returns_bundle()
        test_deliberate_builder_returns_bundle()
        test_deep_builder_returns_bundle()
        test_stable_vs_dynamic_split()

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
