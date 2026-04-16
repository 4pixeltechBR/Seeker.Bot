"""
Scheduler Conversacional — Store

Persistência em SQLite para tarefas agendadas, execuções e sessões do wizard.
"""

import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from src.skills.scheduler_conversacional.models import (
    ScheduledTask,
    ScheduledTaskRun,
    WizardSession,
    ScheduleType,
    TaskStatus,
    WizardState,
)

log = logging.getLogger("seeker.scheduler.store")


class SchedulerStore:
    """Store para Scheduler Conversacional usando SQLite"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS scheduler_tasks (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        schedule_type TEXT NOT NULL,
        day_of_week INTEGER,
        day_of_month INTEGER,
        month INTEGER,
        hour INTEGER NOT NULL,
        timezone TEXT DEFAULT 'America/Sao_Paulo',
        instruction_text TEXT,
        is_enabled BOOLEAN DEFAULT 1,
        status TEXT DEFAULT 'enabled',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_run_at TEXT,
        next_run_at TEXT,
        last_status TEXT,
        failure_count INTEGER DEFAULT 0,
        last_error TEXT,
        chat_id INTEGER,
        created_by TEXT,
        source TEXT DEFAULT 'telegram',
        UNIQUE(chat_id, title)
    );

    CREATE TABLE IF NOT EXISTS scheduler_task_runs (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        scheduled_for TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        status TEXT DEFAULT 'pending',
        error TEXT,
        execution_id TEXT,
        idempotency_key TEXT UNIQUE,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (task_id) REFERENCES scheduler_tasks(id)
    );

    CREATE TABLE IF NOT EXISTS scheduler_wizard_sessions (
        id TEXT PRIMARY KEY,
        chat_id INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        state TEXT NOT NULL,
        data TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        expires_at TEXT,
        previous_state TEXT,
        UNIQUE(chat_id)
    );

    CREATE INDEX IF NOT EXISTS idx_scheduler_chat_id ON scheduler_tasks(chat_id);
    CREATE INDEX IF NOT EXISTS idx_scheduler_enabled ON scheduler_tasks(is_enabled);
    CREATE INDEX IF NOT EXISTS idx_scheduler_next_run ON scheduler_tasks(next_run_at);
    CREATE INDEX IF NOT EXISTS idx_scheduler_run_task_id ON scheduler_task_runs(task_id);
    CREATE INDEX IF NOT EXISTS idx_scheduler_run_status ON scheduler_task_runs(status);
    CREATE INDEX IF NOT EXISTS idx_wizard_chat_id ON scheduler_wizard_sessions(chat_id);
    """

    def __init__(self, db):
        """
        Args:
            db: AsyncDatabase instance (from memory store)
        """
        self.db = db

    async def init(self) -> None:
        """Inicializa schema"""
        try:
            await self.db.executescript(self.SCHEMA)
            await self.db.commit()
            log.info("[scheduler] Schema initialized")
        except Exception as e:
            log.error(f"[scheduler] Schema init failed: {e}")
            raise

    # ────────────────────────────────────────────────────────
    # SCHEDULED TASKS
    # ────────────────────────────────────────────────────────

    async def create_task(self, task: ScheduledTask) -> None:
        """Cria nova tarefa"""
        sql = """
            INSERT INTO scheduler_tasks
            (id, title, schedule_type, day_of_week, day_of_month, month, hour,
             timezone, instruction_text, is_enabled, status, created_at, updated_at,
             next_run_at, chat_id, created_by, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        await self.db.execute(
            sql,
            (
                task.id,
                task.title,
                task.schedule_type.value,
                task.day_of_week,
                task.day_of_month,
                task.month,
                task.hour,
                task.timezone,
                task.instruction_text,
                task.is_enabled,
                task.status.value,
                task.created_at.isoformat(),
                task.updated_at.isoformat(),
                task.next_run_at.isoformat() if task.next_run_at else None,
                task.chat_id,
                task.created_by,
                task.source,
            ),
        )
        await self.db.commit()

    async def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Obtém tarefa por ID"""
        sql = "SELECT * FROM scheduler_tasks WHERE id = ?"
        async with self.db.execute(sql, (task_id,)) as cur:
            row = await cur.fetchone()
            return self._row_to_task(row) if row else None

    async def list_tasks(self, chat_id: int) -> List[ScheduledTask]:
        """Lista tarefas do chat"""
        sql = "SELECT * FROM scheduler_tasks WHERE chat_id = ? ORDER BY created_at DESC"
        async with self.db.execute(sql, (chat_id,)) as cur:
            rows = await cur.fetchall()
            return [self._row_to_task(row) for row in rows if row]

    async def find_overdue_tasks(self) -> List[ScheduledTask]:
        """Encontra tarefas que devem rodar agora"""
        sql = """
            SELECT * FROM scheduler_tasks
            WHERE is_enabled = 1
            AND next_run_at IS NOT NULL
            AND next_run_at <= ?
            ORDER BY next_run_at ASC
        """
        now = datetime.utcnow().isoformat()
        async with self.db.execute(sql, (now,)) as cur:
            rows = await cur.fetchall()
            return [self._row_to_task(row) for row in rows if row]

    async def update_task(self, task: ScheduledTask) -> None:
        """Atualiza tarefa"""
        sql = """
            UPDATE scheduler_tasks SET
                title = ?, schedule_type = ?, day_of_week = ?, day_of_month = ?,
                month = ?, hour = ?, timezone = ?, instruction_text = ?,
                is_enabled = ?, status = ?, updated_at = ?, next_run_at = ?,
                last_run_at = ?, last_status = ?, failure_count = ?, last_error = ?
            WHERE id = ?
        """
        await self.db.execute(
            sql,
            (
                task.title,
                task.schedule_type.value,
                task.day_of_week,
                task.day_of_month,
                task.month,
                task.hour,
                task.timezone,
                task.instruction_text,
                task.is_enabled,
                task.status.value,
                task.updated_at.isoformat(),
                task.next_run_at.isoformat() if task.next_run_at else None,
                task.last_run_at.isoformat() if task.last_run_at else None,
                task.last_status,
                task.failure_count,
                task.last_error,
                task.id,
            ),
        )
        await self.db.commit()

    async def delete_task(self, task_id: str) -> None:
        """Deleta tarefa e suas execuções"""
        await self.db.execute("DELETE FROM scheduler_task_runs WHERE task_id = ?", (task_id,))
        await self.db.execute("DELETE FROM scheduler_tasks WHERE id = ?", (task_id,))
        await self.db.commit()

    # ────────────────────────────────────────────────────────
    # TASK RUNS
    # ────────────────────────────────────────────────────────

    async def create_run(self, run: ScheduledTaskRun) -> None:
        """Cria registro de execução"""
        sql = """
            INSERT INTO scheduler_task_runs
            (id, task_id, scheduled_for, started_at, finished_at, status, error,
             execution_id, idempotency_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        await self.db.execute(
            sql,
            (
                run.id,
                run.task_id,
                run.scheduled_for.isoformat(),
                run.started_at.isoformat() if run.started_at else None,
                run.finished_at.isoformat() if run.finished_at else None,
                run.status,
                run.error,
                run.execution_id,
                run.idempotency_key,
                run.created_at.isoformat(),
                run.updated_at.isoformat(),
            ),
        )
        await self.db.commit()

    async def get_run(self, run_id: str) -> Optional[ScheduledTaskRun]:
        """Obtém execução por ID"""
        sql = "SELECT * FROM scheduler_task_runs WHERE id = ?"
        async with self.db.execute(sql, (run_id,)) as cur:
            row = await cur.fetchone()
            return self._row_to_run(row) if row else None

    async def check_idempotency(self, idempotency_key: str) -> bool:
        """Verifica se já foi executado (idempotência)"""
        sql = "SELECT id FROM scheduler_task_runs WHERE idempotency_key = ?"
        async with self.db.execute(sql, (idempotency_key,)) as cur:
            row = await cur.fetchone()
            return row is not None

    async def update_run(self, run: ScheduledTaskRun) -> None:
        """Atualiza execução"""
        sql = """
            UPDATE scheduler_task_runs SET
                status = ?, error = ?, execution_id = ?, started_at = ?,
                finished_at = ?, updated_at = ?
            WHERE id = ?
        """
        await self.db.execute(
            sql,
            (
                run.status,
                run.error,
                run.execution_id,
                run.started_at.isoformat() if run.started_at else None,
                run.finished_at.isoformat() if run.finished_at else None,
                run.updated_at.isoformat(),
                run.id,
            ),
        )
        await self.db.commit()

    # ────────────────────────────────────────────────────────
    # WIZARD SESSIONS
    # ────────────────────────────────────────────────────────

    async def create_wizard_session(self, session: WizardSession) -> None:
        """Cria sessão do wizard"""
        sql = """
            INSERT INTO scheduler_wizard_sessions
            (id, chat_id, user_id, state, data, created_at, updated_at, expires_at, previous_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        await self.db.execute(
            sql,
            (
                session.id,
                session.chat_id,
                session.user_id,
                session.state.value,
                json.dumps(session.data),
                session.created_at.isoformat(),
                session.updated_at.isoformat(),
                session.expires_at.isoformat() if session.expires_at else None,
                session.previous_state.value if session.previous_state else None,
            ),
        )
        await self.db.commit()

    async def get_wizard_session(self, chat_id: int) -> Optional[WizardSession]:
        """Obtém sessão ativa do chat"""
        sql = "SELECT * FROM scheduler_wizard_sessions WHERE chat_id = ?"
        async with self.db.execute(sql, (chat_id,)) as cur:
            row = await cur.fetchone()
            return self._row_to_wizard_session(row) if row else None

    async def update_wizard_session(self, session: WizardSession) -> None:
        """Atualiza sessão"""
        sql = """
            UPDATE scheduler_wizard_sessions SET
                state = ?, data = ?, updated_at = ?, expires_at = ?, previous_state = ?
            WHERE id = ?
        """
        await self.db.execute(
            sql,
            (
                session.state.value,
                json.dumps(session.data),
                session.updated_at.isoformat(),
                session.expires_at.isoformat() if session.expires_at else None,
                session.previous_state.value if session.previous_state else None,
                session.id,
            ),
        )
        await self.db.commit()

    async def delete_wizard_session(self, chat_id: int) -> None:
        """Deleta sessão (encerra wizard)"""
        await self.db.execute("DELETE FROM scheduler_wizard_sessions WHERE chat_id = ?", (chat_id,))
        await self.db.commit()

    async def cleanup_expired_sessions(self) -> int:
        """Remove sessões expiradas. Retorna count"""
        sql = "SELECT COUNT(*) as count FROM scheduler_wizard_sessions WHERE expires_at IS NOT NULL AND expires_at <= ?"
        now = datetime.utcnow().isoformat()

        async with self.db.execute(sql, (now,)) as cur:
            row = await cur.fetchone()
            count = row["count"] if row else 0

        await self.db.execute(
            "DELETE FROM scheduler_wizard_sessions WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        await self.db.commit()

        return count

    # ────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_task(row) -> ScheduledTask:
        """Converte linha DB em ScheduledTask"""
        return ScheduledTask(
            id=row["id"],
            title=row["title"],
            schedule_type=ScheduleType(row["schedule_type"]),
            hour=row["hour"],
            timezone=row["timezone"],
            day_of_week=row["day_of_week"],
            day_of_month=row["day_of_month"],
            month=row["month"],
            instruction_text=row["instruction_text"] or "",
            is_enabled=bool(row["is_enabled"]),
            status=TaskStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_run_at=datetime.fromisoformat(row["last_run_at"]) if row["last_run_at"] else None,
            next_run_at=datetime.fromisoformat(row["next_run_at"]) if row["next_run_at"] else None,
            last_status=row["last_status"],
            failure_count=row["failure_count"],
            last_error=row["last_error"],
            chat_id=row["chat_id"],
            created_by=row["created_by"],
            source=row["source"],
        )

    @staticmethod
    def _row_to_run(row) -> ScheduledTaskRun:
        """Converte linha DB em ScheduledTaskRun"""
        return ScheduledTaskRun(
            id=row["id"],
            task_id=row["task_id"],
            scheduled_for=datetime.fromisoformat(row["scheduled_for"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
            status=row["status"],
            error=row["error"],
            execution_id=row["execution_id"],
            idempotency_key=row["idempotency_key"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_wizard_session(row) -> WizardSession:
        """Converte linha DB em WizardSession"""
        data = json.loads(row["data"]) if row["data"] else {}
        return WizardSession(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            state=WizardState(row["state"]),
            data=data,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            previous_state=WizardState(row["previous_state"]) if row["previous_state"] else None,
        )
