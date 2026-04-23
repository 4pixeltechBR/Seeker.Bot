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
from .actions import ActionExecutor
from .safety import SafetyGate, SafetyGateEvaluator, ExecutorPolicy
from .afk_protocol import AFKProtocol, AFKProtocolCoordinator, UserStatus

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
    # Executor
    "ActionExecutor",
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
