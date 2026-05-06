"""
Scheduler Conversacional — Models

Dataclasses para tarefas agendadas, execuções e sessões do wizard.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


class ScheduleType(str, Enum):
    """Tipos de periodicidade suportadas"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ANNUAL = "annual"


class TaskStatus(str, Enum):
    """Status de uma tarefa agendada"""
    ENABLED = "enabled"
    PAUSED = "paused"
    DISABLED = "disabled"
    ERROR = "error"


class WizardState(str, Enum):
    """Estados do wizard de criação"""
    IDLE = "idle"
    COLLECTING_TITLE = "collecting_title"
    COLLECTING_SCHEDULE_TYPE = "collecting_schedule_type"
    COLLECTING_DAY_OF_WEEK = "collecting_day_of_week"  # para weekly
    COLLECTING_DAY_OF_MONTH = "collecting_day_of_month"  # para monthly
    COLLECTING_MONTH_DAY = "collecting_month_day"  # para annual
    COLLECTING_HOUR = "collecting_hour"
    COLLECTING_INSTRUCTION = "collecting_instruction"
    CONFIRMATION = "confirmation"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class ScheduledTask:
    """Tarefa agendada"""
    id: str
    title: str
    schedule_type: ScheduleType
    hour: int  # 0-23
    timezone: str = "America/Sao_Paulo"

    # Complementos da periodicidade
    day_of_week: Optional[int] = None  # 0-6 (segunda-domingo) para WEEKLY
    day_of_month: Optional[int] = None  # 1-31 para MONTHLY
    month: Optional[int] = None  # 1-12 para ANNUAL

    # Instrução da tarefa
    instruction_text: str = ""

    # Status
    is_enabled: bool = True
    status: TaskStatus = TaskStatus.ENABLED

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None

    # Execução
    last_status: Optional[str] = None  # "success", "failed", etc
    failure_count: int = 0
    last_error: Optional[str] = None

    # Contexto
    chat_id: int = 0
    created_by: str = ""
    source: str = "telegram"  # "telegram", "api", etc


@dataclass
class ScheduledTaskRun:
    """Registro de execução de uma tarefa agendada"""
    id: str
    task_id: str

    # Timing
    scheduled_for: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    # Status
    status: str = "pending"  # "pending", "running", "success", "failed", "timeout"
    error: Optional[str] = None
    execution_id: Optional[str] = None  # link para ExecutionRecord

    # Idempotência
    idempotency_key: str = ""

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class WizardSession:
    """Sessão ativa do wizard de criação"""
    id: str
    chat_id: int
    user_id: str

    # Estado
    state: WizardState = WizardState.IDLE

    # Dados coletados (será preenchido passo a passo)
    data: Dict[str, Any] = field(default_factory=dict)

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None  # Expira em 30 min

    # Para rollback
    previous_state: Optional[WizardState] = None

    def is_expired(self) -> bool:
        """Verifica se a sessão expirou"""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def get_collected_value(self, key: str) -> Optional[Any]:
        """Obtém valor coletado"""
        return self.data.get(key)

    def set_collected_value(self, key: str, value: Any) -> None:
        """Define valor coletado"""
        self.data[key] = value
        self.updated_at = datetime.utcnow()
