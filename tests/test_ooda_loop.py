"""
Unit tests for OODA Loop (Observe-Orient-Decide-Act).
Tests the formal reasoning cycle with decision phases.
"""

import pytest
import asyncio
from src.core.reasoning.ooda_loop import (
    OODALoop,
    StreamingOODALoop,
    OODAIteration,
    Decision,
    OrientationModel,
    ObservationData,
    ActionResult,
    DecisionPhase,
    LoopResult,
)


@pytest.fixture
def ooda_loop():
    """Initialize OODA loop."""
    return OODALoop()


@pytest.fixture
def streaming_ooda():
    """Initialize Streaming OODA loop."""
    return StreamingOODALoop()


class TestOODABasicFlow:
    """Test basic OODA cycle flow."""

    @pytest.mark.asyncio
    async def test_full_cycle_success(self, ooda_loop):
        """Full OODA cycle should complete successfully."""

        async def observe_fn(user_input, context):
            return ObservationData(user_input=user_input)

        async def orient_fn(observation):
            return OrientationModel(
                confidence=0.95,
                reasoning="Simple question",
            )

        async def decide_fn(orientation):
            return Decision(
                action_type="respond",
                parameters={"response": "Hello"},
                autonomy_tier=3,
                rationale="Direct response",
                verification_required=False,
            )

        async def act_fn(decision):
            return ActionResult(
                success=True,
                output="Response sent",
                latency_ms=10.5,
            )

        iteration = await ooda_loop.execute(
            user_input="Hello",
            observe_fn=observe_fn,
            orient_fn=orient_fn,
            decide_fn=decide_fn,
            act_fn=act_fn,
        )

        assert iteration.result == LoopResult.SUCCESS
        assert iteration.observation is not None
        assert iteration.orientation is not None
        assert iteration.decision is not None
        assert iteration.action_result is not None
        assert iteration.action_result.success is True

    @pytest.mark.asyncio
    async def test_cycle_has_timing(self, ooda_loop):
        """OODA iteration should track timing."""

        async def observe_fn(user_input, context):
            await asyncio.sleep(0.01)
            return ObservationData(user_input=user_input)

        async def orient_fn(observation):
            return OrientationModel()

        async def decide_fn(orientation):
            return Decision(
                action_type="test",
                autonomy_tier=3,
                verification_required=False,
            )

        async def act_fn(decision):
            return ActionResult(success=True)

        iteration = await ooda_loop.execute(
            user_input="test",
            observe_fn=observe_fn,
            orient_fn=orient_fn,
            decide_fn=decide_fn,
            act_fn=act_fn,
        )

        assert iteration.total_latency_ms > 0
        assert iteration.timestamp_end > iteration.timestamp_start

    @pytest.mark.asyncio
    async def test_cycle_has_iteration_id(self, ooda_loop):
        """Each iteration should have unique ID."""

        async def observe_fn(user_input, context):
            return ObservationData(user_input=user_input)

        async def orient_fn(observation):
            return OrientationModel()

        async def decide_fn(orientation):
            return Decision(action_type="test", autonomy_tier=3, verification_required=False)

        async def act_fn(decision):
            return ActionResult(success=True)

        iter1 = await ooda_loop.execute(
            "input1",
            observe_fn,
            orient_fn,
            decide_fn,
            act_fn,
        )

        iter2 = await ooda_loop.execute(
            "input2",
            observe_fn,
            orient_fn,
            decide_fn,
            act_fn,
        )

        assert iter1.iteration_id != iter2.iteration_id
        assert "iter_" in iter1.iteration_id
        assert "iter_" in iter2.iteration_id


