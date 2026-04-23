"""
Remote Executor — Core Data Structures

Modelos e interfaces para orquestração de ações multi-step autônomas.

Track B: Remote Executor implementation (Sprint 12-13)
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime


class ActionType(Enum):
    """Tipos de ação suportadas pelo executor"""
    BASH = "bash"                  # Execute bash command
    FILE_OPS = "file_ops"          # File read/write/delete
    API = "api"                    # HTTP API calls
    REMOTE_TRIGGER = "remote_trigger"  # Delegação para Claude Code


class ApprovalTier(Enum):
    """Tiers de aprovação para ações (L0=manual, L1=logged, L2=silent)"""
    L0_MANUAL = "l0_manual"        # Requer aprovação manual (Telegram callback)
    L1_LOGGED = "l1_logged"        # Executa com log automático
    L2_SILENT = "l2_silent"        # Executa silenciosamente


class ActionStatus(Enum):
    """Status de execução de uma ação"""
    PENDING = "pending"            # Aguardando aprovação
    APPROVED = "approved"          # Aprovada, pronta para executar
    RUNNING = "running"            # Em execução
    SUCCESS = "success"            # Executada com sucesso
    FAILED = "failed"              # Falhou na execução
    TIMEOUT = "timeout"            # Timeout na execução
    SKIPPED = "skipped"            # Pulada (dependência falhou)
    ROLLED_BACK = "rolled_back"    # Rollback executado após falha
    INVALID_STEP = "invalid_step"  # Step inválido ou malformado


@dataclass
class ActionStep:
    """Um passo individual na execução de ação"""

    id: str                        # Unique step ID (step_1, step_2, ...)
    type: ActionType               # Tipo de ação (bash, file, api, remote)
    command: str                   # Comando a executar (bash: "git add .", file: "read:path/to/file", etc)
    timeout_seconds: int           # Timeout para esta ação
    approval_tier: ApprovalTier    # L0_MANUAL / L1_LOGGED / L2_SILENT
    estimated_cost_usd: float      # Custo estimado (LLM calls, API calls, etc)

    # Dependencies
    depends_on: List[str] = field(default_factory=list)  # IDs de steps que este depende

    # Rollback
    rollback_instruction: Optional[str] = None  # Como reverter se falhar (ex: "git reset")

    # Metadata
    description: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExecutionPlan:
    """Plano completo de execução gerado pelo ActionOrchestrator"""

    plan_id: str                   # Unique plan ID
    steps: List[ActionStep]        # Ordered list of steps
    estimated_total_cost_usd: float
    estimated_total_timeout_seconds: int

    # Safety notes
    safety_notes: str              # Notas sobre riscos e mitigações
    highest_approval_tier: ApprovalTier  # Tier máximo necessário (L0 > L1 > L2)

    # Metadata
    user_intention: str            # Intenção original do usuário
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ActionResult:
    """Resultado de uma ação executada"""

    step_id: str
    status: str                    # "success" / "failed" / "timeout" / "skipped"
    output: str                    # stdout/stderr ou resultado
    error_message: Optional[str] = None

    # Execution metrics
    duration_ms: int = 0
    cost_usd: float = 0.0

    # Rollback info
    rollback_executed: bool = False
    rollback_successful: Optional[bool] = None

    # Audit
    executed_by_goal: str = "remote_executor"
    executed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExecutionResult:
    """Resultado completo de um ExecutionPlan"""

    plan_id: str
    overall_status: str            # "success" / "partial_success" / "failed"
    steps_results: List[ActionResult]

    # Aggregated metrics
    total_cost_usd: float
    total_duration_ms: int
    successful_steps: int
    failed_steps: int

    # Metadata
    user_id: str = "unknown"
    session_id: str = "unknown"

    # Audit trail (snapshot-based)
    before_snapshot: Optional[Dict[str, Any]] = None  # Git status, file hashes, etc
    after_snapshot: Optional[Dict[str, Any]] = None

    # Timestamp
    completed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExecutionContext:
    """Contexto de execução para planos"""

    plan_id: str
    triggered_by_user: str         # Usuário que disparou a ação
    triggered_by_intent: str       # Intenção original
    goal_name: str                 # Nome do goal que executa
    budget_remaining_usd: float    # Budget restante

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SAFETY GATE DATASTRUCTURES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class SafetyGateDecision:
    """Decisão de safety gate sobre uma ação"""

    action_id: str
    approved: bool                 # True = executar, False = bloquear
    approval_tier: ApprovalTier
    reason: str                    # Por que foi aprovado/bloqueado

    # Metadata
    evaluated_at: datetime = field(default_factory=datetime.utcnow)
    policy_version: str = "1.0"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AUDIT ENTRY STRUCTURE (para JSONL audit.log)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class AuditEntry:
    """Entry para audit trail em data/executor/audit.jsonl"""

    timestamp: datetime
    action_id: str
    plan_id: str
    type: ActionType
    command: str
    status: str                    # "success" / "failed" / "timeout"
    approval_tier: ApprovalTier
    cost_usd: float
    duration_ms: int

    # Snapshot-based audit
    before_snapshot: Optional[Dict] = None
    after_snapshot: Optional[Dict] = None
    output_hash: Optional[str] = None  # SHA256 de output para não logs grandes

    # Context
    executed_by_goal: str = "remote_executor"
    triggered_by_user: Optional[str] = None
    user_id: int = 0
    session_id: str = ""
