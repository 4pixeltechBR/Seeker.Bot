"""
Tests for Enhanced Safety Layer (Sprint 7.3)
tests/test_safety_layer_enhanced.py

Testes para SafetyPolicy e SafetyLayer:
- Whitelist/blacklist enforcement
- Autonomy tier enforcement
- Trusted goals bypass
- Audit logging
"""

import pytest
import asyncio
from datetime import datetime

from src.core.safety_layer_enhanced import (
    SafetyPolicy,
    SafetyLayer,
    AutonomyTier,
    ActionType,
)


class TestSafetyPolicy:
    """Testes para SafetyPolicy (lógica de controle de ações)"""

    def test_default_tiers_initialized(self):
        """Verifica que tiers padrão são definidos para todas as ações"""
        policy = SafetyPolicy()

        # Todas as ações devem ter tier padrão
        assert len(policy.default_tiers) == 12
        assert ActionType.READ_DATA in policy.default_tiers
        assert ActionType.DELETE_FILE in policy.default_tiers
        assert ActionType.TRANSFER_FUNDS in policy.default_tiers

    def test_read_actions_permit_l2(self):
        """Ações de leitura devem permitir L2_SILENT"""
        policy = SafetyPolicy()

        for action_type in [ActionType.READ_DATA, ActionType.READ_FILE, ActionType.READ_API]:
            allowed, reason = policy.allow_action(
                action_type,
                goal_name="test_goal",
                current_tier=AutonomyTier.L2_SILENT
            )
            assert allowed, f"{action_type} deveria ser permitido com L2"

    def test_write_actions_require_l1(self):
        """Ações de escrita devem aceitar L1+, rejeitar L2"""
        policy = SafetyPolicy()

        for action_type in [ActionType.WRITE_DATA, ActionType.WRITE_FILE, ActionType.API_CALL]:
            # Rejeitar L2 (menos permissões)
            allowed, reason = policy.allow_action(
                action_type,
                goal_name="test_goal",
                current_tier=AutonomyTier.L2_SILENT
            )
            assert not allowed, f"{action_type} deveria rejeitar L2_SILENT"

            # Aceitar L1
            allowed, reason = policy.allow_action(
                action_type,
                goal_name="test_goal",
                current_tier=AutonomyTier.L1_LOGGED
            )
            assert allowed, f"{action_type} deveria aceitar L1_LOGGED"

            # Aceitar L0 (mais permissões)
            allowed, reason = policy.allow_action(
                action_type,
                goal_name="test_goal",
                current_tier=AutonomyTier.L0_MANUAL
            )
            assert allowed, f"{action_type} deveria aceitar L0_MANUAL"

    def test_delete_actions_require_l0_or_trusted(self):
        """Ações de delete devem requerir L0, ou goal com L1 se trusted"""
        policy = SafetyPolicy()

        # L2 sem trust: rejeitar
        allowed, reason = policy.allow_action(
            ActionType.DELETE_FILE,
            goal_name="untrusted_goal",
            current_tier=AutonomyTier.L2_SILENT
        )
        assert not allowed, "DELETE sem trust deveria rejeitar L2_SILENT"

        # L1 sem trust: rejeitar
        allowed, reason = policy.allow_action(
            ActionType.DELETE_FILE,
            goal_name="untrusted_goal",
            current_tier=AutonomyTier.L1_LOGGED
        )
        assert not allowed, "DELETE sem trust deveria rejeitar L1_LOGGED"

        # L1 com trust: aceitar (bypass L0 requerido)
        policy.add_trusted_goal("trusted_deleter")
        allowed, reason = policy.allow_action(
            ActionType.DELETE_FILE,
            goal_name="trusted_deleter",
            current_tier=AutonomyTier.L1_LOGGED
        )
        assert allowed, "DELETE com trust deveria aceitar L1_LOGGED"

        # L0 sem trust: sempre permitido
        allowed, reason = policy.allow_action(
            ActionType.DELETE_FILE,
            goal_name="other_goal",
            current_tier=AutonomyTier.L0_MANUAL
        )
        assert allowed, "DELETE deveria aceitar L0_MANUAL"

    def test_blacklist_blocks_action(self):
        """Ações em blacklist devem ser bloqueadas"""
        policy = SafetyPolicy()

        # Ação deveria ser permitida
        allowed, _ = policy.allow_action(
            ActionType.SEND_MESSAGE,
            current_tier=AutonomyTier.L1_LOGGED
        )
        assert allowed

        # Bloquear ação
        policy.block_action(ActionType.SEND_MESSAGE)

        # Agora deveria ser bloqueada mesmo com tier adequado
        allowed, reason = policy.allow_action(
            ActionType.SEND_MESSAGE,
            current_tier=AutonomyTier.L2_SILENT
        )
        assert not allowed, "Ação em blacklist deveria ser bloqueada"
        assert "bloqueada" in reason.lower()

    def test_unblock_action(self):
        """Desbloquear ação deveria restaurar permissão"""
        policy = SafetyPolicy()
        policy.block_action(ActionType.SEND_MESSAGE)

        # Verificar que está bloqueado
        allowed, _ = policy.allow_action(
            ActionType.SEND_MESSAGE,
            current_tier=AutonomyTier.L1_LOGGED
        )
        assert not allowed

        # Desbloquear
        policy.unblock_action(ActionType.SEND_MESSAGE)

        # Verificar que está desbloqueado
        allowed, _ = policy.allow_action(
            ActionType.SEND_MESSAGE,
            current_tier=AutonomyTier.L1_LOGGED
        )
        assert allowed

    def test_custom_tier_override(self):
        """Custom tiers devem sobrescrever defaults"""
        policy = SafetyPolicy()

        # Por padrão READ_DATA é L2
        assert policy.default_tiers[ActionType.READ_DATA] == AutonomyTier.L2_SILENT

        # Mudar para L0
        policy.set_autonomy_tier(ActionType.READ_DATA, AutonomyTier.L0_MANUAL)

        # Agora L1 deveria rejeitar
        allowed, reason = policy.allow_action(
            ActionType.READ_DATA,
            goal_name="test",
            current_tier=AutonomyTier.L1_LOGGED
        )
        assert not allowed, "Custom tier L0 deveria rejeitar L1"

    def test_trusted_goal_whitelist(self):
        """Goals trusted devem poder fazer ações L0 com apenas L1"""
        policy = SafetyPolicy()

        # DELETE_FILE requer L0 (100), L1 (50) seria rejeitado
        allowed, _ = policy.allow_action(
            ActionType.DELETE_FILE,
            goal_name="untrusted",
            current_tier=AutonomyTier.L1_LOGGED
        )
        assert not allowed, "Untrusted goal com L1 não deveria poder deletar"

        # Adicionar goal à whitelist de confiança
        policy.add_trusted_goal("trusted_deleter")

        # Agora deveria ser permitido (L1 trusted bypass L0 requirement)
        allowed, reason = policy.allow_action(
            ActionType.DELETE_FILE,
            goal_name="trusted_deleter",
            current_tier=AutonomyTier.L1_LOGGED
        )
        assert allowed, "Goal trusted deveria poder fazer DELETE com L1"
        assert "confiança" in reason.lower()

    def test_get_policy_report(self):
        """Policy report deveria conter estado atual"""
        policy = SafetyPolicy()
        policy.add_trusted_goal("my_goal")
        policy.block_action(ActionType.TRANSFER_FUNDS)
        policy.set_autonomy_tier(ActionType.READ_DATA, AutonomyTier.L1_LOGGED)

        report = policy.get_policy_report()

        assert "whitelist" in report
        assert "blacklist" in report
        assert "trusted_goals" in report
        assert "tier_customizations" in report

        assert "my_goal" in report["trusted_goals"]
        assert "transfer_funds" in report["blacklist"]
        assert "read_data" in report["tier_customizations"]
        assert report["tier_customizations"]["read_data"] == "L1_LOGGED"


