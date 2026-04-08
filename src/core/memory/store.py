"""
Seeker.Bot — Memory Storage
src/core/memory/store.py

Implementação SQLite do MemoryProtocol.

Quatro tabelas:
  episodic         — eventos: o que aconteceu, quando, com que contexto
  semantic         — fatos: o que o Seeker aprendeu sobre o mundo e o usuário
  fact_embeddings  — vetores: embeddings persistidos (sobrevivem a restart)
  session_turns    — conversa: janela deslizante com persistência

Zero dependências pesadas: aiosqlite + stdlib.
"""

import aiosqlite
import json
import logging
import os
import time

log = logging.getLogger("seeker.memory.store")

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data", "seeker_memory.db"
)

SCHEMA = """
-- ─── EPISÓDICA ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS episodic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    session_id TEXT NOT NULL,
    user_input TEXT NOT NULL,
    response_summary TEXT DEFAULT '',
    depth TEXT DEFAULT 'deliberate',
    module TEXT DEFAULT 'none',
    had_arbitrage INTEGER DEFAULT 0,
    had_conflicts INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    latency_ms INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_episodic_timestamp ON episodic(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_episodic_session ON episodic(session_id);

-- ─── SEMÂNTICA ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS semantic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact TEXT NOT NULL UNIQUE,
    category TEXT DEFAULT 'general',
    confidence REAL DEFAULT 0.5,
    source TEXT DEFAULT 'inferred',
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    times_seen INTEGER DEFAULT 1,
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_semantic_category ON semantic(category);
CREATE INDEX IF NOT EXISTS idx_semantic_confidence ON semantic(confidence DESC);

-- ─── EMBEDDINGS ────────────────────────────────────────────
-- Persistidos: sobrevivem a restart sem re-chamar API
CREATE TABLE IF NOT EXISTS fact_embeddings (
    fact_id INTEGER PRIMARY KEY,
    vector TEXT NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (fact_id) REFERENCES semantic(id) ON DELETE CASCADE
);

-- ─── SESSÃO ────────────────────────────────────────────────
-- Janela deslizante: continuidade entre mensagens
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

-- ─── USER PREFERENCES ──────────────────────────────────────
-- Armazena preferências do usuário (ex: nichos para SenseNews)
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER PRIMARY KEY,
    telegram_id TEXT,
    niches TEXT,         -- JSON array ['MODELOS & OPEN-WEIGHT', 'INFRA & OTIMIZAÇÃO', ...]
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_preferences_telegram ON user_preferences(telegram_id);

-- ─── GOAL CYCLE HISTORY ─────────────────────────────────────
-- Rastreia saúde dos goals (últimas 20 execuções por goal)
CREATE TABLE IF NOT EXISTS goal_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_name TEXT NOT NULL,
    timestamp REAL NOT NULL,
    success INTEGER DEFAULT 1,
    cost_usd REAL DEFAULT 0.0,
    latency_ms INTEGER DEFAULT 0,
    summary TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_goal_cycles_name ON goal_cycles(goal_name, timestamp DESC);
"""


