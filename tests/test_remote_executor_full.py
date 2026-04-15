"""
Tests End-to-End para RemoteExecutor — Fluxo Completo

Testa:
1. L2_SILENT flow: intention → planning → execution (sem aprovação)
2. L1_LOGGED flow: intention → planning → execution + audit
3. L0_MANUAL flow: intention → planning → enqueue → approval → execution
4. Multi-step com dependências e rollback
5. Integração com RemoteExecutorMiner
"""

import pytest
import asyncio
import json
from datetime import datetime
from typing import Optional

from src.core.executor.models import (
    ActionStep,
    ActionType,
    ApprovalTier,
    ExecutionPlan,
    ActionStatus,
)
from src.core.executor.orchestrator import ActionOrchestrator
from src.core.executor.safety import SafetyGateEvaluator
from src.core.executor.afk_protocol import AFKProtocol, UserStatus
from src.skills.remote_executor.miner import RemoteExecutorMiner, ActionDetectionResult
from src.skills.remote_executor.goal import RemoteExecutorGoal


class MockPipeline:
    """Mock SeekerPipeline para testes."""

    def __init__(self):
        self.cascade_adapter = MockCascadeAdapter()
        self.user_id = "test_user"
        self.sprint11_tracker = MockTracker()


class MockCascadeAdapter:
    """Mock CascadeAdapter que simula respostas LLM."""

    async def invoke_with_fallback(self, request, role="STRATEGIC"):
        """Retorna plano simples para testes."""
        return json.dumps({
            "plan_id": "test_plan",
            "steps": [
                {
                    "id": "step_1",
                    "type": "bash",
                    "command": "echo 'test'",
                    "timeout_seconds": 10,
                    "approval_tier": "L2_SILENT",
                    "estimated_cost_usd": 0.0,
                }
            ],
            "estimated_total_cost_usd": 0.0,
            "estimated_total_timeout_seconds": 10,
            "safety_notes": "Simple test",
        })


class MockTracker:
    """Mock Sprint11Tracker para métricas."""

    def __init__(self):
        self.executions = []

    def record_remote_executor_execution(self, **kwargs):
        self.executions.append(kwargs)


@pytest.fixture
def pipeline():
    return MockPipeline()


@pytest.mark.asyncio
async def test_miner_detects_bash_commands(pipeline):
    """Testa que miner detecta comandos bash."""
    miner = RemoteExecutorMiner()
    intent = "execute ls -la"
    detection = miner.detect(intent)
    
    assert detection.detected is True
    assert detection.category.value == "bash"


@pytest.mark.asyncio
async def test_miner_classifies_autonomy_tiers(pipeline):
    """Testa classificação de autonomy tiers."""
    miner = RemoteExecutorMiner()
    
    # L2_SILENT: safe commands
    result = miner.detect("execute ls")
    assert result.autonomy_tier == ApprovalTier.L2_SILENT
    
    # L0_MANUAL: dangerous commands
    result = miner.detect("execute rm -rf")
    assert result.autonomy_tier == ApprovalTier.L0_MANUAL


@pytest.mark.asyncio
async def test_afk_protocol_enforcement(pipeline):
    """Testa AFK window enforcement."""
    afk = AFKProtocol(user_id="test_user")
    afk.update_status(UserStatus.AWAY)
    
    # L2_SILENT sempre permitido
    assert afk.is_action_allowed(ApprovalTier.L2_SILENT) is True
