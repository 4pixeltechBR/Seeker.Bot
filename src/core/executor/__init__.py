"""
Remote Executor — Orquestração Autônoma de Ações

Track B: Remote Executor implementation (Sprint 12-13)
"""

from .models import (
    ActionType,
    ApprovalTier,
    ActionStatus,
    ActionStep,
    ExecutionPlan,
    ExecutionContext,
    ActionResult,
    ExecutionResult,
    SafetyGateDecision,
    AuditEntry,
)
from .base import ActionHandler
from .orchestrator import ActionOrchestrator
from .safety import SafetyGate, SafetyGateEvaluator, ExecutorPolicy
from .afk_protocol import AFKProtocol, AFKProtocolCoordinator, UserStatus

# NOTE: ActionExecutor foi removido — actions.py nunca foi implementado.
# remote_executor/goal.py está desabilitado em config/skills.yaml até
# alguém escrever src/core/executor/actions.py com execute_plan() e
# summarize_results(). Não reativar este import sem criar o módulo.

__all__ = [
    # Models
    "ActionType",
    "ApprovalTier",
    "ActionStatus",
    "ActionStep",
    "ExecutionPlan",
    "ExecutionContext",
    "ActionResult",
    "ExecutionResult",
    "SafetyGateDecision",
    "AuditEntry",
    # Orchestrator
    "ActionOrchestrator",
    # Handlers
    "ActionHandler",
    # Safety
    "SafetyGate",
    "SafetyGateEvaluator",
    "ExecutorPolicy",
    # AFK Protocol
    "AFKProtocol",
    "AFKProtocolCoordinator",
    "UserStatus",
]