class MemoryStore:
    """
    Implementação SQLite do MemoryProtocol.
    
    Uso:
        store = MemoryStore()
        await store.initialize()
        fact_id = await store.upsert_fact(fact="Python 3.10", category="tech_context")
        await store.store_embedding(fact_id, [0.1, 0.2, ...])
        await store.close()
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        try:
            self._db.row_factory = aiosqlite.Row

            # PRAGMA pra performance — WAL mode permite reads concorrentes
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA foreign_keys=ON")

            await self._db.executescript(SCHEMA)
            await self._db.commit()
        except Exception:
            await self._db.close()
            self._db = None
            raise

        # Log estado inicial
        async with self._db.execute("SELECT COUNT(*) FROM episodic") as cur:
            ep_count = (await cur.fetchone())[0]
        async with self._db.execute("SELECT COUNT(*) FROM semantic") as cur:
            sem_count = (await cur.fetchone())[0]
        async with self._db.execute("SELECT COUNT(*) FROM fact_embeddings") as cur:
            emb_count = (await cur.fetchone())[0]

        log.info(
            f"[memory] DB: {self.db_path} | "
            f"{ep_count} episódios, {sem_count} fatos, {emb_count} embeddings"
        )

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ─── EPISÓDICA ────────────────────────────────────────────

    async def record_episode(
        self,
        *,
        session_id: str,
        user_input: str,
        response_summary: str = "",
        depth: str = "deliberate",
        module: str = "none",
        had_arbitrage: bool = False,
        had_conflicts: bool = False,
        cost_usd: float = 0.0,
        latency_ms: int = 0,
        metadata: dict | None = None,
        _batch: bool = False,
    ) -> None:
        await self._db.execute(
            """INSERT INTO episodic
            (timestamp, session_id, user_input, response_summary, depth,
             module, had_arbitrage, had_conflicts, cost_usd, latency_ms, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(), session_id, user_input, response_summary[:500],
                depth, module, int(had_arbitrage), int(had_conflicts),
                cost_usd, latency_ms, json.dumps(metadata or {}),
            ),
        )
        if not _batch:
            await self._db.commit()

    async def get_recent_episodes(self, limit: int = 10) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM episodic ORDER BY timestamp DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def search_episodes(self, query: str, limit: int = 5) -> list[dict]:
        async with self._db.execute(
            """SELECT * FROM episodic 
            WHERE user_input LIKE ? OR response_summary LIKE ?
            ORDER BY timestamp DESC LIMIT ?""",
            (f"%{query}%", f"%{query}%", limit),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def get_episode_stats(self) -> dict:
        stats = {}
        async with self._db.execute("SELECT COUNT(*) FROM episodic") as cur:
            stats["total_episodes"] = (await cur.fetchone())[0]
        async with self._db.execute("SELECT SUM(cost_usd) FROM episodic") as cur:
            stats["total_cost_usd"] = (await cur.fetchone())[0] or 0.0
        async with self._db.execute("SELECT AVG(latency_ms) FROM episodic") as cur:
            stats["avg_latency_ms"] = int((await cur.fetchone())[0] or 0)
        async with self._db.execute(
            "SELECT depth, COUNT(*) as cnt FROM episodic GROUP BY depth"
        ) as cur:
            stats["by_depth"] = {row["depth"]: row["cnt"] for row in await cur.fetchall()}
        return stats

    # ─── SEMÂNTICA ────────────────────────────────────────────

    async def upsert_fact(
        self,
        *,
        fact: str,
        category: str = "general",
        confidence: float = 0.5,
        source: str = "inferred",
        metadata: dict | None = None,
        _batch: bool = False,
    ) -> int:
        """
        Insere ou atualiza um fato. Retorna o fact_id.
        
        Isso elimina o hack anterior de search-after-insert que existia
        no pipeline.py:192 para descobrir o ID do fato recém inserido.
        """
        now = time.time()
        meta_json = json.dumps(metadata or {})
        fact_clean = fact.strip()

        try:
            await self._db.execute(
                """INSERT INTO semantic (fact, category, confidence, source, first_seen, last_seen, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fact) DO UPDATE SET
                    times_seen = times_seen + 1,
                    last_seen = ?,
                    confidence = MIN(0.95, confidence + 0.05),
                    metadata = ?""",
                (
                    fact_clean, category, confidence, source,
                    now, now, meta_json,
                    now, meta_json,
                ),
            )
            if not _batch:
                await self._db.commit()

            # Retorna o ID (INSERT ou UPDATE — ambos funcionam com essa query)
            async with self._db.execute(
                "SELECT id FROM semantic WHERE fact = ?", (fact_clean,)
            ) as cur:
                row = await cur.fetchone()
                return row["id"] if row else -1

        except Exception as e:
            log.warning(f"[memory] Falha ao salvar fato: {e}")
            return -1

    async def get_facts(
        self,
        category: str | None = None,
        min_confidence: float = 0.3,
        limit: int = 20,
    ) -> list[dict]:
        if category:
            query = """SELECT * FROM semantic 
                WHERE category = ? AND confidence >= ?
                ORDER BY confidence DESC, last_seen DESC LIMIT ?"""
            params = (category, min_confidence, limit)
        else:
            query = """SELECT * FROM semantic 
                WHERE confidence >= ?
                ORDER BY confidence DESC, last_seen DESC LIMIT ?"""
            params = (min_confidence, limit)
        async with self._db.execute(query, params) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def search_facts(self, query: str, limit: int = 10) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM semantic WHERE fact LIKE ? ORDER BY confidence DESC LIMIT ?",
            (f"%{query}%", limit),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def update_fact_confidence(self, fact_id: int, confidence: float) -> None:
        """
        Atualiza confiança de um fato específico.
        
        Usado pelo DecayEngine — substitui o acesso direto a _db
        que existia antes (self.memory._db.execute).
        """
        await self._db.execute(
            "UPDATE semantic SET confidence = ? WHERE id = ?",
            (confidence, fact_id),
        )
        # Commit feito em batch pelo chamador (DecayEngine.run)

    async def delete_fact(self, fact_id: int) -> None:
        """
        Remove fato + embedding associado (cascade).
        
        O ON DELETE CASCADE na FK de fact_embeddings garante
        que o embedding é removido junto, mas fazemos explícito
        por segurança (nem toda migração preserva FKs).
        """
        await self._db.execute("DELETE FROM fact_embeddings WHERE fact_id = ?", (fact_id,))
        await self._db.execute("DELETE FROM semantic WHERE id = ?", (fact_id,))
        # Commit feito em batch pelo chamador

    async def commit(self) -> None:
        """
        Commit explícito para operações em batch.
        
        DecayEngine e outros módulos que fazem múltiplas operações
        chamam commit() uma vez no final ao invés de por operação.
        """
        if self._db:
            await self._db.commit()

    # ─── EMBEDDINGS ───────────────────────────────────────────

    async def store_embedding(self, fact_id: int, vector: list[float]) -> None:
        """Persiste embedding no SQLite. Sobrevive a restart."""
        blob = json.dumps(vector)
        await self._db.execute(
            """INSERT OR REPLACE INTO fact_embeddings (fact_id, vector, updated_at)
            VALUES (?, ?, ?)""",
            (fact_id, blob, time.time()),
        )
        await self._db.commit()

    async def load_all_embeddings(self) -> dict[int, list[float]]:
        """
        Carrega todos os embeddings de uma vez no startup.
        
        Performance:
          100 fatos  → ~5ms
          1.000      → ~20ms
          5.000      → ~80ms
          50.000     → ~800ms (hora de considerar formato binário)
        """
        async with self._db.execute("SELECT fact_id, vector FROM fact_embeddings") as cur:
            rows = await cur.fetchall()

        result = {}
        for row in rows:
            try:
                result[row["fact_id"]] = json.loads(row["vector"])
            except (json.JSONDecodeError, TypeError):
                log.warning(f"[memory] Embedding corrompido para fact_id={row['fact_id']}")
        return result

    async def delete_embedding(self, fact_id: int) -> None:
        """Remove embedding de um fato."""
        await self._db.execute(
            "DELETE FROM fact_embeddings WHERE fact_id = ?", (fact_id,)
        )
        await self._db.commit()

    # ─── SESSÃO ───────────────────────────────────────────────

    async def record_session_turn(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """Registra uma mensagem na sessão ativa."""
        await self._db.execute(
            """INSERT INTO session_turns (session_id, timestamp, role, content, metadata)
            VALUES (?, ?, ?, ?, ?)""",
            (session_id, time.time(), role, content[:2000], json.dumps(metadata or {})),
        )
        await self._db.commit()

    async def get_session_turns(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """Últimas N mensagens da sessão, retornadas em ordem cronológica."""
        async with self._db.execute(
            """SELECT * FROM session_turns
            WHERE session_id = ?
            ORDER BY timestamp DESC LIMIT ?""",
            (session_id, limit),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        return list(reversed(rows))  # Cronológico (mais antiga primeiro)

    async def cleanup_old_sessions(self, max_age_days: int = 30) -> int:
        """
        Remove sessões antigas.
        Roda junto com o DecayEngine no ciclo periódico.
        Retorna quantidade de turns removidas.
        """
        cutoff = time.time() - (max_age_days * 86400)
        cursor = await self._db.execute(
            "DELETE FROM session_turns WHERE timestamp < ?", (cutoff,)
        )
        removed = cursor.rowcount
        await self._db.commit()
        if removed > 0:
            log.info(f"[memory] Sessões: {removed} turns antigas removidas")
        return removed

    # ─── CONTEXTO PARA O LLM ─────────────────────────────────

    async def format_context(self, query: str = "", limit: int = 10) -> str:
        """
        Formata memória semântica + episódios recentes como contexto textual
        para injetar no system prompt do LLM.
        """
        lines = []

        facts = await self.get_facts(min_confidence=0.4, limit=limit)
        
        # Filtra Memory Reflexiva pra destaque
        reflexive = [f for f in facts if f.get("category") == "reflexive_rule"]
        others = [f for f in facts if f.get("category") != "reflexive_rule"]
        
        if reflexive:
            lines.append("=== REGRAS DE COMPORTAMENTO EXIGIDAS PELO USUÁRIO ===")
            for f in reflexive:
                lines.append(f"-> OBRIGATÓRIO: {f['fact']}")
            lines.append("")

        if others:
            lines.append("=== MEMÓRIA SEMÂNTICA ===")
            for f in others:
                lines.append(f"[{f['confidence']:.0%}] {f['fact']} ({f['category']})")
            lines.append("")

        episodes = await self.get_recent_episodes(limit=5)
        if episodes:
            lines.append("=== INTERAÇÕES RECENTES ===")
            for ep in episodes:
                icon = {"reflex": "⚡", "deliberate": "🧠", "deep": "🔬"}.get(ep["depth"], "")
                lines.append(f"{icon} {ep['user_input'][:100]}")
                if ep["response_summary"]:
                    lines.append(f"   → {ep['response_summary'][:100]}")
            lines.append("")

        if query:
            relevant = await self.search_facts(query, limit=5)
            if relevant:
                seen_ids = {f["id"] for f in facts}
                new_facts = [f for f in relevant if f["id"] not in seen_ids]
                if new_facts:
                    lines.append("=== FATOS RELEVANTES PARA ESTA QUERY ===")
                    for f in new_facts:
                        lines.append(f"[{f['confidence']:.0%}] {f['fact']}")

        return "\n".join(lines) if lines else ""

    # ─── USER PREFERENCES ──────────────────────────────────────

    async def get_user_niches(self, user_id: int | str) -> list[str] | None:
        """
        Retorna lista de nichos escolhidos pelo usuário para SenseNews.
        Se o usuário não tem preferências registradas, retorna None.
        """
        if not self._db:
            return None

        # Se user_id é uma string (Telegram ID), converte para int se possível
        if isinstance(user_id, str):
            try:
                user_id = int(user_id)
            except ValueError:
                return None

        async with self._db.execute(
            "SELECT niches FROM user_preferences WHERE user_id = ? OR telegram_id = ?",
            (user_id, str(user_id))
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None

            try:
                niches = json.loads(row['niches'])
                return niches if isinstance(niches, list) else None
            except (json.JSONDecodeError, TypeError):
                return None

    async def set_user_niches(self, user_id: int, telegram_id: str, niches: list[str]) -> bool:
        """
        Salva nichos escolhidos pelo usuário.
        """
        if not self._db:
            return False

        try:
            await self._db.execute(
                """
                INSERT INTO user_preferences (user_id, telegram_id, niches, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    niches = excluded.niches,
                    updated_at = excluded.updated_at
                """,
                (user_id, telegram_id, json.dumps(niches), time.time())
            )
            await self._db.commit()
            return True
        except Exception as e:
            log.error(f"Falha ao salvar preferências do usuário {user_id}: {e}")
            return False

    # ─── LEGACY COMPAT ────────────────────────────────────────
    # Método antigo mantido pra não quebrar nada durante a transição.
    # Será removido quando todos os módulos usarem o Protocol.

    async def decay_old_facts(self, max_age_days: int = 90, decay_rate: float = 0.1):
        """DEPRECATED: Use DecayEngine com update_fact_confidence/delete_fact."""
        cutoff = time.time() - (max_age_days * 86400)
        await self._db.execute(
            "UPDATE semantic SET confidence = MAX(0.1, confidence - ?) "
            "WHERE last_seen < ? AND confidence > 0.1",
            (decay_rate, cutoff),
        )
        await self._db.execute(
            "DELETE FROM semantic WHERE confidence <= 0.1 AND last_seen < ?", (cutoff,),
        )
        await self._db.commit()
