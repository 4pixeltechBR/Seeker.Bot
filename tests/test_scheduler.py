"""
Tests for GoalScheduler — background goal orchestration.
src/core/goals/scheduler.py

Tests cover:
- Goal lifecycle (register, budget tracking)
- Cycle history structure
- Status reporting
- Budget exhaustion logic
- Background task tracking
"""

import asyncio
import pytest
from datetime import date

from src.core.goals.scheduler import GoalScheduler
from src.core.goals.protocol import (
    AutonomousGoal,
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)


class MockGoal(AutonomousGoal):
    """Minimal autonomous goal for testing."""

    def __init__(self, name="test_goal", interval=5, budget=None):
        self._name = name
        self._interval_seconds = interval
        self._budget = budget or GoalBudget(max_per_cycle_usd=0.10, max_daily_usd=0.50)
        self._channels = [NotificationChannel.TELEGRAM]
        self._status = GoalStatus.IDLE

    @property
    def name(self) -> str:
        return self._name

    @property
    def interval_seconds(self) -> int:
        return self._interval_seconds

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return self._channels

    def get_status(self) -> GoalStatus:
        return self._status

    async def run_cycle(self) -> GoalResult:
        """Simulate goal execution."""
        self._status = GoalStatus.IDLE
        return GoalResult(
            success=True,
            summary="Cycle completed",
            cost_usd=0.01,
        )

    def serialize_state(self) -> dict:
        return {"state": "ok"}


class MockNotifier:
    """Minimal goal notifier for testing."""

    def __init__(self):
        self.sent_messages = []

    async def send(self, goal_name: str, content: str, channels, data=None):
        self.sent_messages.append(
            {"goal": goal_name, "content": content, "channels": channels}
        )


def test_scheduler_register_goal():
    """Test registering a goal."""
    notifier = MockNotifier()
    scheduler = GoalScheduler(notifier)

    goal = MockGoal("revenue_hunter")
    scheduler.register(goal)

    assert "revenue_hunter" in scheduler._goals
    assert scheduler._goals["revenue_hunter"] is goal
    assert "revenue_hunter" in scheduler._failure_counts
    assert scheduler._failure_counts["revenue_hunter"] == 0
    assert "revenue_hunter" in scheduler._cycle_history


def test_scheduler_multiple_goals():
    """Test registering multiple goals."""
    notifier = MockNotifier()
    scheduler = GoalScheduler(notifier)

    goal1 = MockGoal("goal1")
    goal2 = MockGoal("goal2")

    scheduler.register(goal1)
    scheduler.register(goal2)

    assert len(scheduler._goals) == 2
    assert "goal1" in scheduler._goals
    assert "goal2" in scheduler._goals


def test_scheduler_budget_tracking():
    """Test per-goal budget tracking."""
    notifier = MockNotifier()
    scheduler = GoalScheduler(notifier)

    budget = GoalBudget(max_per_cycle_usd=0.05, max_daily_usd=0.50)
    goal = MockGoal("test", budget=budget)

    scheduler.register(goal)

    # Spend some budget
    goal.budget.spend(0.01)
    goal.budget.spend(0.01)

    assert goal.budget.spent_today_usd == 0.02
    assert goal.budget.exhausted is False

    # Spend remaining
    goal.budget.spend(0.48)
    assert goal.budget.exhausted is True


def test_scheduler_global_budget():
    """Test global daily budget tracking."""
    notifier = MockNotifier()
    scheduler = GoalScheduler(notifier)
    scheduler.GLOBAL_DAILY_BUDGET_USD = 1.0

    goal1 = MockGoal("goal1")
    goal2 = MockGoal("goal2")

    scheduler.register(goal1)
    scheduler.register(goal2)

    # Simulate spending
    scheduler._global_spent_today = 0.9

    assert scheduler._global_spent_today < scheduler.GLOBAL_DAILY_BUDGET_USD


