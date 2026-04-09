#!/usr/bin/env python3
"""
Validation tests for Error Recovery module (Sprint 9.3)
Tests: Imports, CircuitBreaker, ErrorTelemetry, GracefulDegradation, ErrorRecoveryManager
"""

import sys
import asyncio
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

def test_1_imports():
    """Test 1: Verify all imports work"""
    print("\n=== Test 1: Module Imports ===")
    try:
        from src.core.error_recovery import (
            CircuitBreaker, CircuitBreakerState,
            ErrorRecoveryManager, RecoveryStrategy,
            ErrorTelemetry, ErrorAlert, ErrorCategory, ErrorSeverity,
            GracefulDegradation, DegradationLevel
        )
        print("[PASS] All imports successful")
        print(f"  - CircuitBreaker: {CircuitBreaker.__name__}")
        print(f"  - ErrorRecoveryManager: {ErrorRecoveryManager.__name__}")
        print(f"  - ErrorTelemetry: {ErrorTelemetry.__name__}")
        print(f"  - GracefulDegradation: {GracefulDegradation.__name__}")
        return True
    except Exception as e:
        print(f"[FAIL] Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_2_circuit_breaker():
    """Test 2: CircuitBreaker state machine"""
    print("\n=== Test 2: CircuitBreaker State Machine ===")
    try:
        from src.core.error_recovery import CircuitBreaker, CircuitBreakerState

        cb = CircuitBreaker(name="test-breaker", failure_threshold=3, recovery_timeout=2.0)
        print(f"[PASS] Created CircuitBreaker: {cb.name}")
        print(f"  - Initial state: {cb.state.value}")
        print(f"  - Failure threshold: {cb.failure_threshold}")
        print(f"  - Recovery timeout: {cb.recovery_timeout}s")

        # Simulate failures
        for i in range(3):
            cb._on_failure(f"Test error {i+1}")
            print(f"  - Failure {i+1}: state = {cb.state.value}")

        assert cb.state == CircuitBreakerState.OPEN, "Should be OPEN after 3 failures"
        print(f"[PASS] Circuit opened after {cb.failure_threshold} failures")

        # Get metrics
        metrics = cb.get_metrics()
        print(f"[PASS] Metrics retrieved: {len(metrics)} keys")
        print(f"  - Recent failures: {len(metrics['recent_failures'])} tracked")

        return True
    except Exception as e:
        print(f"[FAIL] CircuitBreaker test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_3_error_telemetry():
    """Test 3: ErrorTelemetry threshold detection"""
    print("\n=== Test 3: ErrorTelemetry Threshold ===")
    try:
        from src.core.error_recovery import (
            ErrorTelemetry, ErrorCategory, ErrorSeverity
        )

        telemetry = ErrorTelemetry(alert_threshold=3, alert_window_minutes=5)
        print(f"[PASS] Created ErrorTelemetry: threshold={telemetry.alert_threshold}")

        # Record errors until alert triggered
        alert = None
        for i in range(4):
            alert = telemetry.record_error(
                category=ErrorCategory.SERVER_ERROR,
                provider="test-provider",
                model="test-model",
                error_message=f"Test error {i+1}",
                severity=ErrorSeverity.HIGH,
                error_code=500
            )
            print(f"  - Error {i+1} recorded, alert triggered: {alert is not None}")

        assert alert is not None, "Alert should have triggered"
        print(f"[PASS] Alert triggered: {alert.message}")

        # Get stats
        stats = telemetry.get_all_stats()
        print(f"[PASS] Stats retrieved: {stats['total_events']} total events")
        print(f"  - Critical events: {stats['critical_events']}")
        print(f"  - Total alerts: {stats['total_alerts']}")

        return True
    except Exception as e:
        print(f"[FAIL] ErrorTelemetry test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_4_graceful_degradation():
    """Test 4: GracefulDegradation fallback chain"""
    print("\n=== Test 4: Graceful Degradation Fallback ===")
    try:
        from src.core.error_recovery import GracefulDegradation, DegradationLevel

        degradation = GracefulDegradation()
        print(f"[PASS] Created GracefulDegradation")

        # Register fallback chain
        degradation.register_fallback_chain(
            "llm",
            ["provider_a", "provider_b", "provider_c"]
        )
        print(f"[PASS] Registered fallback chain: llm -> [provider_a, provider_b, provider_c]")

        # All healthy - should return first
        provider = degradation.get_available_provider("llm")
        assert provider == "provider_a", f"Expected provider_a, got {provider}"
        print(f"  - All healthy -> {provider}")

        # Degrade first provider
        degradation.set_provider_status("provider_a", DegradationLevel.OFFLINE)
        provider = degradation.get_available_provider("llm")
        assert provider == "provider_b", f"Expected provider_b, got {provider}"
        print(f"  - provider_a offline -> {provider}")

        # Degrade second provider
        degradation.set_provider_status("provider_b", DegradationLevel.MINIMAL)
        provider = degradation.get_available_provider("llm")
        assert provider == "provider_c", f"Expected provider_c, got {provider}"
        print(f"  - provider_b minimal -> {provider}")

        # All degraded - should return least degraded
        degradation.set_provider_status("provider_c", DegradationLevel.REDUCED)
        provider = degradation.get_available_provider("llm")
        print(f"  - All degraded -> {provider} (least degraded)")

        return True
    except Exception as e:
        print(f"[FAIL] GracefulDegradation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_5_error_recovery_manager():
    """Test 5: ErrorRecoveryManager orchestration"""
    print("\n=== Test 5: ErrorRecoveryManager Orchestration ===")
    try:
        from src.core.error_recovery import (
            ErrorRecoveryManager, RecoveryStrategy,
            ErrorCategory, ErrorSeverity
        )

        manager = ErrorRecoveryManager()
        print(f"[PASS] Created ErrorRecoveryManager")

        # Handle a rate limit error
        strategy = manager.handle_error(
            provider="openai",
            model="gpt-4",
            error_code=429,
            error_message="Rate limited",
            error_category=ErrorCategory.RATE_LIMIT,
            severity=ErrorSeverity.HIGH
        )
        assert strategy == RecoveryStrategy.RETRY, f"Expected RETRY, got {strategy.value}"
        print(f"[PASS] HTTP 429 -> {strategy.value}")

        # Handle authorization error
        strategy = manager.handle_error(
            provider="openai",
            model="gpt-4",
            error_code=401,
            error_message="Unauthorized",
            error_category=ErrorCategory.AUTH,
            severity=ErrorSeverity.HIGH
        )
        assert strategy == RecoveryStrategy.FALLBACK, f"Expected FALLBACK, got {strategy.value}"
        print(f"[PASS] HTTP 401 -> {strategy.value}")

        # Mark recovery as successful
        manager.mark_success("openai")
        print(f"[PASS] Marked success for openai")

        # Get full status
        status = manager.get_recovery_status()
        print(f"[PASS] Recovery status retrieved:")
        print(f"  - Circuit breakers: {len(status['circuit_breakers'])}")
        print(f"  - Error stats: {len(status['error_stats'])} providers tracked")
        print(f"  - Degradation active: {bool(status['degradation_status'])}")

        # Format report
        report = manager.format_recovery_report()
        assert "<b>" in report, "Report should contain HTML formatting"
        print(f"[PASS] Recovery report formatted ({len(report)} chars)")

        return True
    except Exception as e:
        print(f"[FAIL] ErrorRecoveryManager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all validation tests"""
    print("\n" + "="*60)
    print("ERROR RECOVERY MODULE VALIDATION (Sprint 9.3)")
    print("="*60)

    tests = [
        ("Imports", test_1_imports),
        ("CircuitBreaker", test_2_circuit_breaker),
        ("ErrorTelemetry", test_3_error_telemetry),
        ("GracefulDegradation", test_4_graceful_degradation),
        ("ErrorRecoveryManager", test_5_error_recovery_manager),
    ]

    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n[FAIL] CRITICAL ERROR in {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # Summary
    print("\n" + "="*60)
    print("VALIDATION SUMMARY")
    print("="*60)

    passed = sum(1 for _, p in results if p)
    total = len(results)

    for name, passed_bool in results:
        status = "[PASS]" if passed_bool else "[FAIL]"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n[PASS] ALL TESTS PASSED - Error Recovery module is ready for integration!")
        return 0
    else:
        print(f"\n[FAIL] {total - passed} test(s) failed - Please review errors above")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
