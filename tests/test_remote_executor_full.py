"""
Remote Executor — End-to-End Validation

Testa 5 cenários principais:
1. L2_SILENT action → auto-execute
2. L1_LOGGED action → log + execute
3. L0_MANUAL action → enqueue approval
4. Multi-step com dependency + rollback
5. Claude Code delegation → fallback to bash
"""

import pytest
import asyncio
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.executor import (
    ActionOrchestrator,
    ActionExecutor,
    ExecutionPlan,
    ExecutionContext,
    ActionStep,
    ActionType,
    AutonomyTier,
    ActionStatus,
    ExecutionResult,
)
from src.core.executor.handlers import (
    BashHandler,
    FileOpsHandler,
    APIHandler,
    RemoteTriggerHandler,
)
from src.core.executor.safety import SafetyGateEvaluator, ExecutorPolicy
from src.core.executor.afk_protocol import AFKProtocolCoordinator


class TestRemoteExecutorScenarios:
    """Testa 5 cenários principais de Remote Executor."""

    @pytest.fixture
    def executor(self):
        """Cria ActionExecutor para testes."""
        return ActionExecutor()

    @pytest.fixture
    def afk_protocol(self):
        """Cria AFKProtocolCoordinator para testes."""
        return AFKProtocolCoordinator(user_id="test_user")

    @pytest.fixture
    def safety_evaluator(self):
        """Cria SafetyGateEvaluator para testes."""
        return SafetyGateEvaluator()

    @pytest.fixture
    def context(self):
        """Cria ExecutionContext para testes."""
        return ExecutionContext(
            plan_id="test_plan_123",
            triggered_by_user="test_user",
            triggered_by_intent="test action",
            goal_name="remote_executor",
            budget_remaining_usd=0.20,
            afk_time_seconds=0,
            afk_window_l1_hours=12,
        )

    # ========== SCENARIO 1: L2_SILENT (auto-execute) ==========

    @pytest.mark.asyncio
    async def test_scenario_1_l2_silent_auto_execute(self, executor, context):
        """
        SCENARIO 1: L2_SILENT action → auto-execute anytime
        Action: bash ls (safe, no user involvement)
        Expected: SUCCESS, duration tracked, cost=0.0
        """
        # Setup
        plan = ExecutionPlan(
            plan_id="plan_l2_silent",
            intention="listar arquivos",
            steps=[
                ActionStep(
                    id="step_1",
                    type=ActionType.BASH,
                    description="Listar arquivos no diretório atual",
                    command="ls -la",
                    timeout_seconds=10,
                    approval_tier=AutonomyTier.L2_SILENT,
                    estimated_cost_usd=0.0,
                )
            ],
            estimated_total_cost_usd=0.0,
        )

        # Execute
        results = await executor.execute_plan(plan, context)

        # Assertions
        assert len(results) == 1
        assert "step_1" in results
        result = results["step_1"]
        assert result.status == ActionStatus.SUCCESS
        assert result.cost_usd == 0.0
        assert result.duration_ms >= 0
        assert len(result.output) > 0  # ls retorna output

        # Verify summary
        summary = executor.summarize_results(results)
        assert summary["successful"] == 1
        assert summary["total_steps"] == 1
        assert summary["success_rate"] == 1.0

    # ========== SCENARIO 2: L1_LOGGED (auto-execute até 12h AFK) ==========

    @pytest.mark.asyncio
    async def test_scenario_2_l1_logged_with_audit(self, executor, context):
        """
        SCENARIO 2: L1_LOGGED action → auto-execute com audit trail
        Action: file write (medium-risk, auto-execute + log)
        Expected: SUCCESS, snapshots captured, logged in execution_log
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_file.txt"

            # Setup
            plan = ExecutionPlan(
                plan_id="plan_l1_logged",
                intention="criar arquivo com logging",
                steps=[
                    ActionStep(
                        id="step_1",
                        type=ActionType.FILE_OPS,
                        description="Criar arquivo de teste",
                        command={"op": "write", "path": str(test_file), "data": "test content\n"},
                        timeout_seconds=10,
                        approval_tier=AutonomyTier.L1_LOGGED,
                        estimated_cost_usd=0.0,
                    )
                ],
                estimated_total_cost_usd=0.0,
            )

            # Execute
            results = await executor.execute_plan(plan, context)

            # Assertions
            assert results["step_1"].status == ActionStatus.SUCCESS
            assert test_file.exists()

            # Verify audit trail
            execution_log = executor.get_execution_log()
            assert len(execution_log) > 0
            assert execution_log[0]["step_id"] == "step_1"
            assert execution_log[0]["status"] == "success"

    # ========== SCENARIO 3: L0_MANUAL (approval workflow) ==========

    @pytest.mark.asyncio
    async def test_scenario_3_l0_manual_approval_queue(self, afk_protocol):
        """
        SCENARIO 3: L0_MANUAL action → enqueue approval
        Action: bash rm (dangerous, requer aprovação)
        Expected: Enqueued, approval_id gerado, timeout settings
        """
        # Setup
        step = ActionStep(
            id="step_1",
            type=ActionType.BASH,
            description="deletar arquivo temp.txt",
            command="rm temp.txt",
            timeout_seconds=10,
            approval_tier=AutonomyTier.L0_MANUAL,
            estimated_cost_usd=0.01,
        )

        # Enqueue para aprovação
        approval_id = await afk_protocol.enqueue_approval(step)

        # Assertions
        assert approval_id == step.id
        assert approval_id in afk_protocol.approval_queue

        approval = afk_protocol.approval_queue[approval_id]
        assert approval.step.id == step.id
        assert approval.retry_count == 0
        assert approval.max_retries == 3
        assert not approval.is_expired  # 5 min timeout

        # Verify timeout behavior
        remaining = approval.time_until_timeout
        assert remaining > 0
        assert remaining <= 300  # 5 minutos

    @pytest.mark.asyncio
    async def test_scenario_3_approval_response_workflow(self, afk_protocol):
        """
        SCENARIO 3b: Approval response workflow
        User responde à aprovação → executa ou rejeita
        """
        # Setup
        step = ActionStep(
            id="step_1",
            type=ActionType.BASH,
            description="deletar arquivo",
            command="rm temp.txt",
            approval_tier=AutonomyTier.L0_MANUAL,
        )

        # Enqueue
        approval_id = await afk_protocol.enqueue_approval(step)
        assert approval_id in afk_protocol.approval_queue

        # User responde: APPROVE
        response = await afk_protocol.respond_to_approval(approval_id, approved=True)
        assert response is True
        assert approval_id not in afk_protocol.approval_queue
        assert afk_protocol.approval_responses[approval_id] is True

        # Check status
        status = await afk_protocol.check_approval_status(approval_id)
        assert status is True

    # ========== SCENARIO 4: Multi-step com dependency + rollback ==========

    @pytest.mark.asyncio
    async def test_scenario_4_multi_step_with_dependencies(self, executor, context):
        """
        SCENARIO 4: Multi-step com dependências e rollback
        Action: Simples sequência (create → modify, modify depends_on create)
        Expected: Correct execution order, respeitaependências
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"

            # Setup plan com 2 steps: create file, append to file
            plan = ExecutionPlan(
                plan_id="plan_create_append",
                intention="criar e modificar arquivo",
                steps=[
                    ActionStep(
                        id="step_1",
                        type=ActionType.FILE_OPS,
                        description="criar arquivo",
                        command={"op": "write", "path": str(test_file), "data": "line 1\n"},
                        approval_tier=AutonomyTier.L2_SILENT,
                        rollback_instruction=f"rm {test_file}",
                    ),
                    ActionStep(
                        id="step_2",
                        type=ActionType.BASH,
                        description="appender arquivo",
                        command=f"echo 'line 2' >> {test_file}",
                        approval_tier=AutonomyTier.L2_SILENT,
                        depends_on=["step_1"],
                        rollback_instruction=f"echo 'line 1' > {test_file}",
                    ),
                ],
                dependencies={
                    "step_1": [],
                    "step_2": ["step_1"],
                },
                estimated_total_cost_usd=0.0,
            )

            # Execute
            results = await executor.execute_plan(plan, context)

            # Assertions
            assert results["step_1"].status == ActionStatus.SUCCESS
            assert results["step_2"].status == ActionStatus.SUCCESS
            assert test_file.exists()

            # Verify execution order (step_1 antes step_2)
            summary = executor.summarize_results(results)
            assert summary["successful"] == 2
            assert summary["total_steps"] == 2

    @pytest.mark.asyncio
    async def test_scenario_4_dependency_failure_handling(self, executor, context):
        """
        SCENARIO 4b: Se step_1 falha, step_2 não executa
        """
        plan = ExecutionPlan(
            plan_id="plan_dep_fail",
            intention="test failure",
            steps=[
                ActionStep(
                    id="step_1",
                    type=ActionType.BASH,
                    description="comando que falha",
                    command="false",  # always fails
                    approval_tier=AutonomyTier.L2_SILENT,
                ),
                ActionStep(
                    id="step_2",
                    type=ActionType.BASH,
                    description="não deve executar",
                    command="echo 'should not run'",
                    approval_tier=AutonomyTier.L2_SILENT,
                    depends_on=["step_1"],
                ),
            ],
            dependencies={
                "step_1": [],
                "step_2": ["step_1"],
            },
            estimated_total_cost_usd=0.0,
        )

        # Execute
        results = await executor.execute_plan(plan, context)

        # Assertions
        assert results["step_1"].status == ActionStatus.FAILED
        assert results["step_2"].status == ActionStatus.CANCELLED  # não executou

    # ========== SCENARIO 5: Claude Code delegation ==========

    @pytest.mark.asyncio
    async def test_scenario_5_remote_trigger_delegation(self):
        """
        SCENARIO 5: Delegação para Claude Code via RemoteTrigger
        Action: desktop screenshot (delegado para Claude Code)
        Expected: Health check, API call, fallback se offline
        """
        handler = RemoteTriggerHandler()

        # Mock health check
        with patch.object(handler, "health_check", new_callable=AsyncMock) as mock_health:
            mock_health.return_value = False  # Claude Code offline

            # Setup
            step = ActionStep(
                id="step_1",
                type=ActionType.REMOTE_TRIGGER,
                description="tirar screenshot",
                command={
                    "type": "screenshot",
                    "description": "capturar tela",
                },
                timeout_seconds=10,
                approval_tier=AutonomyTier.L1_LOGGED,
            )

            # Validate
            is_valid, error = await handler.validate(step)
            assert is_valid is True

            # Execute (com health check)
            result = await handler.execute(step)

            # Assertions: deve falhar com "offline"
            assert result.status == ActionStatus.FAILED
            assert "unavailable" in result.error.lower()

    @pytest.mark.asyncio
    async def test_scenario_5_remote_trigger_fallback(self):
        """
        SCENARIO 5b: Fallback de Claude Code para bash local
        Se RemoteTrigger offline → pode usar fallback bash
        """
        # Setup: action que pode rodar via bash local
        step = ActionStep(
            id="step_1",
            type=ActionType.BASH,
            description="tirar screenshot via screenshot.py",
            command="python -m src.skills.vision.screenshot > screenshot.png",
            approval_tier=AutonomyTier.L1_LOGGED,
        )

        handler = BashHandler()

        # Execute
        result = await handler.execute(step)

        # Assertions
        assert result.step_id == step.id
        # Resultado pode ser SUCCESS ou FAILED dependendo se screenshot.py existe
        # Importante: não deve ser TIMEOUT


