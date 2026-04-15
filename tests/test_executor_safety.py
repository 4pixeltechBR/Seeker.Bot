"""
Tests para SafetyGate — Validação de Segurança e Conformidade

Valida:
1. Whitelist enforcement (bash commands)
2. Approval tier classification
3. Budget limits (per-action, per-cycle, per-day)
4. AFK window enforcement
5. Policy violations
"""

import pytest
from datetime import datetime, timedelta

from src.core.executor.models import (
    ActionStep,
    ActionType,
    ApprovalTier,
    SafetyGateDecision,
)
from src.core.executor.safety import SafetyGateEvaluator, ExecutorPolicy
from src.core.executor.afk_protocol import AFKProtocol, UserStatus


@pytest.fixture
def safety_evaluator():
    """Fixture: SafetyGateEvaluator instanciado."""
    return SafetyGateEvaluator()


@pytest.fixture
def executor_policy():
    """Fixture: ExecutorPolicy com defaults."""
    return ExecutorPolicy()


class TestBashWhitelist:
    """Testes para bash command whitelist."""

    @pytest.mark.asyncio
    async def test_bash_safe_command_l2_silent(self, safety_evaluator):
        """L2_SILENT: 'ls' deve ser aprovado automaticamente."""
        step = ActionStep(
            id="test_ls",
            type=ActionType.BASH,
            command="ls -la /home",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L2_SILENT,
            estimated_cost_usd=0.0,
        )

        decision = await safety_evaluator.evaluate(step)

        assert decision.approved is True
        assert decision.approval_tier == ApprovalTier.L2_SILENT

    @pytest.mark.asyncio
    async def test_bash_medium_command_l1_logged(self, safety_evaluator):
        """L1_LOGGED: 'mkdir' deve ser aprovado com logging."""
        step = ActionStep(
            id="test_mkdir",
            type=ActionType.BASH,
            command="mkdir -p /tmp/test_dir",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L1_LOGGED,
            estimated_cost_usd=0.0,
        )

        decision = await safety_evaluator.evaluate(step)

        assert decision.approved is True
        assert decision.approval_tier == ApprovalTier.L1_LOGGED

    @pytest.mark.asyncio
    async def test_bash_dangerous_command_l0_manual(self, safety_evaluator):
        """L0_MANUAL: 'rm' deve requerer aprovação manual."""
        step = ActionStep(
            id="test_rm",
            type=ActionType.BASH,
            command="rm -rf /some/path",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L0_MANUAL,
            estimated_cost_usd=0.01,
        )

        decision = await safety_evaluator.evaluate(step)

        # Não temos approval, então deve ser negado (ou pendente)
        assert decision.approval_tier == ApprovalTier.L0_MANUAL

    @pytest.mark.asyncio
    async def test_bash_unknown_command_l1(self, safety_evaluator):
        """Comando desconhecido: deve ser escalado para L1_LOGGED."""
        step = ActionStep(
            id="test_unknown",
            type=ActionType.BASH,
            command="custom_script.sh --flag",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L1_LOGGED,
            estimated_cost_usd=0.0,
        )

        decision = await safety_evaluator.evaluate(step)

        # Comando desconhecido deve ser tratado como L1+
        assert decision.approved is True or decision.approval_tier == ApprovalTier.L1_LOGGED


class TestBudgetEnforcement:
    """Testes para limites de orçamento."""

    @pytest.mark.asyncio
    async def test_per_action_budget_limit(self, safety_evaluator):
        """Ação com custo > $0.20 deve ser rejeitada."""
        step = ActionStep(
            id="expensive_action",
            type=ActionType.BASH,
            command="expensive_operation",
            timeout_seconds=60,
            approval_tier=ApprovalTier.L2_SILENT,
            estimated_cost_usd=0.30,  # Acima do limit de $0.20/ação
        )

        decision = await safety_evaluator.evaluate(step)

        # Deve ser rejeitado por orçamento
        assert decision.approved is False
        assert "budget" in decision.reason.lower() or "cost" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_per_action_within_budget(self, safety_evaluator):
        """Ação com custo <= $0.20 deve ser aprovada (se não houver outras violações)."""
        step = ActionStep(
            id="cheap_action",
            type=ActionType.BASH,
            command="ls",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L2_SILENT,
            estimated_cost_usd=0.05,  # Dentro do limit
        )

        decision = await safety_evaluator.evaluate(step)

        assert decision.approved is True


