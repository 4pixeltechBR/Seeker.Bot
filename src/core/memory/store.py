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
CREATE INDEX IF NOT EXISTS idx_semantic_category_confidence ON semantic(category, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_semantic_last_seen ON semantic(last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_semantic_fact ON semantic(fact);

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

-- ─── ENTIDADES ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT DEFAULT 'unknown',
    properties TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ─── KNOWLEDGE GRAPH (TRIPLES) ──────────────────────────────
CREATE TABLE IF NOT EXISTS knowledge_triples (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    confidence REAL DEFAULT 1.0,
    source_closet TEXT,
    source_file TEXT,
    source_drawer_id TEXT,
    adapter_name TEXT,
    extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject) REFERENCES entities(id),
    FOREIGN KEY (object) REFERENCES entities(id)
);

CREATE INDEX IF NOT EXISTS idx_triples_subject ON knowledge_triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_object ON knowledge_triples(object);
CREATE INDEX IF NOT EXISTS idx_triples_predicate ON knowledge_triples(predicate);
CREATE INDEX IF NOT EXISTS idx_triples_valid ON knowledge_triples(valid_from, valid_to);

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
        Carrega IDs de todos os embeddings (lazy loading).

        Performance:
          100 fatos  → ~5ms
          1.000      → ~20ms
          5.000      → ~80ms
          50.000     → ~800ms (hora de considerar formato binário)
        """
        async with self._db.execute("SELECT fact_id FROM fact_embeddings") as cur:
            rows = await cur.fetchall()
        # Retorna dict vazio (só usamos para saber quais IDs existem)
        return {row["fact_id"]: [] for row in rows}

    async def load_embedding(self, fact_id: int) -> list[float] | None:
        """Carrega um embedding individual (lazy load sob demanda)."""
        try:
            async with self._db.execute(
                "SELECT vector FROM fact_embeddings WHERE fact_id = ?", (fact_id,)
            ) as cur:
                row = await cur.fetchone()
                if row:
                    return json.loads(row["vector"])
        except (json.JSONDecodeError, TypeError):
            log.warning(f"[memory] Embedding corrompido para fact_id={fact_id}")
        return None

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

    # ─── KNOWLEDGE GRAPH ──────────────────────────────────────

    def _entity_id(self, name: str) -> str:
        """Gera um ID normalizado para uma entidade."""
        return name.lower().strip().replace(" ", "_").replace("'", "").replace('"', "")

    async def add_entity(self, name: str, entity_type: str = "unknown", properties: dict | None = None) -> str:
        eid = self._entity_id(name)
        props_json = json.dumps(properties or {})
        await self._db.execute(
            "INSERT OR REPLACE INTO entities (id, name, type, properties) VALUES (?, ?, ?, ?)",
            (eid, name, entity_type, props_json)
        )
        await self._db.commit()
        return eid

    async def add_triple(
        self,
        *,
        subject: str,
        predicate: str,
        object_: str,
        valid_from: str | None = None,
        valid_to: str | None = None,
        confidence: float = 1.0,
        source_file: str | None = None,
        source_drawer_id: str | None = None,
        adapter_name: str | None = None,
    ) -> str:
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(object_)
        pred = predicate.lower().strip().replace(" ", "_")

        # Garante que entidades existem
        await self._db.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (sub_id, subject))
        await self._db.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (obj_id, object_))

        # Check se já existe idêntico e válido
        async with self._db.execute(
            "SELECT id FROM knowledge_triples WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
            (sub_id, pred, obj_id)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return row["id"]

        import hashlib
        triple_id = f"t_{sub_id}_{pred}_{obj_id}_{hashlib.sha256(f'{valid_from}{time.time()}'.encode()).hexdigest()[:12]}"

        await self._db.execute(
            """INSERT INTO knowledge_triples (
                id, subject, predicate, object,
                valid_from, valid_to, confidence,
                source_file, source_drawer_id, adapter_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (triple_id, sub_id, pred, obj_id, valid_from, valid_to, confidence, source_file, source_drawer_id, adapter_name)
        )
        await self._db.commit()
        return triple_id

    async def invalidate_triple(self, subject: str, predicate: str, object_: str, ended: str | None = None) -> None:
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(object_)
        pred = predicate.lower().strip().replace(" ", "_")
        ended = ended or time.strftime("%Y-%m-%d")

        await self._db.execute(
            "UPDATE knowledge_triples SET valid_to=? WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
            (ended, sub_id, pred, obj_id)
        )
        await self._db.commit()

    async def query_knowledge(self, entity_name: str, as_of: str | None = None, direction: str = "outgoing") -> list[dict]:
        eid = self._entity_id(entity_name)
        results = []

        if direction in ("outgoing", "both"):
            query = "SELECT t.*, e.name as obj_name FROM knowledge_triples t JOIN entities e ON t.object = e.id WHERE t.subject = ?"
            params = [eid]
            if as_of:
                query += " AND (t.valid_from IS NULL OR t.valid_from <= ?) AND (t.valid_to IS NULL OR t.valid_to >= ?)"
                params.extend([as_of, as_of])
            async with self._db.execute(query, params) as cur:
                for row in await cur.fetchall():
                    d = dict(row)
                    d["direction"] = "outgoing"
                    results.append(d)

        if direction in ("incoming", "both"):
            query = "SELECT t.*, e.name as sub_name FROM knowledge_triples t JOIN entities e ON t.subject = e.id WHERE t.object = ?"
            params = [eid]
            if as_of:
                query += " AND (t.valid_from IS NULL OR t.valid_from <= ?) AND (t.valid_to IS NULL OR t.valid_to >= ?)"
                params.extend([as_of, as_of])
            async with self._db.execute(query, params) as cur:
                for row in await cur.fetchall():
                    d = dict(row)
                    d["direction"] = "incoming"
                    results.append(d)
        return results

    async def get_knowledge_timeline(self, entity_name: str | None = None, limit: int = 100) -> list[dict]:
        query = """
            SELECT t.*, s.name as sub_name, o.name as obj_name
            FROM knowledge_triples t
            JOIN entities s ON t.subject = s.id
            JOIN entities o ON t.object = o.id
        """
        params = []
        if entity_name:
            eid = self._entity_id(entity_name)
            query += " WHERE t.subject = ? OR t.object = ?"
            params = [eid, eid]
        
        query += " ORDER BY t.valid_from ASC NULLS LAST LIMIT ?"
        params.append(limit)
        
        async with self._db.execute(query, params) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def find_temporal_anomalies(self, limit: int = 5) -> list[dict]:
        """
        Encontra fatos que podem estar obsoletos ou que precisam de confirmação.
        Prioriza triplas antigas (> 60 dias) ou com baixa confiança.
        """
        cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - (60 * 86400)))
        query = """
            SELECT t.*, s.name as sub_name, o.name as obj_name
            FROM knowledge_triples t
            JOIN entities s ON t.subject = s.id
            JOIN entities o ON t.object = o.id
            WHERE (t.valid_from < ? OR t.confidence < 0.6)
            AND t.valid_to IS NULL
            ORDER BY t.confidence ASC, t.extracted_at ASC
            LIMIT ?
        """
        async with self._db.execute(query, (cutoff, limit)) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def get_verification_context(self) -> str:
        """Gera um bloco de texto para o LLM pedindo confirmação de fatos antigos."""
        anomalies = await self.find_temporal_anomalies(limit=3)
        if not anomalies:
            return ""
        
        lines = ["=== AUDITORIA TEMPORAL (Verificar com usuário se ainda é verdade) ==="]
        for a in anomalies:
            lines.append(f"• {a['sub_name']} {a['predicate']} {a['obj_name']} (Registrado em: {a['extracted_at'][:10]})")
        return "\n".join(lines)

    # ─── CONTEXTO PARA O LLM ─────────────────────────────────

    async def format_context(
        self,
        query: str = "",
        limit: int = 10,
        identity: str = "",
        on_demand_category: str | None = None,
    ) -> str:
        """
        Formata o contexto usando o 4-Layer Stack (L0-L3).
        """
        from src.core.memory.hierarchy import format_4layer_context, score_fact
        
        # L1: Essential
        all_facts = await self.get_facts(min_confidence=0.3, limit=100)
        scored = [(score_fact(f), f) for f in all_facts]
        scored.sort(key=lambda x: x[0], reverse=True)
        essential = [f for _, f in scored[:limit]]
        
        # L2: On-Demand
        on_demand = []
        if on_demand_category:
            on_demand = await self.get_facts(category=on_demand_category, limit=5)
            
        # L3: Search
        search_results = []
        if query:
            search_results = await self.search_facts(query, limit=5)

        return format_4layer_context(
            identity=identity,
            essential_facts=essential,
            on_demand_facts=on_demand,
            search_results=search_results
        )

    # ─── USER PREFERENCES ──────────────────────────────────────

    async def get_user_niches(self, user_id: int | str) -> list[str] | None:
        """Retorna lista de nichos escolhidos pelo usuário para SenseNews."""
        if not self._db:
            return None
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
        """Salva nichos escolhidos pelo usuário."""
        if not self._db:
            return False
        try:
            await self._db.execute(
                """INSERT INTO user_preferences (user_id, telegram_id, niches, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET niches = excluded.niches, updated_at = excluded.updated_at""",
                (user_id, telegram_id, json.dumps(niches), time.time())
            )
            await self._db.commit()
            return True
        except Exception as e:
            log.error(f"Falha ao salvar preferências do usuário {user_id}: {e}")
            return False
