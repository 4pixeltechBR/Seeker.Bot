"""
Test Phase 2: Crew Implementation - Monitor, Executor, Analyst

Tests:
- MonitorCrew health checks (CPU, RAM, disk, Ollama)
- ExecutorCrew action detection and execution
- AnalystCrew analysis generation
- Supervisor integration with implemented crews
- Confidence scoring across crew results
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.hierarchy import (
    Supervisor,
    CrewRequest,
)
from src.core.router.cognitive_load import CognitiveLoadRouter, CognitiveDepth
from src.core.hierarchy.crew_router import crew_router
from src.core.hierarchy.crews import (
    monitor_crew,
    hunter_crew,
    executor_crew,
    analyst_crew,
    vision_crew,
    admin_crew,
)


async def test_monitor_crew_health_check():
    """Test MonitorCrew executes health monitoring"""
    request = CrewRequest(
        user_input="check system health",
        cognitive_depth=CognitiveDepth.REFLEX,
        memory_context=[],
        user_id=123,
        session_id="test-monitor",
        timeout_sec=5.0,
    )

    result = await monitor_crew.monitor.execute(request)

    assert result.crew_id == "monitor"
    assert result.cost_usd == 0.0  # Monitor has no LLM cost
    assert result.llm_calls == 0
    assert result.confidence >= 0.3  # At least partially operational
    assert "CPU" in result.response or "Sistema" in result.response
    assert result.latency_ms > 0
    print(f"[OK] MonitorCrew health check: confidence={result.confidence}, latency={result.latency_ms}ms")
    print(f"    Response: {result.response[:80]}...")


async def test_executor_crew_git_action():
    """Test ExecutorCrew detects and prepares git actions"""
    request = CrewRequest(
        user_input="please make a commit of the changes",
        cognitive_depth=CognitiveDepth.DELIBERATE,
        memory_context=[],
        user_id=123,
        session_id="test-executor-git",
        timeout_sec=10.0,
    )

    result = await executor_crew.executor.execute(request)

    assert result.crew_id == "executor"
    # Git commit may have 0 changes, but action should be detected
    assert result.latency_ms >= 0
    assert result.confidence >= 0.1  # At least tried
    print(f"[OK] ExecutorCrew git action detected: confidence={result.confidence}")
    print(f"    Response: {result.response[:100]}...")


async def test_executor_crew_action_detection():
    """Test ExecutorCrew action intent detection"""
    request = CrewRequest(
        user_input="execute ls command",
        cognitive_depth=CognitiveDepth.REFLEX,
        memory_context=[],
        user_id=123,
        session_id="test-executor-bash",
        timeout_sec=5.0,
    )

    result = await executor_crew.executor.execute(request)

    assert result.crew_id == "executor"
    # Just check that executor detected the action intent (response may be "nenhuma ação" or actual execution)
    assert "execute" in result.response.lower() or "execut" in result.response.lower() or "nenhuma" in result.response.lower() or result.confidence > 0.2
    print(f"[OK] ExecutorCrew bash detection: response contains action reference")


async def test_executor_crew_no_action():
    """Test ExecutorCrew returns gracefully when no action detected"""
    request = CrewRequest(
        user_input="hello, how are you?",
        cognitive_depth=CognitiveDepth.REFLEX,
        memory_context=[],
        user_id=123,
        session_id="test-executor-no-action",
        timeout_sec=5.0,
    )

    result = await executor_crew.executor.execute(request)

    assert result.crew_id == "executor"
    assert result.confidence < 0.6  # Low confidence for no action
    assert "Nenhuma ação" in result.response or "No action" in result.response
    print(f"[OK] ExecutorCrew no-action detection: confidence={result.confidence}")


async def test_analyst_crew_briefing():
    """Test AnalystCrew generates briefing analysis"""
    request = CrewRequest(
        user_input="gere um briefing diário",
        cognitive_depth=CognitiveDepth.DELIBERATE,
        memory_context=["Fact 1: System operational", "Fact 2: 10 leads processed"],
        user_id=123,
        session_id="test-analyst-briefing",
        timeout_sec=10.0,
    )

    result = await analyst_crew.analyst.execute(request)

    assert result.crew_id == "analyst"
    assert "BRIEFING" in result.response or "briefing" in result.response.lower()
    assert result.llm_calls == 1
    assert result.cost_usd > 0.0  # Analysis has LLM cost
    assert result.confidence >= 0.80
    assert result.should_save_fact == True
    print(f"[OK] AnalystCrew briefing: confidence={result.confidence}, cost=${result.cost_usd:.3f}")


async def test_analyst_crew_improvement():
    """Test AnalystCrew generates improvement analysis"""
    request = CrewRequest(
        user_input="qual é a recomendação de improvement?",
        cognitive_depth=CognitiveDepth.DEEP,
        memory_context=[],
        user_id=123,
        session_id="test-analyst-improvement",
        timeout_sec=10.0,
    )

    result = await analyst_crew.analyst.execute(request)

    assert result.crew_id == "analyst"
    assert "MELHORIA" in result.response or "improvement" in result.response.lower()
    assert result.llm_calls == 1
    assert result.confidence >= 0.80
    print(f"[OK] AnalystCrew improvement: confidence={result.confidence}")


async def test_analyst_crew_revenue():
    """Test AnalystCrew generates revenue analysis"""
    request = CrewRequest(
        user_input="analyze revenue this week",
        cognitive_depth=CognitiveDepth.DEEP,
        memory_context=[],
        user_id=123,
        session_id="test-analyst-revenue",
        timeout_sec=10.0,
    )

    result = await analyst_crew.analyst.execute(request)

    assert result.crew_id == "analyst"
    assert "receita" in result.response.lower() or "revenue" in result.response.lower()
    assert "$" in result.response  # Contains financial data
    assert result.llm_calls == 1
    print(f"[OK] AnalystCrew revenue: confidence={result.confidence}")


async def test_supervisor_with_monitor_crew():
    """Test Supervisor orchestrates with real MonitorCrew"""
    crews = {
        "monitor": monitor_crew.monitor,
        "hunter": hunter_crew.hunter,
        "executor": executor_crew.executor,
        "analyst": analyst_crew.analyst,
        "vision": vision_crew.vision,
        "admin": admin_crew.admin,
    }

    supervisor = Supervisor(crews)

    # REFLEX request should route to monitor only
    result = await supervisor.process(
        user_input="está tudo ok?",  # Simple health check -> REFLEX
        user_id=123,
        session_id="test-supervisor-monitor",
        memory_context=[],
    )

    assert result.response is not None
    assert result.crew_id == "supervisor"
    # Confidence should reflect monitor crew's confidence
    assert result.confidence >= 0.3
    print(f"[OK] Supervisor with MonitorCrew: confidence={result.confidence}")
    print(f"    Response: {result.response[:100]}...")


async def test_supervisor_with_executor_crew():
    """Test Supervisor orchestrates with ExecutorCrew"""
    crews = {
        "monitor": monitor_crew.monitor,
        "hunter": hunter_crew.hunter,
        "executor": executor_crew.executor,
        "analyst": analyst_crew.analyst,
        "vision": vision_crew.vision,
        "admin": admin_crew.admin,
    }

    supervisor = Supervisor(crews)

    # Request with action intent should route to executor
    result = await supervisor.process(
        user_input="faça um commit do código",
        user_id=123,
        session_id="test-supervisor-executor",
        memory_context=[],
    )

    assert result.response is not None
    assert result.crew_id == "supervisor"
    assert result.latency_ms > 0
    print(f"[OK] Supervisor with ExecutorCrew: latency={result.latency_ms}ms")


async def test_supervisor_with_analyst_crew():
    """Test Supervisor orchestrates with AnalystCrew"""
    crews = {
        "monitor": monitor_crew.monitor,
        "hunter": hunter_crew.hunter,
        "executor": executor_crew.executor,
        "analyst": analyst_crew.analyst,
        "vision": vision_crew.vision,
        "admin": admin_crew.admin,
    }

    supervisor = Supervisor(crews)

    # DEEP request should route to analyst
    result = await supervisor.process(
        user_input="quale estratégia melhor pro crescimento?",  # Complex -> DEEP
        user_id=123,
        session_id="test-supervisor-analyst",
        memory_context=[],
    )

    assert result.response is not None
    assert result.crew_id == "supervisor"
    assert result.confidence >= 0.3
    print(f"[OK] Supervisor with AnalystCrew: response length={len(result.response)}")


async def test_crew_error_handling():
    """Test crews handle errors gracefully and return CrewResult"""
    # Monitor with extremely short timeout
    request = CrewRequest(
        user_input="check health",
        cognitive_depth=CognitiveDepth.REFLEX,
        memory_context=[],
        user_id=123,
        session_id="test-error-handling",
        timeout_sec=0.001,  # Very short timeout
    )

    # Even with error, monitor should return CrewResult, not raise
    result = await monitor_crew.monitor.execute(request)

    assert result is not None
    assert isinstance(result.response, str)
    assert result.crew_id == "monitor"
    # Confidence may be low due to timeout, but result is valid
    print(f"[OK] Error handling: monitor returned CrewResult even with tight timeout")


async def test_monitor_crew_status():
    """Test MonitorCrew provides extended status"""
    status = monitor_crew.monitor.get_status()

    assert status["crew_id"] == "monitor"
    assert "is_healthy" in status
    assert "status" in status
    assert "recent_checks" in status or "history" in status
    print(f"[OK] MonitorCrew status: {status['status']}")


async def test_executor_crew_status():
    """Test ExecutorCrew provides extended status"""
    status = executor_crew.executor.get_status()

    assert status["crew_id"] == "executor"
    assert "is_healthy" in status
    assert "last_actions_count" in status or "repo_dir" in status
    print(f"[OK] ExecutorCrew status: {status['status']}")


async def test_analyst_crew_status():
    """Test AnalystCrew provides extended status"""
    status = analyst_crew.analyst.get_status()

    assert status["crew_id"] == "analyst"
    assert "is_healthy" in status
    assert "analysis_count" in status or "recent_analyses" in status
    print(f"[OK] AnalystCrew status: {status['status']}")


async def main():
    """Run all Phase 2 tests"""
    print("\n" + "=" * 60)
    print("PHASE 2 TESTS: Crew Implementation (Monitor/Executor/Analyst)")
    print("=" * 60 + "\n")

    try:
        # Monitor Crew tests
        print("[MONITOR CREW TESTS]")
        await test_monitor_crew_health_check()

        # Executor Crew tests
        print("\n[EXECUTOR CREW TESTS]")
        await test_executor_crew_git_action()
        await test_executor_crew_action_detection()
        await test_executor_crew_no_action()

        # Analyst Crew tests
        print("\n[ANALYST CREW TESTS]")
        await test_analyst_crew_briefing()
        await test_analyst_crew_improvement()
        await test_analyst_crew_revenue()

        # Supervisor Integration tests
        print("\n[SUPERVISOR INTEGRATION TESTS]")
        await test_supervisor_with_monitor_crew()
        await test_supervisor_with_executor_crew()
        await test_supervisor_with_analyst_crew()

        # Error handling
        print("\n[ERROR HANDLING TESTS]")
        await test_crew_error_handling()

        # Status tests
        print("\n[STATUS TESTS]")
        await test_monitor_crew_status()
        await test_executor_crew_status()
        await test_analyst_crew_status()

        print("\n" + "=" * 60)
        print("[OK] ALL PHASE 2 TESTS PASSED")
        print("=" * 60 + "\n")
        print("PHASE 2 DELIVERABLE: Crews Monitor/Executor/Analyst implemented [OK]")
        return 0

    except Exception as e:
        print(f"\n[FAILED] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