class TestOODABlocking:
    """Test blocking behavior for high-risk actions."""

    @pytest.mark.asyncio
    async def test_blocks_on_manual_approval_required(self, ooda_loop):
        """Should block if MANUAL approval tier detected."""

        # Mock IntentCard with MANUAL tier
        class MockIntentCard:
            def __init__(self):
                self.autonomy_tier = type("AutonomyTier", (), {"name": "MANUAL"})()

            def requires_approval(self):
                return True

        async def observe_fn(user_input, context):
            return ObservationData(user_input=user_input)

        async def orient_fn(observation):
            return OrientationModel(
                intent_card=MockIntentCard(),
                confidence=0.9,
            )

        async def decide_fn(orientation):
            return Decision(action_type="delete", autonomy_tier=1)

        async def act_fn(decision):
            # Should never reach here
            raise AssertionError("Should not reach act phase")

        iteration = await ooda_loop.execute(
            "delete everything",
            observe_fn,
            orient_fn,
            decide_fn,
            act_fn,
        )

        assert iteration.result == LoopResult.BLOCKED
        assert iteration.orientation is not None
        # Act should not execute
        assert iteration.action_result is None

    @pytest.mark.asyncio
    async def test_blocks_on_verification_failure(self, ooda_loop):
        """Should block if pre-commit verification fails."""

        async def observe_fn(user_input, context):
            return ObservationData(user_input=user_input)

        async def orient_fn(observation):
            return OrientationModel(confidence=0.8)

        async def decide_fn(orientation):
            return Decision(
                action_type="delete",
                autonomy_tier=1,  # MANUAL requires explicit approval
                verification_required=True,
            )

        async def act_fn(decision):
            raise AssertionError("Should not reach act phase")

        iteration = await ooda_loop.execute(
            "delete",
            observe_fn,
            orient_fn,
            decide_fn,
            act_fn,
        )

        assert iteration.result == LoopResult.BLOCKED
        assert iteration.decision is not None


class TestOODAHistory:
    """Test history tracking."""

    @pytest.mark.asyncio
    async def test_history_tracks_iterations(self, ooda_loop):
        """Should maintain history of iterations."""

        async def observe_fn(user_input, context):
            return ObservationData(user_input=user_input)

        async def orient_fn(observation):
            return OrientationModel()

        async def decide_fn(orientation):
            return Decision(action_type="test", autonomy_tier=3, verification_required=False)

        async def act_fn(decision):
            return ActionResult(success=True)

        # Execute 3 times
        for i in range(3):
            await ooda_loop.execute(
                f"input{i}",
                observe_fn,
                orient_fn,
                decide_fn,
                act_fn,
            )

        history = ooda_loop.get_history()
        assert len(history) == 3
        assert all(isinstance(it, OODAIteration) for it in history)

    @pytest.mark.asyncio
    async def test_history_limit(self, ooda_loop):
        """Should respect history limit."""

        async def observe_fn(user_input, context):
            return ObservationData(user_input=user_input)

        async def orient_fn(observation):
            return OrientationModel()

        async def decide_fn(orientation):
            return Decision(action_type="test", autonomy_tier=3, verification_required=False)

        async def act_fn(decision):
            return ActionResult(success=True)

        # Execute 30 times
        for i in range(30):
            await ooda_loop.execute(
                f"input{i}",
                observe_fn,
                orient_fn,
                decide_fn,
                act_fn,
            )

        # Should return only last 20 (default limit)
        history = ooda_loop.get_history(limit=20)
        assert len(history) == 20


