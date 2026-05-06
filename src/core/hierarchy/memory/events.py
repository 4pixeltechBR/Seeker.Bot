"""
Event Sourcing for Seeker.Bot v1.0 Hierarchy

Immutable event log for distributed consistency, crash recovery, and audit trail.
"""

import json
import sqlite3
from datetime import datetime
from typing import Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import logging

log = logging.getLogger("seeker.hierarchy.events")


class GoalEventType(str, Enum):
    """Event types in goal execution lifecycle"""
    STARTED = "started"
    API_CALL = "api_call"
    FACT_LEARNED = "fact_learned"
    RESULT_READY = "result_ready"
    ERROR = "error"
    COMPLETED = "completed"


@dataclass
class GoalEvent:
    """Single immutable event in goal execution"""
    event_id: int
    goal_id: str
    crew_id: str
    event_type: GoalEventType
    timestamp: float
    payload: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "goal_id": self.goal_id,
            "crew_id": self.crew_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "payload": json.dumps(self.payload),
        }


class GoalEventLog:
    """Event sourcing log for distributed consistency"""

    def __init__(self, db_path: str = "data/seeker_data.db"):
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self):
        """Create events table if not exists"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS goal_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id TEXT NOT NULL,
                    crew_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    payload TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(goal_id, event_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_goal_timestamp
                ON goal_events(goal_id, timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_crew
                ON goal_events(crew_id, timestamp DESC)
            """)
            conn.commit()

    async def append_event(
        self,
        goal_id: str,
        crew_id: str,
        event_type: GoalEventType,
        payload: dict[str, Any],
    ) -> int:
        """Append immutable event to log"""
        timestamp = datetime.utcnow().timestamp()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO goal_events (goal_id, crew_id, event_type, timestamp, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (goal_id, crew_id, event_type.value, timestamp, json.dumps(payload)),
            )
            conn.commit()
            event_id = cursor.lastrowid
            log.debug(f"Event appended: {goal_id}:{event_id} ({event_type.value})")
            return event_id

    async def get_events_for_goal(
        self, goal_id: str, start_time: Optional[float] = None
    ) -> list[GoalEvent]:
        """Retrieve all events for a goal (ordered by timestamp)"""
        with sqlite3.connect(self.db_path) as conn:
            query = "SELECT * FROM goal_events WHERE goal_id = ?"
            params = [goal_id]

            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time)

            query += " ORDER BY timestamp ASC"

            rows = conn.execute(query, params).fetchall()
            events = [
                GoalEvent(
                    event_id=row[0],
                    goal_id=row[1],
                    crew_id=row[2],
                    event_type=GoalEventType(row[3]),
                    timestamp=row[4],
                    payload=json.loads(row[5]),
                )
                for row in rows
            ]
            return events

    async def get_events_for_crew(
        self, crew_id: str, limit: int = 100
    ) -> list[GoalEvent]:
        """Retrieve recent events for a crew (for monitoring)"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM goal_events
                WHERE crew_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (crew_id, limit),
            ).fetchall()
            events = [
                GoalEvent(
                    event_id=row[0],
                    goal_id=row[1],
                    crew_id=row[2],
                    event_type=GoalEventType(row[3]),
                    timestamp=row[4],
                    payload=json.loads(row[5]),
                )
                for row in reversed(rows)
            ]
            return events

    async def replay_goal_state(self, goal_id: str) -> dict[str, Any]:
        """Reconstruct goal state by replaying all events"""
        events = await self.get_events_for_goal(goal_id)

        state = {
            "goal_id": goal_id,
            "started_at": None,
            "last_api_call": None,
            "facts_learned": [],
            "error_count": 0,
            "completed": False,
            "final_result": None,
        }

        for event in events:
            if event.event_type == GoalEventType.STARTED:
                state["started_at"] = event.timestamp

            elif event.event_type == GoalEventType.API_CALL:
                state["last_api_call"] = event.payload.get("provider")

            elif event.event_type == GoalEventType.FACT_LEARNED:
                state["facts_learned"].append(event.payload.get("fact"))

            elif event.event_type == GoalEventType.ERROR:
                state["error_count"] += 1

            elif event.event_type == GoalEventType.COMPLETED:
                state["completed"] = True
                state["final_result"] = event.payload.get("result")

        return state

    async def cleanup_old_events(self, days_old: int = 30):
        """Archive/remove events older than N days"""
        import time

        cutoff_time = time.time() - (days_old * 86400)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM goal_events WHERE timestamp < ?",
                (cutoff_time,),
            )
            count = cursor.fetchone()[0]

            # Archive to separate table (optional)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS goal_events_archive AS
                SELECT * FROM goal_events WHERE timestamp < ?
                """,
                (cutoff_time,),
            )

            # Delete old events
            conn.execute(
                "DELETE FROM goal_events WHERE timestamp < ?", (cutoff_time,)
            )
            conn.commit()

            log.info(f"Archived and deleted {count} events older than {days_old} days")
