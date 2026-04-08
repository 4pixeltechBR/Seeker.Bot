"""
Tests for Health Dashboard (4.1)
src/core/goals/scheduler.py — get_health_dashboard() and get_goal_metrics()

Tests cover:
- Dashboard data structure and metrics calculation
- Trend analysis (success rate, latency trends)
- Cycle history persistence
- Multi-goal health aggregation
"""

import pytest
import time
from collections import deque
from unittest.mock import MagicMock, AsyncMock

from src.core.goals.scheduler import GoalScheduler
from src.core.goals.protocol import GoalStatus, NotificationChannel


@pytest.fixture
def mock_notifier():
    """Mock notifier for scheduler."""
    notifier = MagicMock()
    notifier.send = AsyncMock()
    return notifier


@pytest.fixture
def scheduler(mock_notifier):
    """Create a scheduler with mock notifier."""
    return GoalScheduler(mock_notifier)


@pytest.fixture
def mock_goal():
    """Create a mock goal."""
    goal = MagicMock()
    goal.name = "test_goal"
    goal.interval_seconds = 60
    goal.channels = [NotificationChannel.TELEGRAM]
    goal.get_status = MagicMock(return_value=GoalStatus.RUNNING)
    goal.serialize_state = MagicMock(return_value={})

    # Mock budget
    goal.budget = MagicMock()
    goal.budget.spent_today_usd = 0.5
    goal.budget.max_daily_usd = 1.0
    goal.budget.exhausted = False
    goal.budget.reset_if_new_day = MagicMock()
    goal.budget.spend = MagicMock()

    return goal