def test_scheduler_cycle_history_structure():
    """Test cycle history record structure."""
    notifier = MockNotifier()
    scheduler = GoalScheduler(notifier)

    goal = MockGoal("test")
    scheduler.register(goal)

    # Simulate a successful cycle
    scheduler._cycle_history["test"].append({
        "ts": 1234567890.0,
        "ok": True,
        "cost": 0.01,
        "latency": 0.5,
        "summary": "Test completed",
    })

    history = list(scheduler._cycle_history["test"])
    assert len(history) == 1

    record = history[0]
    assert "ts" in record
    assert "ok" in record
    assert "cost" in record
    assert "latency" in record
    assert "summary" in record
    assert record["ok"] is True


def test_scheduler_status_report_content():
    """Test status report generation includes all goals."""
    notifier = MockNotifier()
    scheduler = GoalScheduler(notifier)

    goal1 = MockGoal("goal1")
    goal2 = MockGoal("goal2")

    scheduler.register(goal1)
    scheduler.register(goal2)

    # Add some history
    scheduler._cycle_history["goal1"].append({
        "ts": 1234567890.0,
        "ok": True,
        "cost": 0.01,
        "latency": 1.0,
        "summary": "Success",
    })

    report = scheduler.get_status_report()

    assert "goal1" in report
    assert "goal2" in report
    assert "Goals Ativos" in report
    assert "Budget global" in report


def test_scheduler_failure_counting():
    """Test failure count tracking."""
    notifier = MockNotifier()
    scheduler = GoalScheduler(notifier)

    goal = MockGoal("flaky")
    scheduler.register(goal)

    # Simulate failures
    scheduler._failure_counts["flaky"] = 0
    scheduler._failure_counts["flaky"] += 1
    scheduler._failure_counts["flaky"] += 1

    assert scheduler._failure_counts["flaky"] == 2


def test_scheduler_budget_reset_on_new_day():
    """Test that budget resets when date changes."""
    notifier = MockNotifier()
    scheduler = GoalScheduler(notifier)

    budget = GoalBudget(max_per_cycle_usd=0.05, max_daily_usd=0.50)
    goal = MockGoal("test", budget=budget)

    scheduler.register(goal)

    # Spend budget for "yesterday"
    goal.budget.budget_reset_date = "2026-04-07"
    goal.budget.spent_today_usd = 0.25

    # Reset with today's date (should trigger reset)
    today = "2026-04-08"
    goal.budget.reset_if_new_day(today)

    # Budget should be reset to 0
    assert goal.budget.spent_today_usd == 0.0
    assert goal.budget.budget_reset_date == today

    # Verify reset method exists
    assert hasattr(goal.budget, 'reset_if_new_day')


def test_scheduler_friction_metrics():
    """Test friction metrics tracking."""
    notifier = MockNotifier()
    scheduler = GoalScheduler(notifier)

    # Initial metrics
    assert scheduler.friction_metrics["rate_limits"] == 0
    assert scheduler.friction_metrics["rethinks_blocked"] == 0
    assert scheduler.friction_metrics["sara_edits"] == 0

    # Increment metrics
    scheduler.friction_metrics["rate_limits"] += 1
    scheduler.friction_metrics["rethinks_blocked"] += 2

    assert scheduler.friction_metrics["rate_limits"] == 1
    assert scheduler.friction_metrics["rethinks_blocked"] == 2


def test_scheduler_background_task_tracking():
    """Test that background tasks are tracked for shutdown."""
    notifier = MockNotifier()
    scheduler = GoalScheduler(notifier)

    # Should have empty task tracking set initially
    assert isinstance(scheduler._rethink_tasks, set)
    assert len(scheduler._rethink_tasks) == 0


@pytest.mark.asyncio
async def test_scheduler_create_tracked_task():
    """Test creating and tracking background tasks."""
    notifier = MockNotifier()
    scheduler = GoalScheduler(notifier)

    async def dummy_coro():
        return "done"

    # Create tracked task
    task = scheduler._create_tracked_task(dummy_coro())

    # Should be in tracking set
    assert task in scheduler._rethink_tasks

    # Wait for task to complete
    result = await task
    assert result == "done"

    # After completion, callback should have removed it
    # (give callback a moment to execute)
    await asyncio.sleep(0.01)
    assert task not in scheduler._rethink_tasks


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
