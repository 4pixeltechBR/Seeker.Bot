"""
Test Phase 0: Verify LangGraph skeleton compiles and basic structure works
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.hierarchy import (
    Supervisor,
    CognitiveDepth,
    CrewRequest,
    GoalEventLog,
    GoalEventType,
)
from src.core.hierarchy.crews import (
    monitor_crew,
    hunter_crew,
    executor_crew,
    analyst_crew,
    vision_crew,
    admin_crew,
)


async def test_imports():
    """Test that all imports work"""
    print("[OK] All imports successful")


async def test_interfaces():
    """Test interface definitions"""
    request = CrewRequest(
        user_input="Test input",
        cognitive_depth=CognitiveDepth.DELIBERATE,
        memory_context=["fact1", "fact2"],
        user_id=123,
        session_id="test-session",
    )
    assert request.user_input == "Test input"
    print("[OK] CrewRequest interface works")


async def test_crews_exist():
    """Test that all 6 crews are instantiated"""
    crews = {
        "monitor": monitor_crew.monitor,
        "hunter": hunter_crew.hunter,
        "executor": executor_crew.executor,
        "analyst": analyst_crew.analyst,
        "vision": vision_crew.vision,
        "admin": admin_crew.admin,
    }

    for crew_id, crew in crews.items():
        assert crew.crew_id == crew_id
        status = crew.get_status()
        assert status["crew_id"] == crew_id
        print(f"[OK] Crew '{crew_id}' instantiated and responds to status()")


async def test_supervisor_instantiation():
    """Test Supervisor can be created"""
    crews = {
        "monitor": monitor_crew.monitor,
        "hunter": hunter_crew.hunter,
        "executor": executor_crew.executor,
        "analyst": analyst_crew.analyst,
        "vision": vision_crew.vision,
        "admin": admin_crew.admin,
    }

    supervisor = Supervisor(crews)
    assert supervisor.graph is not None
    print("[OK] Supervisor instantiated with LangGraph")


async def test_event_log():
    """Test event sourcing"""
    event_log = GoalEventLog("data/test_events.db")

    # Append event
    event_id = await event_log.append_event(
        goal_id="test-goal-1",
        crew_id="monitor",
        event_type=GoalEventType.STARTED,
        payload={"test": "data"},
    )

    assert event_id > 0
    print(f"[OK] Event appended with ID {event_id}")

    # Retrieve events
    events = await event_log.get_events_for_goal("test-goal-1")
    assert len(events) == 1
    assert events[0].event_type == GoalEventType.STARTED
    print(f"[OK] Events retrieved and verified")

    # Replay state
    state = await event_log.replay_goal_state("test-goal-1")
    assert state["goal_id"] == "test-goal-1"
    print(f"[OK] State replayed from event log")


async def test_crew_execution():
    """Test crew can be called (even if stub)"""
    request = CrewRequest(
        user_input="Test",
        cognitive_depth=CognitiveDepth.REFLEX,
        memory_context=[],
        user_id=123,
        session_id="test",
    )

    result = await monitor_crew.monitor.execute(request)
    assert result.crew_id == "monitor"
    assert "PLACEHOLDER" in result.response
    print("[OK] Crew execution works (stub returns placeholder)")


async def main():
    """Run all Phase 0 tests"""
    print("\n" + "=" * 60)
    print("PHASE 0 TESTS: LangGraph Skeleton Compilation")
    print("=" * 60 + "\n")

    try:
        await test_imports()
        await test_interfaces()
        await test_crews_exist()
        await test_supervisor_instantiation()
        await test_event_log()
        await test_crew_execution()

        print("\n" + "=" * 60)
        print("[OK] ALL PHASE 0 TESTS PASSED")
        print("=" * 60 + "\n")
        print("PHASE 0 DELIVERABLE: Empty hierarchical graph compiles [OK]")
        return 0

    except Exception as e:
        print(f"\n[FAILED] TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