class TestHealthDashboard:
    """Test health dashboard metrics and reporting."""

    def test_get_health_dashboard_empty(self, scheduler):
        """Test dashboard with no goals registered."""
        dashboard = scheduler.get_health_dashboard()

        assert "timestamp" in dashboard
        assert "date" in dashboard
        assert "global_budget" in dashboard
        assert "goals" in dashboard
        assert "summary" in dashboard
        assert len(dashboard["goals"]) == 0
        assert dashboard["summary"]["total_goals"] == 0

    def test_get_goal_metrics_no_history(self, scheduler, mock_goal):
        """Test goal metrics with no execution history."""
        scheduler.register(mock_goal)

        metrics = scheduler.get_goal_metrics("test_goal")

        assert metrics["name"] == "test_goal"
        assert metrics["metrics"]["success_rate"] == 0.0
        assert metrics["metrics"]["total_cycles"] == 0
        assert metrics["metrics"]["consecutive_failures"] == 0

    def test_get_goal_metrics_with_successful_cycles(self, scheduler, mock_goal):
        """Test goal metrics with successful cycle history."""
        scheduler.register(mock_goal)

        # Simulate 5 successful cycles
        for i in range(5):
            scheduler._cycle_history["test_goal"].append({
                "ts": time.time() - (100 - i*20),  # Timestamps in past
                "ok": True,
                "cost": 0.1,
                "latency": 1.5,
                "summary": f"Success {i}",
            })

        metrics = scheduler.get_goal_metrics("test_goal")

        assert metrics["metrics"]["success_rate"] == 100.0
        assert metrics["metrics"]["total_cycles"] == 5
        assert metrics["metrics"]["total_cost"] == pytest.approx(0.5, rel=0.01)
        assert metrics["metrics"]["avg_latency"] == pytest.approx(1.5, rel=0.01)
        assert metrics["metrics"]["consecutive_failures"] == 0

    def test_get_goal_metrics_with_failures(self, scheduler, mock_goal):
        """Test goal metrics with failed cycles."""
        scheduler.register(mock_goal)

        # Simulate mix of success and failure
        cycles = [
            {"ts": time.time() - 100, "ok": True, "cost": 0.1, "latency": 1.0, "summary": "OK"},
            {"ts": time.time() - 80, "ok": False, "cost": 0.0, "latency": 0.0, "summary": "Failed"},
            {"ts": time.time() - 60, "ok": True, "cost": 0.1, "latency": 1.2, "summary": "OK"},
            {"ts": time.time() - 40, "ok": False, "cost": 0.0, "latency": 0.0, "summary": "Failed"},
            {"ts": time.time() - 20, "ok": True, "cost": 0.1, "latency": 1.1, "summary": "OK"},
        ]
        for cycle in cycles:
            scheduler._cycle_history["test_goal"].append(cycle)

        # Set failure count
        scheduler._failure_counts["test_goal"] = 0

        metrics = scheduler.get_goal_metrics("test_goal")

        assert metrics["metrics"]["success_rate"] == 60.0  # 3 success / 5 total
        assert metrics["metrics"]["total_cycles"] == 5
        assert metrics["metrics"]["consecutive_failures"] == 0

    def test_trend_analysis(self, scheduler, mock_goal):
        """Test trend analysis (recent vs earlier success rates)."""
        scheduler.register(mock_goal)

        # Earlier cycles: all successful
        for i in range(5):
            scheduler._cycle_history["test_goal"].append({
                "ts": time.time() - (200 - i*20),
                "ok": True,
                "cost": 0.1,
                "latency": 1.0,
                "summary": "OK",
            })

        # Recent cycles: all failed
        for i in range(5):
            scheduler._cycle_history["test_goal"].append({
                "ts": time.time() - (50 - i*10),
                "ok": False,
                "cost": 0.0,
                "latency": 0.0,
                "summary": "Failed",
            })

        metrics = scheduler.get_goal_metrics("test_goal")

        # Overall: 50%
        assert metrics["metrics"]["success_rate"] == 50.0
        # Recent 5: 0%
        assert metrics["metrics"]["recent_5_success_rate"] == 0.0
        # Trend should be down
        assert metrics["metrics"]["trend"] == "📉"

    def test_latency_metrics(self, scheduler, mock_goal):
        """Test latency min/max/avg calculations."""
        scheduler.register(mock_goal)

        cycles = [
            {"ts": time.time() - 100, "ok": True, "cost": 0.1, "latency": 1.0, "summary": "OK"},
            {"ts": time.time() - 80, "ok": True, "cost": 0.1, "latency": 2.5, "summary": "OK"},
            {"ts": time.time() - 60, "ok": True, "cost": 0.1, "latency": 0.5, "summary": "OK"},
            {"ts": time.time() - 40, "ok": True, "cost": 0.1, "latency": 1.5, "summary": "OK"},
        ]
        for cycle in cycles:
            scheduler._cycle_history["test_goal"].append(cycle)

        metrics = scheduler.get_goal_metrics("test_goal")

        assert metrics["metrics"]["min_latency"] == 0.5
        assert metrics["metrics"]["max_latency"] == 2.5
        assert metrics["metrics"]["avg_latency"] == pytest.approx(1.375, rel=0.01)

    def test_last_run_metadata(self, scheduler, mock_goal):
        """Test last run metadata (timestamp, age, summary)."""
        scheduler.register(mock_goal)

        now = time.time()
        scheduler._cycle_history["test_goal"].append({
            "ts": now - 30,  # 30 seconds ago
            "ok": True,
            "cost": 0.05,
            "latency": 1.2,
            "summary": "Recent success",
        })

        metrics = scheduler.get_goal_metrics("test_goal")

        assert metrics["last_run"]["success"] == True
        assert metrics["last_run"]["cost"] == 0.05
        assert metrics["last_run"]["latency"] == 1.2
        assert metrics["last_run"]["summary"] == "Recent success"
        assert 25 < metrics["last_run"]["age_seconds"] < 35  # ~30s

    def test_multi_goal_health_aggregation(self, scheduler):
        """Test health dashboard aggregating metrics from multiple goals."""
        # Create 3 goals with different metrics
        for i in range(3):
            goal = MagicMock()
            goal.name = f"goal_{i}"
            goal.interval_seconds = 60
            goal.channels = [NotificationChannel.TELEGRAM]
            goal.get_status = MagicMock(return_value=GoalStatus.RUNNING)
            goal.serialize_state = MagicMock(return_value={})
            goal.budget = MagicMock()
            goal.budget.spent_today_usd = 0.2 * (i + 1)
            goal.budget.max_daily_usd = 1.0
            goal.budget.exhausted = False
            goal.budget.reset_if_new_day = MagicMock()

            scheduler.register(goal)

            # Add cycles: each goal has progressively better success rate
            success_count = i + 1  # 1, 2, 3 successes out of 3
            for j in range(3):
                scheduler._cycle_history[goal.name].append({
                    "ts": time.time() - (100 - j*20),
                    "ok": j < success_count,
                    "cost": 0.1,
                    "latency": 1.0,
                    "summary": "Test",
                })

        dashboard = scheduler.get_health_dashboard()

        assert dashboard["summary"]["total_goals"] == 3
        # Average success rate: (33.3% + 66.7% + 100%) / 3 ≈ 66.7%
        assert 65 < dashboard["summary"]["avg_success_rate"] < 68
        # Total cost: 0.2 + 0.4 + 0.6 = 1.2
        assert dashboard["summary"]["total_cost_today"] == pytest.approx(1.2, rel=0.01)

    def test_cycle_history_maxlen(self, scheduler, mock_goal):
        """Test that cycle history is limited to maxlen=20."""
        scheduler.register(mock_goal)

        # Add 30 cycles
        for i in range(30):
            scheduler._cycle_history["test_goal"].append({
                "ts": time.time() - (300 - i*10),
                "ok": True,
                "cost": 0.01,
                "latency": 1.0,
                "summary": f"Cycle {i}",
            })

        metrics = scheduler.get_goal_metrics("test_goal")

        # Should only have 20 (deque maxlen)
        assert metrics["metrics"]["total_cycles"] == 20
        # History in returned metrics should be last 10
        assert len(metrics["history"]) == 10

    def test_global_budget_tracking(self, scheduler, mock_goal):
        """Test global budget spending aggregation."""
        scheduler.register(mock_goal)

        # Simulate global spending
        scheduler._global_spent_today = 1.5

        dashboard = scheduler.get_health_dashboard()

        assert dashboard["global_budget"]["spent"] == 1.5
        assert dashboard["global_budget"]["limit"] == 2.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
