"""
Seeker.Bot — Unified Goal Manager
Integra persistência, eval_count tracking, e tier-based autonomy.

Features:
- CRUD com persistência em SQLite
- eval_count tracking para debug de loops infinitos
- Tier-based autonomy (L1/L2/L3)
- Actions log para auditoria
- Emergency stop (kill switch)

Uso:
    manager = GoalManager(memory_store)
    goal = await manager.add_goal(
        title="Daily Report",
        description="Generate daily report",
        tier=2,
        priority=1,
        schedule="daily 09:00"
    )
    due_goals = await manager.get_due_goals()
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("seeker.goal_manager")


@dataclass
class Goal:
    """Modelo unificado de Goal."""
    goal_id: str
    title: str
    description: str
    tier: int  # 1=irreversível (manual), 2=reversível, 3=autonomo
    priority: int  # 1=crítico ... 5=baixo
    schedule: str  # "every 60m", "daily 09:00", "on_event:vision"
    max_actions_per_cycle: int
    enabled: bool
    tools: list[str]
    created_at: str
    last_evaluated: Optional[str]
    next_evaluation: Optional[str]
    eval_count: int  # Quantas vezes foi avaliado
    status: str  # "active", "paused", "emergency_stop"
    context: dict  # Dados persistentes entre ciclos


class GoalManager:
    """
    Gerenciador unificado de Goals com persistência em SQLite.
    Integra com a MemoryStore existente.
    """

    # Schema SQL para goals
    GOALS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS goals (
        goal_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        tier INTEGER DEFAULT 2,
        priority INTEGER DEFAULT 3,
        schedule TEXT,
        max_actions_per_cycle INTEGER DEFAULT 5,
        enabled INTEGER DEFAULT 1,
        tools TEXT,  -- JSON array
        created_at TEXT,
        last_evaluated TEXT,
        next_evaluation TEXT,
        eval_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active',
        context TEXT,  -- JSON dict
        UNIQUE(goal_id)
    );

    CREATE TABLE IF NOT EXISTS goal_actions_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        goal_id TEXT NOT NULL,
        action TEXT,
        result TEXT,
        tier INTEGER,
        approved INTEGER DEFAULT 1,
        FOREIGN KEY (goal_id) REFERENCES goals(goal_id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_goals_enabled ON goals(enabled);
    CREATE INDEX IF NOT EXISTS idx_goals_next_eval ON goals(next_evaluation);
    CREATE INDEX IF NOT EXISTS idx_actions_timestamp ON goal_actions_log(timestamp DESC);
    """

    def __init__(self, memory_store):
        self.memory = memory_store
        self._kill_switch = False

    async def init(self) -> None:
        """Inicializa schema no banco de dados."""
        try:
            await self.memory._db.executescript(self.GOALS_SCHEMA)
            await self.memory._db.commit()
            log.info("[goal_manager] Schema inicializado")
        except Exception as e:
            log.error(f"[goal_manager] Falha ao inicializar schema: {e}")

    async def add_goal(
        self,
        title: str,
        description: str,
        tier: int = 2,
        priority: int = 3,
        schedule: str = "every 60m",
        max_actions_per_cycle: int = 5,
        enabled: bool = True,
        tools: Optional[list[str]] = None,
    ) -> Goal:
        """Cria e persiste novo Goal."""
        goal_id = f"goal_{uuid.uuid4().hex[:8]}"
        next_eval = self._calculate_next_eval(schedule)
        context = {}

        await self.memory._db.execute(
            """
            INSERT INTO goals
            (goal_id, title, description, tier, priority, schedule,
             max_actions_per_cycle, enabled, tools, created_at, next_evaluation,
             eval_count, status, context)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                goal_id, title, description, tier, priority, schedule,
                max_actions_per_cycle, enabled, json.dumps(tools or []),
                datetime.now().isoformat(), next_eval,
                0, "active", json.dumps(context)
            ),
        )
        await self.memory._db.commit()

        log.info(
            f"[goal_manager] Nova goal: {title} (tier={tier}, schedule={schedule})"
        )

        return Goal(
            goal_id=goal_id,
            title=title,
            description=description,
            tier=tier,
            priority=priority,
            schedule=schedule,
            max_actions_per_cycle=max_actions_per_cycle,
            enabled=enabled,
            tools=tools or [],
            created_at=datetime.now().isoformat(),
            last_evaluated=None,
            next_evaluation=next_eval,
            eval_count=0,
            status="active",
            context=context,
        )

    async def list_goals(self, include_disabled: bool = False) -> list[Goal]:
        """Lista todos os goals."""
        query = "SELECT * FROM goals"
        if not include_disabled:
            query += " WHERE enabled = 1"

        async with self.memory._db.execute(query) as cur:
            rows = await cur.fetchall()
            return [self._row_to_goal(row) for row in rows]

    async def get_goal(self, goal_id: str) -> Optional[Goal]:
        """Retorna um goal por ID."""
        async with self.memory._db.execute(
            "SELECT * FROM goals WHERE goal_id = ?", (goal_id,)
        ) as cur:
            row = await cur.fetchone()
            return self._row_to_goal(row) if row else None

    async def update_goal(self, goal_id: str, updates: dict) -> Optional[Goal]:
        """Atualiza campos de um goal."""
        allowed_fields = {
            "title", "description", "tier", "priority", "schedule",
            "max_actions_per_cycle", "enabled", "tools", "status"
        }
        updates = {k: v for k, v in updates.items() if k in allowed_fields}

        if not updates:
            return await self.get_goal(goal_id)

        # Prepara values
        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [goal_id]

        # Se schedule mudou, recalcula next_evaluation
        if "schedule" in updates:
            next_eval = self._calculate_next_eval(updates["schedule"])
            set_clause += ", next_evaluation = ?"
            values.insert(-1, next_eval)

        await self.memory._db.execute(
            f"UPDATE goals SET {set_clause} WHERE goal_id = ?",
            values,
        )
        await self.memory._db.commit()

        log.info(f"[goal_manager] Goal atualizado: {goal_id}")
        return await self.get_goal(goal_id)

    async def disable_goal(self, goal_id: str) -> bool:
        """Desativa um goal."""
        result = await self.update_goal(goal_id, {"enabled": False, "status": "paused"})
        return result is not None

    async def enable_goal(self, goal_id: str) -> bool:
        """Reativa um goal."""
        result = await self.update_goal(goal_id, {"enabled": True, "status": "active"})
        return result is not None

    async def delete_goal(self, goal_id: str) -> bool:
        """Remove permanentemente um goal."""
        await self.memory._db.execute("DELETE FROM goals WHERE goal_id = ?", (goal_id,))
        await self.memory._db.commit()
        log.info(f"[goal_manager] Goal removida: {goal_id}")
        return True

    async def get_due_goals(self) -> list[Goal]:
        """Retorna goals que precisam ser avaliados agora."""
        now = datetime.now().isoformat()
        query = """
            SELECT * FROM goals
            WHERE enabled = 1 AND next_evaluation IS NOT NULL AND next_evaluation <= ?
            ORDER BY priority ASC
        """
        async with self.memory._db.execute(query, (now,)) as cur:
            rows = await cur.fetchall()
            return [self._row_to_goal(row) for row in rows]

    async def get_event_goals(self, event_type: str) -> list[Goal]:
        """Retorna goals que reagem a um tipo de evento."""
        query = f"""
            SELECT * FROM goals
            WHERE enabled = 1 AND schedule LIKE 'on_event:{event_type}%'
        """
        async with self.memory._db.execute(query) as cur:
            rows = await cur.fetchall()
            return [self._row_to_goal(row) for row in rows]

    async def mark_goal_evaluated(
        self,
        goal_id: str,
        context_update: Optional[dict] = None,
    ) -> bool:
        """Marca goal como avaliado e agenda próxima avaliação."""
        goal = await self.get_goal(goal_id)
        if not goal:
            return False

        next_eval = self._calculate_next_eval(goal.schedule)
        new_context = goal.context.copy()
        if context_update:
            new_context.update(context_update)

        await self.memory._db.execute(
            """
            UPDATE goals SET
                last_evaluated = ?,
                eval_count = eval_count + 1,
                next_evaluation = ?,
                context = ?
            WHERE goal_id = ?
            """,
            (
                datetime.now().isoformat(),
                next_eval,
                json.dumps(new_context),
                goal_id,
            ),
        )
        await self.memory._db.commit()
        return True

    async def log_action(
        self,
        goal_id: str,
        action: str,
        result: str,
        tier: int,
        approved: bool = True,
    ) -> None:
        """Registra uma ação autônoma no log de auditoria."""
        await self.memory._db.execute(
            """
            INSERT INTO goal_actions_log
            (timestamp, goal_id, action, result, tier, approved)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(),
                goal_id,
                action,
                result[:2000],
                tier,
                1 if approved else 0,
            ),
        )
        await self.memory._db.commit()

    async def get_actions_log(self, limit: int = 20) -> list[dict]:
        """Retorna as últimas N ações do log."""
        query = """
            SELECT timestamp, goal_id, action, result, tier, approved
            FROM goal_actions_log
            ORDER BY timestamp DESC
            LIMIT ?
        """
        async with self.memory._db.execute(query, (limit,)) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

    async def count_recent_actions(self, goal_id: str, hours: int = 1) -> int:
        """Conta ações recentes de um goal (para rate limiting)."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        query = """
            SELECT COUNT(*) FROM goal_actions_log
            WHERE goal_id = ? AND timestamp >= ?
        """
        async with self.memory._db.execute(query, (goal_id, cutoff)) as cur:
            result = await cur.fetchone()
            return result[0] if result else 0

    async def emergency_stop(self) -> int:
        """Kill switch: desativa TODOS os goals."""
        self._kill_switch = True
        await self.memory._db.execute(
            "UPDATE goals SET enabled = 0, status = 'emergency_stop' WHERE enabled = 1"
        )
        count = await self._db.execute(
            "SELECT COUNT(*) FROM goal_actions_log WHERE timestamp >= ?",
            (datetime.now().isoformat(),)
        )
        await self.memory._db.commit()
        log.critical("[goal_manager] ⚠️ EMERGENCY STOP ATIVADO")
        return count

    def _calculate_next_eval(self, schedule: str) -> Optional[str]:
        """Calcula próxima avaliação baseada no schedule."""
        now = datetime.now()

        if schedule.startswith("on_event:"):
            return None  # Event-driven

        if schedule.startswith("every "):
            val_str = schedule.replace("every ", "")
            if val_str.endswith("m"):
                minutes = int(val_str[:-1])
                return (now + timedelta(minutes=minutes)).isoformat()
            elif val_str.endswith("h"):
                hours = int(val_str[:-1])
                return (now + timedelta(hours=hours)).isoformat()

        if schedule.startswith("daily "):
            time_str = schedule.replace("daily ", "")
            try:
                hour, minute = map(int, time_str.split(":"))
                next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
                return next_run.isoformat()
            except ValueError:
                pass

        # Fallback
        log.warning(f"[goal_manager] Schedule desconhecido: '{schedule}'. Usando fallback 1h")
        return (now + timedelta(hours=1)).isoformat()

    def _row_to_goal(self, row) -> Goal:
        """Converte row do DB para Goal object."""
        return Goal(
            goal_id=row["goal_id"],
            title=row["title"],
            description=row["description"],
            tier=row["tier"],
            priority=row["priority"],
            schedule=row["schedule"],
            max_actions_per_cycle=row["max_actions_per_cycle"],
            enabled=bool(row["enabled"]),
            tools=json.loads(row["tools"] or "[]"),
            created_at=row["created_at"],
            last_evaluated=row["last_evaluated"],
            next_evaluation=row["next_evaluation"],
            eval_count=row["eval_count"],
            status=row["status"],
            context=json.loads(row["context"] or "{}"),
        )
