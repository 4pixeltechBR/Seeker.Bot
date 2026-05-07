"""
Seeker.Bot — Session Storage (Decoupled)
src/core/memory/session_store.py

Implementação SQLite para persistência de sessões em arquivo SEPARADO.
Isso evita lock-contention com a memória semântica/episódica.
"""

import aiosqlite
import json
import logging
import os
import time

log = logging.getLogger("seeker.memory.session_store")

DEFAULT_SESSION_DB_PATH = os.path.join(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
    "data",
    "seeker_session.db",
)

SCHEMA = """
-- ─── SESSÃO ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS session_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_session_turns_lookup
    ON session_turns(session_id, timestamp DESC);

-- ─── RESUMOS ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS session_summaries (
    session_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


class SessionStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DEFAULT_SESSION_DB_PATH
        self._db: aiosqlite.Connection | None = None
        self._initialized = False

    async def init(self):
        if self._initialized:
            return

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        self._initialized = True
        log.info(f"[session_store] DB inicializado em {self.db_path}")

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None
            self._initialized = False

    async def get_summary(self, session_id: str) -> str | None:
        """Carrega resumo persistido da sessão."""
        if not self._initialized:
            await self.init()
        async with self._db.execute(
            "SELECT summary FROM session_summaries WHERE session_id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
            return row["summary"] if row else None

    async def store_summary(self, session_id: str, summary: str) -> None:
        """Salva resumo persistido da sessão."""
        if not self._initialized:
            await self.init()
        await self._db.execute(
            "INSERT OR REPLACE INTO session_summaries (session_id, summary, updated_at) VALUES (?, ?, ?)",
            (session_id, summary, time.time()),
        )
        await self._db.commit()

    async def record_session_turn(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """Registra uma mensagem na sessão ativa."""
        if not self._initialized:
            await self.init()

        await self._db.execute(
            """INSERT INTO session_turns (session_id, timestamp, role, content, metadata)
            VALUES (?, ?, ?, ?, ?)""",
            (session_id, time.time(), role, content[:2000], json.dumps(metadata or {})),
        )
        await self._db.commit()

    async def get_session_turns(
        self,
        session_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """Últimas N mensagens da sessão, retornadas em ordem cronológica inversa."""
        if not self._initialized:
            await self.init()

        async with self._db.execute(
            """SELECT * FROM session_turns
            WHERE session_id = ?
            ORDER BY timestamp DESC LIMIT ?""",
            (session_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def delete_session(self, session_id: str) -> None:
        """Remove todo o histórico de uma sessão."""
        if not self._initialized:
            await self.init()
        await self._db.execute(
            "DELETE FROM session_turns WHERE session_id = ?", (session_id,)
        )
        await self._db.commit()
