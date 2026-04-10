"""
Remote Executor — Testes de Integração E2E

Valida:
1. Goal discovery e auto-registro
2. Callbacks de aprovação Telegram
3. Integração com Sprint11Tracker
4. Fluxo completo: plan → enqueue → approve → execute
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from prometheus_client import REGISTRY

from src.core.pipeline import SeekerPipeline
from src.core.goals.registry import discover_goals
from src.core.goals.scheduler import GoalScheduler, GoalNotifier
from src.skills.remote_executor.goal import RemoteExecutorGoal
from src.core.executor import ExecutionPlan, ExecutionContext, ActionStep, ActionType, AutonomyTier
from src.core.metrics import Sprint11Tracker


class TestRemoteExecutorE2E:
    """Testes E2E da integração completa"""

    @pytest.fixture(autouse=True)
    def reset_prometheus_registry(self):
        """Reset Prometheus registry antes de cada teste"""
        # Limpar collectors antigos
        collectors_to_remove = list(REGISTRY._collector_to_names.keys())
        for collector in collectors_to_remove:
            try:
                REGISTRY.unregister(collector)
            except Exception:
                pass
        yield
        # Limpar após o teste também
        collectors_to_remove = list(REGISTRY._collector_to_names.keys())
        for collector in collectors_to_remove:
            try:
                REGISTRY.unregister(collector)
            except Exception:
                pass

    @pytest.fixture
    def api_keys(self):
        """Mock API keys"""
        return {
            "gemini": "test_gemini_key",
            "groq": "test_groq_key",
            "deepseek": "test_deepseek_key",
            "nvidia": "test_nvidia_key",
        }

    @pytest.fixture
    async def pipeline(self, api_keys, tmp_path):
        """Inicializa pipeline com tracker"""
        pipeline = SeekerPipeline(api_keys, db_path=str(tmp_path / "memory.db"))
        await pipeline.init()
        pipeline.sprint11_tracker = Sprint11Tracker()
        return pipeline

    @pytest.mark.asyncio
    async def test_goal_discovery_includes_remote_executor(self, pipeline):
        """Valida que Remote Executor é descoberto automaticamente"""
        goals = discover_goals(pipeline, deny_list=set())

        goal_names = [g.name for g in goals]
        assert "remote_executor" in goal_names, f"Remote Executor não descoberto. Goals: {goal_names}"

        # Verificar propriedades do goal
        remote_executor = next(g for g in goals if g.name == "remote_executor")
        assert remote_executor.interval_seconds == 60
        assert remote_executor.channels  # Tem canais de notificação

    @pytest.mark.asyncio
    async def test_remote_executor_goal_initialization(self, pipeline):
        """Valida inicialização correta do goal"""
        goal = RemoteExecutorGoal(pipeline, notifier=None)

        assert goal.name == "remote_executor"
        assert goal.orchestrator is not None
        assert goal.executor is not None
        assert goal.afk_protocol is not None
        assert goal.tracker is not None

    @pytest.mark.asyncio
    async def test_metrics_tracking_on_plan_creation(self, pipeline):
        """Valida registro de métricas quando plano é criado"""
        goal = RemoteExecutorGoal(pipeline)
        initial_plans = goal.tracker.remote_executor.total_plans

        # Mock orchestrator
        mock_plan = ExecutionPlan(
            plan_id="test_plan",
            intention="test action",
            steps=[],
            estimated_total_cost_usd=0.0,
        )
        goal.orchestrator.plan = AsyncMock(return_value=(mock_plan, ""))

        # Criar plano
        plan, error = await goal.plan_action("test action", user_id="test_user")

        # Verificar que métrica foi registrada
        assert goal.tracker.remote_executor.total_plans == initial_plans + 1

    @pytest.mark.asyncio
    async def test_metrics_tracking_on_execution(self, pipeline):
        """Valida registro de métricas na execução"""
        goal = RemoteExecutorGoal(pipeline)

        # Registrar execução manualmente
        goal.tracker.record_remote_executor_execution(
            success=True,
            execution_status="SUCCESS",
            latency_ms=250.5,
            cost_usd=0.05,
        )

        goal.tracker.record_remote_executor_autonomy_tier("L2_SILENT")

        # Verificar métricas
        stats = goal.tracker.remote_executor.get_stats()
        assert stats["successful"] == 1
        assert stats["l2_executed"] == 1
        assert stats["total_cost_usd"] == "$0.0500"

    @pytest.mark.asyncio
    async def test_metrics_tracking_on_approval(self, pipeline):
        """Valida registro de métricas na aprovação"""
        goal = RemoteExecutorGoal(pipeline)

        # Registrar aprovação
        goal.tracker.record_remote_executor_approval(approved=True)
        goal.tracker.record_remote_executor_approval(approved=True)
        goal.tracker.record_remote_executor_approval(approved=False)

        # Verificar métricas
        stats = goal.tracker.remote_executor.get_stats()
        assert stats["l0_manual_approved"] == 2
        assert stats["l0_manual_rejected"] == 1
        assert stats["l0_approval_rate"] == "66.7%"

    @pytest.mark.asyncio
    async def test_approval_notification_format(self, pipeline):
        """Valida formatação de notificação com buttons"""
        from src.skills.remote_executor.prompts import get_approval_notification

        text, buttons = get_approval_notification(
            action_id="step_1",
            description="Delete old logs",
            timeout_seconds=300,
            estimated_cost=0.01,
        )

        # Verificar formato
        assert "step_1" in text
        assert "Delete old logs" in text
        assert "300" in text
        assert "$0.01" in text

        # Verificar buttons
        assert len(buttons) == 1
        assert len(buttons[0]) == 2  # ✅ e ❌

        approve_btn = buttons[0][0]
        reject_btn = buttons[0][1]

        assert approve_btn["text"] == "✅ Aprovar"
        assert approve_btn["callback_data"] == "exec_approve:step_1"
        assert reject_btn["text"] == "❌ Rejeitar"
        assert reject_btn["callback_data"] == "exec_reject:step_1"

    @pytest.mark.asyncio
    async def test_sprint11_tracker_remote_executor_report(self, pipeline):
        """Valida formato de relatório no Telegram"""
        tracker = pipeline.sprint11_tracker

        # Simular atividade do Remote Executor
        tracker.record_remote_executor_plan()
        tracker.record_remote_executor_plan()

        tracker.record_remote_executor_execution(
            success=True,
            execution_status="SUCCESS",
            latency_ms=150.0,
            cost_usd=0.02,
        )

        tracker.record_remote_executor_execution(
            success=False,
            execution_status="FAILED",
            latency_ms=500.0,
            cost_usd=0.01,
        )

        tracker.record_remote_executor_autonomy_tier("L2_SILENT")
        tracker.record_remote_executor_autonomy_tier("L1_LOGGED")

        tracker.record_remote_executor_approval(approved=True)
        tracker.record_remote_executor_approval(approved=True)

        # Gerar relatório Telegram
        report = tracker.format_for_telegram()

        # Verificar conteúdo
        assert "🤖 REMOTE EXECUTOR:" in report
        assert "Plans: 2" in report
        assert "Executed: 2" in report
        assert "L0 Manual:" in report
        assert "✅ 2" in report
        assert "Cost: $0.0300" in report

    @pytest.mark.asyncio
    async def test_full_report_structure(self, pipeline):
        """Valida estrutura do relatório completo"""
        tracker = pipeline.sprint11_tracker

        # Adicionar dados
        tracker.record_remote_executor_plan()
        tracker.record_remote_executor_execution(
            success=True,
            execution_status="SUCCESS",
            latency_ms=200.0,
            cost_usd=0.05,
        )

        # Gerar relatório
        report = tracker.get_full_report()

        assert "remote_executor" in report
        assert "timestamp" in report
        assert "uptime_seconds" in report

        re_stats = report["remote_executor"]
        assert re_stats["total_plans"] == 1
        assert re_stats["total_executed"] == 1
        assert re_stats["successful"] == 1

    @pytest.mark.asyncio
    async def test_goal_scheduler_includes_remote_executor(self, pipeline):
        """Valida que scheduler registra Remote Executor"""
        notifier = GoalNotifier(bot=None)
        scheduler = GoalScheduler(notifier)

        # Descobrir goals
        goals = discover_goals(pipeline, deny_list=set())
        for goal in goals:
            scheduler.register(goal)

        # Verificar que Remote Executor foi registrado
        assert "remote_executor" in scheduler._goals
        remote_executor = scheduler._goals["remote_executor"]
        assert isinstance(remote_executor, RemoteExecutorGoal)

    @pytest.mark.asyncio
    async def test_error_handling_in_plan_creation(self, pipeline):
        """Valida tratamento de erro em planeamento"""
        goal = RemoteExecutorGoal(pipeline)

        # Mock orchestrator falhar
        goal.orchestrator.plan = AsyncMock(return_value=(None, "Planning error"))

        plan, error = await goal.plan_action("invalid action", user_id="test_user")

        assert plan is None
        assert "Planning error" in error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
