"""
Testes para Goal Manager Unificado (Sprint 7.2)
- Priority system (CRITICAL, HIGH, NORMAL, LOW)
- Preemption logic
- Coroutine pool limiting
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from src.core.goals.scheduler import GoalScheduler, GoalPriority
from src.core.goals.protocol import GoalResult, GoalStatus, NotificationChannel


class MockGoal:
    """Mock goal para testes — nao herda de AutonomousGoal"""
    def __init__(self, goal_name, priority=GoalPriority.NORMAL):
        self._name = goal_name
        self.interval_seconds = 60
        self.channels = []
        self.budget = MagicMock()
        self.budget.exhausted = False
        self.budget.reset_if_new_day = MagicMock()
        self.budget.spend = MagicMock()
        self.priority = priority
        self._status = GoalStatus.IDLE

    @property
    def name(self):
        return self._name

    async def run_cycle(self):
        """Simula execucao do goal"""
        await asyncio.sleep(0.01)
        return GoalResult(
            success=True,
            summary="Mock execution",
            notification=None,
            cost_usd=0.001
        )

    def get_status(self):
        return self._status


@pytest.fixture
def mock_notifier():
    """Mock do GoalNotifier"""
    notifier = MagicMock()
    notifier.send = AsyncMock()
    return notifier


@pytest.fixture
def scheduler(mock_notifier):
    """Cria scheduler para testes"""
    return GoalScheduler(mock_notifier)


class TestPrioritySystem:
    """Testa sistema de prioridades"""

    def test_register_with_priority(self, scheduler):
        """Registra goal com prioridade especifica"""
        goal = MockGoal("important", priority=GoalPriority.HIGH)
        scheduler.register(goal, priority=GoalPriority.HIGH)

        assert scheduler._goal_priorities["important"] == GoalPriority.HIGH

    def test_default_priority_is_normal(self, scheduler):
        """Priority padrao eh NORMAL"""
        goal = MockGoal("basic")
        scheduler.register(goal)

        assert scheduler._goal_priorities["basic"] == GoalPriority.NORMAL

    def test_priority_levels_ordering(self):
        """Testa ordem de prioridades"""
        assert GoalPriority.CRITICAL.value < GoalPriority.HIGH.value
        assert GoalPriority.HIGH.value < GoalPriority.NORMAL.value
        assert GoalPriority.NORMAL.value < GoalPriority.LOW.value


class TestPreemption:
    """Testa preemption logic"""

    def test_critical_goal_pauses_normal(self, scheduler):
        """Goal CRITICAL pausa goals NORMAL/LOW"""
        critical = MockGoal("alert", priority=GoalPriority.CRITICAL)
        normal = MockGoal("routine", priority=GoalPriority.NORMAL)

        scheduler.register(critical, GoalPriority.CRITICAL)
        scheduler.register(normal, GoalPriority.NORMAL)

        # Simula CRITICAL em execucao
        scheduler._running_goals.add("alert")

        # NORMAL nao deve executar
        assert not scheduler._should_execute_goal("routine")

    def test_high_priority_not_preempted_by_normal(self, scheduler):
        """Goal HIGH nao eh pausado por NORMAL"""
        high = MockGoal("important", priority=GoalPriority.HIGH)
        normal = MockGoal("routine", priority=GoalPriority.NORMAL)

        scheduler.register(high, GoalPriority.HIGH)
        scheduler.register(normal, GoalPriority.NORMAL)

        # HIGH deve executar mesmo com NORMAL rodando
        scheduler._running_goals.add("routine")
        assert scheduler._should_execute_goal("important")

    def test_pause_tracking(self, scheduler):
        """Goals pausados sao rastreados em _paused_by_preemption"""
        critical = MockGoal("alert", priority=GoalPriority.CRITICAL)
        normal = MockGoal("routine", priority=GoalPriority.NORMAL)

        scheduler.register(critical, GoalPriority.CRITICAL)
        scheduler.register(normal, GoalPriority.NORMAL)

        # Simula preemption
        scheduler._running_goals.add("alert")
        scheduler._should_execute_goal("routine")

        assert "routine" in scheduler._paused_by_preemption


class TestPooling:
    """Testa coroutine pool limiting"""

    def test_pool_semaphore_initialized(self, scheduler):
        """Pool semaphore eh inicializado com MAX_CONCURRENT_GOALS"""
        assert scheduler._pool_semaphore._value == scheduler.MAX_CONCURRENT_GOALS
        assert scheduler.MAX_CONCURRENT_GOALS == 3

    def test_running_goals_tracking(self, scheduler):
        """_running_goals rastreia goals em execucao"""
        scheduler._running_goals.add("goal1")
        scheduler._running_goals.add("goal2")

        assert len(scheduler._running_goals) == 2
        assert "goal1" in scheduler._running_goals


class TestSchedulerIntegration:
    """Testa integracao de prioridades + preemption + pooling"""

    def test_critical_has_higher_priority(self, scheduler):
        """Goals CRITICAL tem valor de prioridade menor (executado primeiro)"""
        critical = MockGoal("alert", GoalPriority.CRITICAL)
        normal = MockGoal("routine", GoalPriority.NORMAL)

        scheduler.register(critical, GoalPriority.CRITICAL)
        scheduler.register(normal, GoalPriority.NORMAL)

        # Ordena por prioridade
        sorted_goals = sorted(
            scheduler._goal_priorities.items(),
            key=lambda x: x[1].value
        )

        assert sorted_goals[0][0] == "alert"  # CRITICAL primeiro (0 < 2)
        assert sorted_goals[1][0] == "routine"

    def test_multiple_priority_levels(self, scheduler):
        """Multiplos niveis de prioridade sao ordenados corretamente"""
        critical = MockGoal("c", GoalPriority.CRITICAL)
        high = MockGoal("h", GoalPriority.HIGH)
        normal = MockGoal("n", GoalPriority.NORMAL)
        low = MockGoal("l", GoalPriority.LOW)

        scheduler.register(critical, GoalPriority.CRITICAL)
        scheduler.register(high, GoalPriority.HIGH)
        scheduler.register(normal, GoalPriority.NORMAL)
        scheduler.register(low, GoalPriority.LOW)

        sorted_goals = sorted(
            scheduler._goal_priorities.items(),
            key=lambda x: x[1].value
        )

        names = [name for name, _ in sorted_goals]
        assert names == ["c", "h", "n", "l"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