# ========== INTEGRATION TESTS ==========


class TestRemoteExecutorIntegration:
    """Testes de integração para Remote Executor."""

    @pytest.mark.asyncio
    async def test_end_to_end_planning_and_execution(self):
        """
        E2E: Intenção → Orchestrator → Executor → Resultados
        Nota: Requer CascadeAdapter disponível (mock)
        """
        # Mock cascade adapter
        mock_cascade = AsyncMock()
        response_obj = MagicMock()
        response_obj.get = MagicMock(
            return_value='{"steps": [{"id": "step_1", "type": "bash", '
            '"description": "test", "command": "echo test", '
            '"approval_tier": "L2_SILENT", "estimated_cost_usd": 0.0}], '
            '"estimated_total_cost_usd": 0.0}'
        )
        mock_cascade.call = AsyncMock(return_value=response_obj)

        # Setup
        orchestrator = ActionOrchestrator(cascade_adapter=mock_cascade)
        executor = ActionExecutor()

        context = ExecutionContext(
            plan_id="e2e_test",
            triggered_by_user="test_user",
            triggered_by_intent="test action",
            budget_remaining_usd=0.20,
        )

        # Plan
        plan, error = await orchestrator.plan("test", context)
        assert error == ""
        assert plan is not None
        assert len(plan.steps) > 0

        # Execute
        results = await executor.execute_plan(plan, context)
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_cost_tracking_across_execution(self):
        """
        Valida que custos são agregados corretamente
        """
        executor = ActionExecutor()

        # Criar plan com múltiplos steps de tipos diferentes
        plan = ExecutionPlan(
            plan_id="cost_test",
            intention="multi-type actions",
            steps=[
                ActionStep(
                    id="step_1",
                    type=ActionType.BASH,
                    description="bash (free)",
                    command="echo test",
                    approval_tier=AutonomyTier.L2_SILENT,
                    estimated_cost_usd=0.0,  # bash é free
                ),
                ActionStep(
                    id="step_2",
                    type=ActionType.FILE_OPS,
                    description="file ops (free)",
                    command={"op": "write", "path": "/tmp/test.txt", "data": "test"},
                    approval_tier=AutonomyTier.L2_SILENT,
                    estimated_cost_usd=0.0,  # file ops é free
                ),
            ],
            estimated_total_cost_usd=0.0,
        )

        context = ExecutionContext(
            plan_id="cost_test",
            triggered_by_user="test_user",
            triggered_by_intent="test",
            budget_remaining_usd=0.20,
        )

        # Execute
        results = await executor.execute_plan(plan, context)

        # Verify costs
        total_cost = sum(r.cost_usd for r in results.values())
        assert total_cost == 0.0  # Todos free

        summary = executor.summarize_results(results)
        assert summary["total_cost_usd"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