class TestOODAStats:
    """Test statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_empty_loop(self, ooda_loop):
        """Empty loop should have zero stats."""
        stats = ooda_loop.get_stats()
        assert stats["total_iterations"] == 0
        assert stats["success_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_after_iterations(self, ooda_loop):
        """Stats should aggregate results."""

        async def observe_fn(user_input, context):
            return ObservationData(user_input=user_input)

        async def orient_fn(observation):
            return OrientationModel()

        async def decide_fn(orientation):
            return Decision(action_type="test", autonomy_tier=3, verification_required=False)

        async def act_fn(decision):
            return ActionResult(success=True)

        # 2 successes
        for i in range(2):
            await ooda_loop.execute(
                f"input{i}",
                observe_fn,
                orient_fn,
                decide_fn,
                act_fn,
            )

        stats = ooda_loop.get_stats()
        assert stats["total_iterations"] == 2
        assert stats["success_count"] == 2
        assert stats["success_rate"] == 1.0
        assert stats["avg_latency_ms"] >= 0  # May be 0 for very fast operations

    @pytest.mark.asyncio
    async def test_stats_tracks_blocked(self, ooda_loop):
        """Stats should track blocked iterations."""

        class MockIntentCard:
            def requires_approval(self):
                return True

            autonomy_tier = type("AutonomyTier", (), {"name": "MANUAL"})()

        async def observe_fn(user_input, context):
            return ObservationData(user_input=user_input)

        async def orient_fn(observation):
            return OrientationModel(intent_card=MockIntentCard())

        async def decide_fn(orientation):
            return Decision(action_type="test", autonomy_tier=1)

        async def act_fn(decision):
            raise AssertionError("Should not execute")

        # 1 blocked
        await ooda_loop.execute(
            "blocked",
            observe_fn,
            orient_fn,
            decide_fn,
            act_fn,
        )

        stats = ooda_loop.get_stats()
        assert stats["blocked_count"] == 1
        assert stats["success_rate"] == 0.0


class TestStreamingOODA:
    """Test StreamingOODALoop callbacks."""

    @pytest.mark.asyncio
    async def test_streaming_calls_callbacks(self):
        """Streaming loop should call phase callbacks."""
        phases_called = []

        async def on_phase_complete(phase: DecisionPhase, data):
            phases_called.append(phase)

        streaming = StreamingOODALoop(on_phase_complete=on_phase_complete)

        async def observe_fn(user_input, context):
            return ObservationData(user_input=user_input)

        async def orient_fn(observation):
            return OrientationModel()

        async def decide_fn(orientation):
            return Decision(action_type="test", autonomy_tier=3, verification_required=False)

        async def act_fn(decision):
            return ActionResult(success=True)

        await streaming.execute(
            "test",
            observe_fn,
            orient_fn,
            decide_fn,
            act_fn,
        )

        # Should have called all 4 phases
        assert DecisionPhase.OBSERVE in phases_called
        assert DecisionPhase.ORIENT in phases_called
        assert DecisionPhase.DECIDE in phases_called
        assert DecisionPhase.ACT in phases_called

    @pytest.mark.asyncio
    async def test_streaming_no_callback(self):
        """Streaming loop should work without callback."""
        streaming = StreamingOODALoop()

        async def observe_fn(user_input, context):
            return ObservationData(user_input=user_input)

        async def orient_fn(observation):
            return OrientationModel()

        async def decide_fn(orientation):
            return Decision(action_type="test", autonomy_tier=3, verification_required=False)

        async def act_fn(decision):
            return ActionResult(success=True)

        iteration = await streaming.execute(
            "test",
            observe_fn,
            orient_fn,
            decide_fn,
            act_fn,
        )

        assert iteration.result == LoopResult.SUCCESS


class TestOODALoggingAndMetadata:
    """Test logging and metadata generation."""

    @pytest.mark.asyncio
    async def test_iteration_log_entry(self, ooda_loop):
        """Iteration should generate log entry."""

        async def observe_fn(user_input, context):
            return ObservationData(user_input=user_input)

        async def orient_fn(observation):
            return OrientationModel()

        async def decide_fn(orientation):
            return Decision(action_type="test", autonomy_tier=3, verification_required=False)

        async def act_fn(decision):
            return ActionResult(success=True)

        iteration = await ooda_loop.execute(
            "test",
            observe_fn,
            orient_fn,
            decide_fn,
            act_fn,
        )

        log_entry = iteration.to_log_entry()
        assert "OODA" in log_entry
        assert iteration.iteration_id in log_entry
        assert "SUCCESS" in log_entry


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