class TestSafetyLayer:
    """Testes para SafetyLayer (integração + auditoria)"""

    @pytest.mark.asyncio
    async def test_check_action_allowed(self):
        """Ação permitida deveria retornar True"""
        layer = SafetyLayer()

        allowed, reason = await layer.check_action(
            ActionType.READ_DATA,
            goal_name="reader",
            current_tier=AutonomyTier.L2_SILENT
        )

        assert allowed
        assert "permitida" in reason.lower()

    @pytest.mark.asyncio
    async def test_check_action_denied(self):
        """Ação bloqueada deveria retornar False"""
        layer = SafetyLayer()

        allowed, reason = await layer.check_action(
            ActionType.DELETE_FILE,
            goal_name="deleter",
            current_tier=AutonomyTier.L0_MANUAL  # Tem tier certo
        )
        assert allowed  # Primeira tentativa OK

        # Bloquear ação
        layer.policy.block_action(ActionType.DELETE_FILE)

        allowed, reason = await layer.check_action(
            ActionType.DELETE_FILE,
            goal_name="deleter",
            current_tier=AutonomyTier.L0_MANUAL  # Mesmo tier, mas bloqueado
        )

        assert not allowed
        assert "bloqueada" in reason.lower()

    @pytest.mark.asyncio
    async def test_audit_log_creation(self):
        """Cada check_action deveria registrar no audit log"""
        layer = SafetyLayer()

        assert len(layer.audit_log) == 0

        await layer.check_action(
            ActionType.READ_DATA,
            goal_name="reader",
            current_tier=AutonomyTier.L2_SILENT
        )

        assert len(layer.audit_log) == 1

        entry = layer.audit_log[0]
        assert entry["goal"] == "reader"
        assert entry["action"] == "read_data"
        assert entry["tier"] == "L2_SILENT"
        assert entry["allowed"] is True
        assert "timestamp" in entry

    @pytest.mark.asyncio
    async def test_audit_log_includes_details(self):
        """Audit log deveria incluir action_details"""
        layer = SafetyLayer()

        details = {"filename": "important_file.txt", "size": 1024}

        await layer.check_action(
            ActionType.DELETE_FILE,
            goal_name="cleaner",
            current_tier=AutonomyTier.L0_MANUAL,
            action_details=details
        )

        entry = layer.audit_log[0]
        assert entry["details"] == details

    @pytest.mark.asyncio
    async def test_get_audit_log_limit(self):
        """get_audit_log deveria respeitar limit"""
        layer = SafetyLayer()

        # Criar 10 entradas
        for i in range(10):
            await layer.check_action(
                ActionType.READ_DATA,
                goal_name=f"goal_{i}",
                current_tier=AutonomyTier.L2_SILENT
            )

        assert len(layer.audit_log) == 10

        # Pedir apenas 5
        recent = layer.get_audit_log(limit=5)
        assert len(recent) == 5

        # Últimas 5 devem ser goals_5..9
        goals = [entry["goal"] for entry in recent]
        assert "goal_9" in goals
        assert "goal_0" not in goals

    @pytest.mark.asyncio
    async def test_concurrent_audit_entries(self):
        """Múltiplas ações concorrentes devem ser registradas"""
        layer = SafetyLayer()

        async def make_action(goal_id):
            await layer.check_action(
                ActionType.API_CALL,
                goal_name=f"concurrent_goal_{goal_id}",
                current_tier=AutonomyTier.L1_LOGGED
            )

        # Executar 5 ações concorrentemente
        await asyncio.gather(*[make_action(i) for i in range(5)])

        assert len(layer.audit_log) == 5

    @pytest.mark.asyncio
    async def test_export_policy(self):
        """export_policy deveria conter timestamp e configuração"""
        layer = SafetyLayer()

        # Fazer algumas ações para gerar audit entries
        await layer.check_action(
            ActionType.READ_DATA,
            goal_name="reader",
            current_tier=AutonomyTier.L2_SILENT
        )

        export = layer.export_policy()

        assert "timestamp" in export
        assert "policy" in export
        assert "audit_entries" in export
        assert export["audit_entries"] == 1

        policy = export["policy"]
        assert "whitelist" in policy
        assert "blacklist" in policy
        assert "trusted_goals" in policy


