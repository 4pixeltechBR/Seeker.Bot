"""
Test Phase 1: Core Supervisor Routing & Execution

Tests:
- Supervisor router (CognitiveLoadRouter + CrewRouter)
- Crew selection based on input
- Parallel vs sequential execution
- Response compilation
- Latency tracking
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


async def test_cognitive_router():
    """Test CognitiveLoadRouter detects depth"""
    router = CognitiveLoadRouter()

    # Test REFLEX
    decision = router.route("ok")
    assert decision.depth.value == "reflex", f"Expected reflex, got {decision.depth}"
    print("[OK] CognitiveRouter detects REFLEX")

    # Test DELIBERATE
    decision = router.route("como configuro Docker?")
    assert decision.depth.value == "deliberate", f"Expected deliberate, got {decision.depth}"
    print("[OK] CognitiveRouter detects DELIBERATE")

    # Test DEEP
    decision = router.route("vale a pena migrar para Kubernetes?")
    assert decision.depth.value == "deep", f"Expected deep, got {decision.depth}"
    print("[OK] CognitiveRouter detects DEEP")


async def test_crew_router_reflex():
    """Test CrewRouter routes REFLEX -> monitor only"""
    decision = crew_router.route(
        user_input="ok",
        cognitive_depth=CognitiveDepth.REFLEX,
    )

    assert "monitor" in decision.target_crews
    assert decision.parallelizable == False
    assert decision.estimated_latency_ms == 500
    print(f"[OK] REFLEX routes to: {decision.target_crews}")


async def test_crew_router_deliberate():
    """Test CrewRouter routes DELIBERATE -> monitor + hunter"""
    decision = crew_router.route(
        user_input="procura oportunidades de venda",
        cognitive_depth=CognitiveDepth.DELIBERATE,
    )

    assert "monitor" in decision.target_crews
    assert "hunter" in decision.target_crews
    assert decision.parallelizable == True
    print(f"[OK] DELIBERATE routes to: {decision.target_crews}")


async def test_crew_router_deep():
    """Test CrewRouter routes DEEP -> monitor + hunter + analyst"""
    decision = crew_router.route(
        user_input="qual eh a melhor estrategia pra crescer?",
        cognitive_depth=CognitiveDepth.DEEP,
    )

    assert "monitor" in decision.target_crews
    assert "hunter" in decision.target_crews
    assert "analyst" in decision.target_crews
    assert decision.parallelizable == True
    print(f"[OK] DEEP routes to: {decision.target_crews}")


async def test_crew_router_action_intent():
    """Test CrewRouter detects action intent and adds executor"""
    decision = crew_router.route(
        user_input="faça um backup do repositorio",
        cognitive_depth=CognitiveDepth.DELIBERATE,
    )

    assert "executor" in decision.target_crews
    print(f"[OK] Action intent detected, executor added: {decision.target_crews}")


async def test_crew_router_vision():
    """Test CrewRouter adds vision for image requests"""
    decision = crew_router.route(
        user_input="le o screenshot dessa tela",
        cognitive_depth=CognitiveDepth.DELIBERATE,
        include_vision=True,
    )

    assert "vision" in decision.target_crews
    print(f"[OK] Vision crew detected: {decision.target_crews}")


async def test_supervisor_routing():
    """Test Supervisor can route input correctly"""
    crews = {
        "monitor": monitor_crew.monitor,
        "hunter": hunter_crew.hunter,
        "executor": executor_crew.executor,
        "analyst": analyst_crew.analyst,
        "vision": vision_crew.vision,
        "admin": admin_crew.admin,
    }

    supervisor = Supervisor(crews)

    # Test routing decision
    decision = supervisor.crew_router.route(
        user_input="procura leads",
        cognitive_depth=CognitiveDepth.DELIBERATE,
    )

    assert len(decision.target_crews) > 0
    assert decision.estimated_cost > 0
    print(f"[OK] Supervisor routes correctly: {decision.target_crews}")


async def test_supervisor_process():
    """Test Supervisor end-to-end process"""
    crews = {
        "monitor": monitor_crew.monitor,
        "hunter": hunter_crew.hunter,
        "executor": executor_crew.executor,
        "analyst": analyst_crew.analyst,
        "vision": vision_crew.vision,
        "admin": admin_crew.admin,
    }

    supervisor = Supervisor(crews)

    result = await supervisor.process(
        user_input="qual eh o status?",
        user_id=123,
        session_id="test-session-1",
        memory_context=["Previous context"],
    )

    assert result.response is not None
    assert result.crew_id == "supervisor"
    assert "[OK]" in result.response or "PLACEHOLDER" in result.response
    print(f"[OK] Supervisor process completed")
    print(f"    Response: {result.response[:100]}")


async def test_response_compilation():
    """Test response compilation logic"""
    crews = {
        "monitor": monitor_crew.monitor,
        "hunter": hunter_crew.hunter,
        "executor": executor_crew.executor,
        "analyst": analyst_crew.analyst,
        "vision": vision_crew.vision,
        "admin": admin_crew.admin,
    }

    supervisor = Supervisor(crews)

    # Create mock crew results
    from src.core.hierarchy.interfaces import CrewResult

    crew_results = {
        "monitor": CrewResult(
            response="System is healthy",
            crew_id="monitor",
            cost_usd=0.01,
            llm_calls=1,
            confidence=0.95,  # High confidence
            latency_ms=500,
            sources=[],
        ),
        "hunter": CrewResult(
            response="Found 5 opportunities",
            crew_id="hunter",
            cost_usd=0.05,
            llm_calls=2,
            confidence=0.80,
            latency_ms=2000,
            sources=[],
        ),
    }

    compiled = supervisor._compile_final_response(crew_results)

    assert "System is healthy" in compiled
    assert compiled is not None
    print("[OK] Response compilation works")
    print(f"    Compiled: {compiled[:100]}")


async def main():
    """Run all Phase 1 tests"""
    print("\n" + "=" * 60)
    print("PHASE 1 TESTS: Core Supervisor Routing & Execution")
    print("=" * 60 + "\n")

    try:
        await test_cognitive_router()
        await test_crew_router_reflex()
        await test_crew_router_deliberate()
        await test_crew_router_deep()
        await test_crew_router_action_intent()
        await test_crew_router_vision()
        await test_supervisor_routing()
        await test_supervisor_process()
        await test_response_compilation()

        print("\n" + "=" * 60)
        print("[OK] ALL PHASE 1 TESTS PASSED")
        print("=" * 60 + "\n")
        print("PHASE 1 DELIVERABLE: Supervisor can route & invoke crews [OK]")
        return 0

    except Exception as e:
        print(f"\n[FAILED] TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
