"""SQLite local. Cada conversa, cada texto e cada passo ficam neste arquivo."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from seeker.transcript import Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    due_at TEXT NOT NULL,
    repeat TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_fired_at TEXT
);
CREATE TABLE IF NOT EXISTS routines (
    id TEXT PRIMARY KEY,
    instruction TEXT NOT NULL,
    due_at TEXT NOT NULL,
    repeat TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_run_at TEXT
);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suggestions (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    day TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notices (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    seen INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_chat(self, title: str = "Nova conversa") -> dict:
        chat_id = uuid.uuid4().hex
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO chats (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (chat_id, title, now, now),
            )
        return {"id": chat_id, "title": title, "created_at": now, "updated_at": now}

    def list_chats(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM chats ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_chat(self, chat_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, title, created_at, updated_at FROM chats WHERE id = ?",
                (chat_id,),
            ).fetchone()
        return dict(row) if row else None

    def rename(self, chat_id: str, title: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))

    def maybe_retitle(self, chat_id: str, text: str) -> str | None:
        chat = self.get_chat(chat_id)
        if chat is None or chat["title"] != "Nova conversa":
            return None
        title = " ".join(text.split())[:48] or "Nova conversa"
        if title == "Nova conversa":
            return None
        self.rename(chat_id, title)
        return title

    def rewrite_secrets(self, clean) -> int:
        columns = (
            ("messages", "content"),
            ("chats", "title"),
            ("events", "detail"),
            ("memories", "text"),
            ("notices", "text"),
            ("suggestions", "text"),
            ("tasks", "title"),
            ("routines", "instruction"),
        )
        count = 0
        with self._conn() as conn:
            for table, column in columns:
                rows = conn.execute(f"SELECT id, {column} AS value FROM {table}").fetchall()
                for row in rows:
                    raw = row["value"] or ""
                    cleaned = clean(raw)
                    if cleaned != raw:
                        conn.execute(f"UPDATE {table} SET {column} = ? WHERE id = ?", (cleaned, row["id"]))
                        count += 1
        return count

    def add_message(self, chat_id: str, role: str, content: str) -> str:
        message_id = uuid.uuid4().hex
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages (id, chat_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (message_id, chat_id, role, content, now),
            )
            conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
        return message_id

    def messages(self, chat_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, role, content, created_at FROM messages
                WHERE chat_id = ? ORDER BY created_at, rowid
                """,
                (chat_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def all_messages(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages ORDER BY created_at, rowid"
            ).fetchall()
        return [dict(row) for row in rows]

    def transcript(self, chat_id: str, limit: int = 40) -> list[Message]:
        rows = self.messages(chat_id)[-limit:]
        return [Message(role=row["role"], content=row["content"]) for row in rows]

    def add_event(self, chat_id: str, label: str, status: str, detail: str) -> str:
        event_id = uuid.uuid4().hex
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO events (id, chat_id, label, status, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, chat_id, label, status, detail, _now()),
            )
        return event_id

    def update_event(self, event_id: str, status: str, detail: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE events SET status = ?, detail = ? WHERE id = ?",
                (status, detail, event_id),
            )

    def events(self, chat_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, label, status, detail, created_at FROM events
                WHERE chat_id = ? ORDER BY created_at, rowid
                """,
                (chat_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_task(self, title: str, due_at: str, repeat: str) -> dict:
        task_id = uuid.uuid4().hex[:8]
        now = _now()
        with self._conn() as conn:
            while conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone():
                task_id = uuid.uuid4().hex[:8]
            conn.execute(
                """
                INSERT INTO tasks (id, title, due_at, repeat, status, created_at, last_fired_at)
                VALUES (?, ?, ?, ?, 'pending', ?, NULL)
                """,
                (task_id, title.strip(), due_at, repeat, now),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def pending_tasks(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending' ORDER BY due_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def find_task(self, query: str) -> dict | None:
        text = (query or "").strip().casefold()
        if not text:
            return None
        pending = self.pending_tasks()
        for task in pending:
            if task["id"] == text or task["id"].startswith(text):
                return task
        hits = [task for task in pending if text in task["title"].casefold()]
        if len(hits) == 1:
            return hits[0]
        return None

    def update_task(self, task_id: str, **fields: object) -> None:
        if not fields:
            return
        columns = ", ".join(f"{key} = ?" for key in fields)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE tasks SET {columns} WHERE id = ?",
                (*fields.values(), task_id),
            )

    def add_routine(self, instruction: str, due_at: str, repeat: str) -> dict:
        routine_id = uuid.uuid4().hex[:8]
        now = _now()
        with self._conn() as conn:
            while conn.execute("SELECT 1 FROM routines WHERE id = ?", (routine_id,)).fetchone():
                routine_id = uuid.uuid4().hex[:8]
            conn.execute(
                """
                INSERT INTO routines (id, instruction, due_at, repeat, status, created_at, last_run_at)
                VALUES (?, ?, ?, ?, 'active', ?, NULL)
                """,
                (routine_id, instruction.strip(), due_at, repeat, now),
            )
        return self.get_routine(routine_id)

    def get_routine(self, routine_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
        return dict(row) if row else None

    def active_routines(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM routines WHERE status = 'active' ORDER BY due_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def update_routine(self, routine_id: str, **fields: object) -> None:
        if not fields:
            return
        columns = ", ".join(f"{key} = ?" for key in fields)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE routines SET {columns} WHERE id = ?",
                (*fields.values(), routine_id),
            )

    def add_memory(self, text: str) -> dict | None:
        clean = " ".join(text.split())
        if not clean:
            return None
        existing = self.memories()
        if any(item["text"].casefold() == clean.casefold() for item in existing):
            return None
        memory_id = uuid.uuid4().hex[:8]
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO memories (id, text, created_at) VALUES (?, ?, ?)",
                (memory_id, clean, now),
            )
        return {"id": memory_id, "text": clean, "created_at": now}

    def memories(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, text, created_at FROM memories ORDER BY created_at, rowid"
            ).fetchall()
        return [dict(row) for row in rows]

    def forget_memory(self, query: str) -> int:
        text = (query or "").strip().casefold()
        if not text:
            return 0
        gone = [item["id"] for item in self.memories() if text in item["text"].casefold()]
        with self._conn() as conn:
            for memory_id in gone:
                conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return len(gone)

    def add_suggestion(self, kind: str, text: str, day: str) -> dict:
        suggestion_id = uuid.uuid4().hex[:8]
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO suggestions (id, kind, text, status, day, created_at)
                VALUES (?, ?, ?, 'open', ?, ?)
                """,
                (suggestion_id, kind, text, day, now),
            )
        return {"id": suggestion_id, "kind": kind, "text": text, "status": "open", "day": day}

    def open_suggestions(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, kind, text, status, day FROM suggestions
                WHERE status = 'open' ORDER BY created_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def suggestion_blocked(self, kind: str, day: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM suggestions
                WHERE kind = ? AND day = ? AND status IN ('dismissed', 'accepted', 'open')
                """,
                (kind, day),
            ).fetchone()
        return row is not None

    def set_suggestion_status(self, suggestion_id: str, status: str) -> dict | None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE suggestions SET status = ? WHERE id = ?",
                (status, suggestion_id),
            )
            row = conn.execute(
                "SELECT id, kind, text, status, day FROM suggestions WHERE id = ?",
                (suggestion_id,),
            ).fetchone()
        return dict(row) if row else None

    def add_notice(self, text: str) -> dict:
        notice_id = uuid.uuid4().hex[:8]
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO notices (id, text, created_at, seen) VALUES (?, ?, ?, 0)",
                (notice_id, text, now),
            )
        return {"id": notice_id, "text": text, "created_at": now, "seen": 0}

    def unseen_notices(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, text, created_at FROM notices WHERE seen = 0 ORDER BY created_at, rowid"
            ).fetchall()
        return [dict(row) for row in rows]

    def ack_notices(self, ids: list[str]) -> None:
        with self._conn() as conn:
            for notice_id in ids:
                conn.execute("UPDATE notices SET seen = 1 WHERE id = ?", (notice_id,))

    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