class TestIntegrationSafetyTierAndPolicy:
    """Testes de integração entre SafetyLayer e SafetyPolicy"""

    @pytest.mark.asyncio
    async def test_end_to_end_workflow(self):
        """Workflow completo: criar policy, layer, executar ações, auditar"""
        # 1. Criar policy customizada
        policy = SafetyPolicy()
        policy.add_trusted_goal("revenue_hunter")
        policy.block_action(ActionType.TRANSFER_FUNDS)  # Não queremos transferências

        # 2. Criar layer com policy
        layer = SafetyLayer(policy)

        # 3. Revenue Hunter (L1) tenta ação de leitura (requer L2) → deve passar
        allowed, _ = await layer.check_action(
            ActionType.READ_API,
            goal_name="revenue_hunter",
            current_tier=AutonomyTier.L1_LOGGED
        )
        assert allowed, "L1 deveria conseguir fazer READ (requer L2)"

        # 4. Revenue Hunter (L1 trusted) tenta deletar (requer L0) → deve passar
        allowed, _ = await layer.check_action(
            ActionType.DELETE_DATA,
            goal_name="revenue_hunter",
            current_tier=AutonomyTier.L1_LOGGED
        )
        assert allowed, "L1 trusted deveria conseguir fazer DELETE"

        # 5. Tenta transferir fundos → deve ser bloqueado (em blacklist)
        allowed, reason = await layer.check_action(
            ActionType.TRANSFER_FUNDS,
            goal_name="revenue_hunter",
            current_tier=AutonomyTier.L0_MANUAL  # Mesmo com tier máximo
        )
        assert not allowed
        assert "bloqueada" in reason.lower()

        # 6. Verificar audit log
        log = layer.get_audit_log()
        assert len(log) == 3

        # Última entry deve ser o transfer bloqueado
        assert log[-1]["action"] == "transfer_funds"
        assert log[-1]["allowed"] is False

    @pytest.mark.asyncio
    async def test_tier_escalation_workflow(self):
        """Teste escalação de tier: L0 → L1 → L2"""
        layer = SafetyLayer()

        # 1. L0 consegue fazer DELETE (action requer L0)
        allowed, _ = await layer.check_action(
            ActionType.DELETE_FILE,
            goal_name="admin",
            current_tier=AutonomyTier.L0_MANUAL
        )
        assert allowed

        # 2. L1 consegue fazer WRITE (action requer L1)
        allowed, _ = await layer.check_action(
            ActionType.WRITE_DATA,
            goal_name="worker",
            current_tier=AutonomyTier.L1_LOGGED
        )
        assert allowed

        # 3. L2 consegue tudo (exceto blacklisted)
        allowed, _ = await layer.check_action(
            ActionType.READ_DATA,
            goal_name="reader",
            current_tier=AutonomyTier.L2_SILENT
        )
        assert allowed

    @pytest.mark.asyncio
    async def test_prevent_privilege_escalation(self):
        """Garantir que tier baixo (L2) não consegue executar ações restritas"""
        layer = SafetyLayer()

        # L2 tenta fazer WRITE (requer L1) → deve falhar
        allowed, reason = await layer.check_action(
            ActionType.WRITE_DATA,
            goal_name="weak_goal",
            current_tier=AutonomyTier.L2_SILENT
        )

        assert not allowed, "L2_SILENT não deveria poder fazer WRITE"
        assert "requer" in reason.lower()
        assert "L1" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
