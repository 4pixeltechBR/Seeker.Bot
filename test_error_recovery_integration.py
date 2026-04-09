#!/usr/bin/env python3
"""
Integration test for Error Recovery with Pipeline
Tests error handling, circuit breaker escalation, and degradation triggers
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

async def test_integration():
    """Integration test: Pipeline + ErrorRecoveryManager"""
    print("\n" + "="*70)
    print("ERROR RECOVERY INTEGRATION TEST (Sprint 9.3)")
    print("="*70)

    # Import after path setup
    from src.core.pipeline import SeekerPipeline
    from src.core.error_recovery import (
        ErrorRecoveryManager, ErrorCategory, ErrorSeverity,
        RecoveryStrategy, CircuitBreakerState, DegradationLevel
    )
    from config.env import load_env_config

    # Load environment
    env = load_env_config()
    api_keys = {
        "openai": env.get("OPENAI_API_KEY", ""),
        "gemini": env.get("GEMINI_API_KEY", ""),
        "groq": env.get("GROQ_API_KEY", ""),
        "deepseek": env.get("DEEPSEEK_API_KEY", ""),
        "anthropic": env.get("ANTHROPIC_API_KEY", ""),
    }

    print("\n[TEST 1] ErrorRecoveryManager initialization in Pipeline")
    try:
        pipeline = SeekerPipeline(api_keys, db_path=":memory:")
        assert hasattr(pipeline, 'error_recovery'), "Pipeline should have error_recovery"
        assert isinstance(pipeline.error_recovery, ErrorRecoveryManager)
        print("[PASS] ErrorRecoveryManager initialized in Pipeline")
        print(f"  - Circuit breaker count: {len(pipeline.error_recovery._circuit_breakers)}")
        print(f"  - Alert threshold: {pipeline.error_recovery._telemetry.alert_threshold}")
    except Exception as e:
        print(f"[FAIL] Pipeline init failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n[TEST 2] Simulate provider errors and circuit breaker escalation")
    try:
        recovery = pipeline.error_recovery

        # Simulate 5 consecutive rate limit errors (429)
        for i in range(5):
            strategy = recovery.handle_error(
                provider="test-provider",
                model="test-model",
                error_code=429,
                error_message=f"Rate limited attempt {i+1}",
                error_category=ErrorCategory.RATE_LIMIT,
                severity=ErrorSeverity.HIGH
            )
            print(f"  - Error {i+1}: {error_category} -> strategy={strategy.value}")

        # Check circuit breaker state
        cb = recovery.get_circuit_breaker("test-provider")
        print(f"  - Circuit breaker state: {cb.state.value}")
        print(f"  - Failure count: {cb._failure_count}/{cb.failure_threshold}")

        assert cb.state == CircuitBreakerState.OPEN, "Circuit should be OPEN after 5 failures"
        print("[PASS] Circuit breaker escalated to OPEN after threshold")
    except Exception as e:
        print(f"[FAIL] Circuit breaker test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n[TEST 3] Graceful degradation on provider errors")
    try:
        recovery = pipeline.error_recovery
        degradation = recovery._degradation

        # Register fallback chain
        degradation.register_fallback_chain(
            "embedding",
            ["gemini", "cohere", "openai"]
        )
        print("  - Registered fallback chain: embedding -> [gemini, cohere, openai]")

        # Simulate provider failures
        strategy = recovery.handle_error(
            provider="gemini",
            model="embedding-001",
            error_code=503,
            error_message="Service unavailable",
            error_category=ErrorCategory.SERVER_ERROR,
            severity=ErrorSeverity.HIGH
        )

        # Check degradation state
        gemini_status = degradation.get_provider_status("gemini")
        print(f"  - Gemini degradation level: {gemini_status.name}")

        # Get available provider
        available = degradation.get_available_provider("embedding")
        print(f"  - Available provider: {available}")
        assert available in ["cohere", "openai"], f"Should fallback to cohere or openai, got {available}"

        print("[PASS] Graceful degradation working correctly")
    except Exception as e:
        print(f"[FAIL] Degradation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n[TEST 4] Error telemetry and alert thresholds")
    try:
        recovery = pipeline.error_recovery
        telemetry = recovery._telemetry

        # Record errors until alert triggers
        alerts = []
        for i in range(6):
            alert = recovery.handle_error(
                provider="alert-test",
                model="test",
                error_code=500,
                error_message=f"Server error {i+1}",
                error_category=ErrorCategory.SERVER_ERROR,
                severity=ErrorSeverity.MEDIUM
            )
            if alert:
                alerts.append(alert)
                print(f"  - Error {i+1}: ALERT TRIGGERED - {alert.message}")
            else:
                print(f"  - Error {i+1}: No alert yet")

        assert len(alerts) > 0, "Should have triggered at least one alert"
        print(f"[PASS] Error telemetry triggered {len(alerts)} alert(s)")
    except Exception as e:
        print(f"[FAIL] Telemetry test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n[TEST 5] Recovery status formatting for Telegram")
    try:
        recovery = pipeline.error_recovery

        # Get formatted report
        report = recovery.format_recovery_report()
        assert "<b>" in report, "Report should contain HTML"
        assert "Circuit" in report, "Report should mention circuit breakers"
        assert "DEGRADATION" in report, "Report should mention degradation"

        print(f"[PASS] Recovery report formatted successfully")
        print(f"  - Report size: {len(report)} characters")

        # Show first 200 chars of report
        preview = report[:200].replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
        print(f"  - Preview: {preview}...")
    except Exception as e:
        print(f"[FAIL] Report formatting failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n[TEST 6] Recovery status across multiple providers")
    try:
        recovery = pipeline.error_recovery

        # Simulate errors on multiple providers
        providers = ["openai", "groq", "gemini", "deepseek"]
        for provider in providers:
            for _ in range(2):
                recovery.handle_error(
                    provider=provider,
                    model="test",
                    error_code=429,
                    error_message="Rate limit",
                    error_category=ErrorCategory.RATE_LIMIT,
                    severity=ErrorSeverity.MEDIUM
                )

        # Get aggregated status
        status = recovery.get_recovery_status()

        print(f"  - Providers tracked: {len(status['circuit_breakers'])}")
        print(f"  - Error stats keys: {list(status['error_stats'].keys())}")

        # Check each provider
        for provider in providers:
            if provider in status['circuit_breakers']:
                cb_status = status['circuit_breakers'][provider]
                print(f"    - {provider}: {cb_status['state']}, failures={cb_status['failure_count']}")

        print(f"[PASS] Aggregated status across {len(status['circuit_breakers'])} providers")
    except Exception as e:
        print(f"[FAIL] Multi-provider status failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "="*70)
    print("[SUCCESS] All integration tests passed!")
    print("="*70)
    return True


def main():
    """Run integration tests"""
    try:
        result = asyncio.run(test_integration())
        return 0 if result else 1
    except Exception as e:
        print(f"\n[CRITICAL] Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
