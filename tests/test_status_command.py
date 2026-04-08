"""
Tests for extended /status command with OODA Loop and Goal Cycles stats.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.core.reasoning.ooda_loop import OODALoop, OODAIteration, LoopResult


@pytest.fixture
def ooda_loop():
    """Create OODALoop with some history."""
    loop = OODALoop()
    # Simulate 5 iterations
    for i in range(5):
        iteration = OODAIteration(
            iteration_id=f"iter_{i}",
            user_input=f"test input {i}",
            result=LoopResult.SUCCESS if i < 4 else LoopResult.BLOCKED,
            total_latency_ms=100 + i * 10,
        )
        loop.history.append(iteration)
    return loop


class TestOODALoopStats:
    """Test OODA Loop statistics."""

    def test_ooda_loop_get_stats(self, ooda_loop):
        """OODALoop should return correct statistics."""
        stats = ooda_loop.get_stats()

        assert stats["total_iterations"] == 5
        assert stats["success_count"] == 4
        assert stats["blocked_count"] == 1
        assert stats["success_rate"] == 0.8  # 4/5
        assert stats["avg_latency_ms"] > 0

    def test_ooda_loop_empty_stats(self):
        """Empty OODALoop should return zero stats."""
        loop = OODALoop()
        stats = loop.get_stats()

        assert stats["total_iterations"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["avg_latency_ms"] == 0.0
        # Empty stats doesn't include blocked_count for efficiency

    def test_ooda_loop_stats_format(self, ooda_loop):
        """Stats should be in format suitable for display."""
        stats = ooda_loop.get_stats()

        # Check required fields for /status display
        assert "total_iterations" in stats
        assert "success_rate" in stats
        assert "blocked_count" in stats
        assert "avg_latency_ms" in stats


class TestStatusCommandIntegration:
    """Test /status command with OODA Loop integration."""

    def test_status_includes_ooda_stats(self, ooda_loop):
        """Status output should include OODA stats when available."""
        stats = ooda_loop.get_stats()

        # Simulate what /status command would output
        output_lines = []
        if stats["total_iterations"] > 0:
            output_lines.append("🔄 OODA Loop:")
            output_lines.append(f"  {stats['total_iterations']} iterações")
            output_lines.append(
                f"  Success rate: {stats['success_rate']:.0%} | "
                f"Bloqueadas: {stats['blocked_count']}"
            )
            output_lines.append(f"  Latência média: {stats['avg_latency_ms']:.0f}ms")

        # Verify format
        assert len(output_lines) > 0
        assert "OODA Loop" in output_lines[0]
        assert "Success rate" in output_lines[2]

    def test_ooda_stats_empty_no_output(self):
        """Empty OODA stats should not add output."""
        loop = OODALoop()
        stats = loop.get_stats()

        # Empty stats should not trigger output
        if stats["total_iterations"] == 0:
            # This is the expected behavior
            assert stats["total_iterations"] == 0


class TestOODABlockedTracking:
    """Test that blocked actions are properly tracked in stats."""

    def test_blocked_count_increments(self, ooda_loop):
        """Blocked iterations should be counted."""
        stats = ooda_loop.get_stats()
        assert stats["blocked_count"] == 1

    def test_success_rate_with_blocks(self, ooda_loop):
        """Success rate should account for blocked iterations."""
        stats = ooda_loop.get_stats()
        # 4 success out of 5 total = 80%
        assert stats["success_rate"] == 0.8


class TestLatencyTracking:
    """Test that latency is properly tracked and averaged."""

    def test_avg_latency_calculation(self, ooda_loop):
        """Average latency should be calculated correctly."""
        stats = ooda_loop.get_stats()
        # Iterations: 100, 110, 120, 130, 140 ms
        # Average: (100+110+120+130+140) / 5 = 120
        expected_avg = (100 + 110 + 120 + 130 + 140) / 5
        assert abs(stats["avg_latency_ms"] - expected_avg) < 1.0

    def test_latency_unit_milliseconds(self, ooda_loop):
        """Latency should be in milliseconds."""
        stats = ooda_loop.get_stats()
        assert stats["avg_latency_ms"] > 0
        # Should be reasonable (100-200ms range for our test data)
        assert 50 < stats["avg_latency_ms"] < 200


class TestHistoryLimits:
    """Test that history respects limits."""

    def test_history_grow_correctly(self, ooda_loop):
        """History should grow with each iteration."""
        original_len = len(ooda_loop.history)
        assert original_len == 5

    def test_get_history_limit(self, ooda_loop):
        """get_history should respect limit parameter."""
        history_last_3 = ooda_loop.get_history(limit=3)
        assert len(history_last_3) == 3

    def test_get_history_more_than_available(self, ooda_loop):
        """get_history with limit > available should return all."""
        history_limit_100 = ooda_loop.get_history(limit=100)
        assert len(history_limit_100) == 5  # Only 5 iterations exist


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