class TestAFKWindowEnforcement:
    """Testes para AFK window enforcement."""

    @pytest.mark.asyncio
    async def test_l2_silent_no_afk_window_limit(self):
        """L2_SILENT não tem limite de AFK window (24h)."""
        afk = AFKProtocol(user_id="test_user")
        afk.update_status(UserStatus.SLEEP)

        # Simular que usuário está offline por 20h
        afk._last_status_change = datetime.utcnow() - timedelta(hours=20)

        # L2_SILENT deve ser permitido mesmo com 20h offline
        allowed = afk.is_action_allowed(ApprovalTier.L2_SILENT)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_l1_logged_afk_window_6h(self):
        """L1_LOGGED permite apenas 6h de offline."""
        afk = AFKProtocol(user_id="test_user")
        afk.update_status(UserStatus.AWAY)

        # Simular que usuário está offline por 5h (dentro da janela)
        afk._last_status_change = datetime.utcnow() - timedelta(hours=5)

        allowed = afk.is_action_allowed(ApprovalTier.L1_LOGGED)
        assert allowed is True

        # Agora simular 7h offline (fora da janela)
        afk._last_status_change = datetime.utcnow() - timedelta(hours=7)

        allowed = afk.is_action_allowed(ApprovalTier.L1_LOGGED)
        assert allowed is False  # Excedeu 6h

    @pytest.mark.asyncio
    async def test_l0_manual_afk_window_5m(self):
        """L0_MANUAL permite apenas 5 min de offline."""
        afk = AFKProtocol(user_id="test_user")
        afk.update_status(UserStatus.IDLE)

        # Simular que usuário está offline por 3m (dentro da janela)
        afk._last_status_change = datetime.utcnow() - timedelta(minutes=3)

        allowed = afk.is_action_allowed(ApprovalTier.L0_MANUAL)
        assert allowed is True

        # Agora simular 10m offline (fora da janela)
        afk._last_status_change = datetime.utcnow() - timedelta(minutes=10)

        allowed = afk.is_action_allowed(ApprovalTier.L0_MANUAL)
        assert allowed is False  # Excedeu 5m


class TestPolicyViolations:
    """Testes para detecção de policy violations."""

    @pytest.mark.asyncio
    async def test_injection_attempt_in_bash(self, safety_evaluator):
        """Tentativa de bash injection deve ser detectada."""
        step = ActionStep(
            id="injection_test",
            type=ActionType.BASH,
            command="ls; rm -rf /",  # Injection attempt
            timeout_seconds=10,
            approval_tier=ApprovalTier.L2_SILENT,
            estimated_cost_usd=0.0,
        )

        decision = await safety_evaluator.evaluate(step)

        # Deve ser rejeitado por violação de policy
        assert decision.approved is False or decision.approval_tier != ApprovalTier.L2_SILENT

    @pytest.mark.asyncio
    async def test_sensitive_file_access(self, safety_evaluator):
        """Acesso a arquivos sensíveis deve ser escalado."""
        step = ActionStep(
            id="sensitive_access",
            type=ActionType.FILE_OPS,
            command="read /etc/passwd",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L2_SILENT,
            estimated_cost_usd=0.0,
        )

        decision = await safety_evaluator.evaluate(step)

        # Arquivos sensíveis devem ser L0_MANUAL
        assert decision.approval_tier == ApprovalTier.L0_MANUAL or decision.approved is False


class TestApprovalTierClassification:
    """Testes para classificação automática de approval tiers."""

    @pytest.mark.asyncio
    async def test_git_command_classification(self, safety_evaluator):
        """'git status' deve ser L2_SILENT."""
        step = ActionStep(
            id="git_status",
            type=ActionType.BASH,
            command="git status",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L2_SILENT,  # Esperado
            estimated_cost_usd=0.0,
        )

        decision = await safety_evaluator.evaluate(step)

        assert decision.approval_tier == ApprovalTier.L2_SILENT

    @pytest.mark.asyncio
    async def test_file_deletion_classification(self, safety_evaluator):
        """'rm file' deve ser L0_MANUAL."""
        step = ActionStep(
            id="rm_file",
            type=ActionType.BASH,
            command="rm /tmp/tempfile",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L0_MANUAL,  # Esperado
            estimated_cost_usd=0.01,
        )

        decision = await safety_evaluator.evaluate(step)

        assert decision.approval_tier == ApprovalTier.L0_MANUAL
