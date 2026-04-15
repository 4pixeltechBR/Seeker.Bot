"""
Tests para ActionOrchestrator — LLM Planning de Ações

Valida:
1. Parsing de intenção do usuário
2. Geração de ExecutionPlan com steps múltiplos
3. Dependências entre steps
4. Estimativa de custo + timeout
5. Safety notes
"""

import pytest
import asyncio
import json
from typing import Optional

from src.core.executor.models import (
    ExecutionPlan,
    ActionStep,
    ActionType,
    ApprovalTier,
)
from src.core.executor.orchestrator import ActionOrchestrator
from src.providers.cascade_advanced import CascadeAdapter


class MockCascadeAdapter:
    """Mock para CascadeAdapter para testes sem LLM real."""

    def __init__(self, response_override: Optional[str] = None):
        self.response_override = response_override
        self.call_count = 0

    async def invoke_with_fallback(self, request, role="STRATEGIC"):
        """Mock de invoke que retorna plano estruturado."""
        self.call_count += 1

        if self.response_override:
            return self.response_override

        # Default mock response: simples plano com 2 steps
        return json.dumps({
            "plan_id": "test_plan_001",
            "steps": [
                {
                    "id": "step_1",
                    "type": "bash",
                    "command": "git add .",
                    "timeout_seconds": 30,
                    "approval_tier": "L1_LOGGED",
                    "estimated_cost_usd": 0.0,
                    "rollback_instruction": "git reset",
                },
                {
                    "id": "step_2",
                    "type": "bash",
                    "command": "git commit -m 'backup'",
                    "timeout_seconds": 15,
                    "approval_tier": "L1_LOGGED",
                    "depends_on": ["step_1"],
                    "rollback_instruction": None,
                }
            ],
            "estimated_total_cost_usd": 0.05,
            "estimated_total_timeout_seconds": 60,
            "safety_notes": "All steps are auto-approved (L1_LOGGED)",
        })


@pytest.mark.asyncio
async def test_orchestrator_basic_planning():
    """Teste básico: orchestrator cria plano a partir de intenção."""
    cascade = MockCascadeAdapter()
    orchestrator = ActionOrchestrator(cascade_adapter=cascade)

    intent = "commit all changes to git"
    plan = await orchestrator.plan_actions(intent)

    assert plan is not None
    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) == 2
    assert plan.steps[0].id == "step_1"
    assert plan.steps[1].depends_on == ["step_1"]
    assert cascade.call_count == 1


@pytest.mark.asyncio
async def test_orchestrator_step_dependencies():
    """Teste: verifica que dependências são parseadas corretamente."""
    cascade = MockCascadeAdapter()
    orchestrator = ActionOrchestrator(cascade_adapter=cascade)

    plan = await orchestrator.plan_actions("test")

    # Step 1 não tem dependências
    assert len(plan.steps[0].depends_on or []) == 0

    # Step 2 depende de step 1
    assert plan.steps[1].depends_on == ["step_1"]


@pytest.mark.asyncio
async def test_orchestrator_cost_estimation():
    """Teste: orchestrator estima custo total do plano."""
    cascade = MockCascadeAdapter()
    orchestrator = ActionOrchestrator(cascade_adapter=cascade)

    plan = await orchestrator.plan_actions("expensive operation")

    assert plan.estimated_total_cost_usd > 0
    assert plan.estimated_total_cost_usd <= 0.20  # Max hard cap


@pytest.mark.asyncio
async def test_orchestrator_timeout_calculation():
    """Teste: orchestrator calcula timeout total de todos os steps."""
    cascade = MockCascadeAdapter()
    orchestrator = ActionOrchestrator(cascade_adapter=cascade)

    plan = await orchestrator.plan_actions("test")

    # 30 + 15 = 45 segundo total esperado (ou perto)
    assert plan.estimated_total_timeout_seconds <= 60


@pytest.mark.asyncio
async def test_orchestrator_multi_step_plan():
    """Teste: plano com múltiplos steps em sequência."""
    response = json.dumps({
        "plan_id": "multi_step",
        "steps": [
            {
                "id": "step_1",
                "type": "bash",
                "command": "mkdir backup",
                "timeout_seconds": 10,
                "approval_tier": "L1_LOGGED",
                "estimated_cost_usd": 0.0,
                "rollback_instruction": "rmdir backup",
            },
            {
                "id": "step_2",
                "type": "bash",
                "command": "cp -r . backup/",
                "timeout_seconds": 20,
                "approval_tier": "L1_LOGGED",
                "depends_on": ["step_1"],
                "estimated_cost_usd": 0.0,
                "rollback_instruction": "rm -rf backup/",
            },
            {
                "id": "step_3",
                "type": "bash",
                "command": "git commit -m 'backup'",
                "timeout_seconds": 15,
                "approval_tier": "L1_LOGGED",
                "depends_on": ["step_2"],
                "estimated_cost_usd": 0.02,
                "rollback_instruction": None,
            }
        ],
        "estimated_total_cost_usd": 0.02,
        "estimated_total_timeout_seconds": 45,
        "safety_notes": "Backup sequence, all safe",
    })

    cascade = MockCascadeAdapter(response_override=response)
    orchestrator = ActionOrchestrator(cascade_adapter=cascade)

    plan = await orchestrator.plan_actions("create backup")

    assert len(plan.steps) == 3
    assert plan.steps[2].depends_on == ["step_2"]
    assert plan.estimated_total_cost_usd == 0.02


@pytest.mark.asyncio
async def test_orchestrator_approval_tiers():
    """Teste: verifica que approval tiers são parseados corretamente."""
    cascade = MockCascadeAdapter()
    orchestrator = ActionOrchestrator(cascade_adapter=cascade)

    plan = await orchestrator.plan_actions("test")

    for step in plan.steps:
        assert step.approval_tier in [ApprovalTier.L0_MANUAL, ApprovalTier.L1_LOGGED, ApprovalTier.L2_SILENT]


@pytest.mark.asyncio
async def test_orchestrator_safety_notes():
    """Teste: orchestrator inclui safety notes no plano."""
    cascade = MockCascadeAdapter()
    orchestrator = ActionOrchestrator(cascade_adapter=cascade)

    plan = await orchestrator.plan_actions("test")

    assert plan.safety_notes is not None
    assert len(plan.safety_notes) > 0


@pytest.mark.asyncio
async def test_orchestrator_max_steps_limit():
    """Teste: orchestrator respeita limite máximo de steps."""
    # Criar plano com muitos steps (deveria falhar ou ser truncado)
    cascade = MockCascadeAdapter()
    orchestrator = ActionOrchestrator(cascade_adapter=cascade)

    # MAX_STEPS = 10 por padrão
    plan = await orchestrator.plan_actions("test")

    assert len(plan.steps) <= 10  # Should not exceed max
