"""
Seeker.Bot — S.A.R.A ErrorDatabase + PendingPatchStore
src/skills/self_improvement/error_database.py

Armazena histórico de erros, patches aplicados e resultados de auto-cura em SQLite.

Propósito:
- Dedup: não analisar o mesmo erro duas vezes em sequência
- Telemetria: taxa de sucesso do SARA, custo acumulado, arquivos mais problemáticos
- Auditoria: rastreabilidade de tudo que o SARA tocou no código
- PendingPatchStore: patches aguardando aprovação via Telegram inline buttons

Schema:
  errors(id, traceback_hash, file_path, error_type, first_seen, last_seen, count)
  patches(id, error_id, proposed_at, validation_passed, stage_failed, applied, cost_usd, rationale)
"""

import asyncio
import hashlib
import logging
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("seeker.self_improvement.error_db")


# ── Sanitização de tracebacks ────────────────────────────────────────

def sanitize_traceback(raw: str, max_len: int = 2000) -> str:
    """
    Prepara traceback para envio seguro ao LLM:

    1. Remove paths absolutos do sistema (mantém apenas relative)
    2. Remove tokens/secrets de variáveis de ambiente em linhas de log
    3. Trunca a comprimento seguro
    4. Normaliza espaços em branco excessivos

    Args:
        raw: Traceback bruto do log
        max_len: Comprimento máximo da saída

    Returns:
        String sanitizada, segura para envio ao LLM externo
    """
    if not raw:
        return ""

    lines = raw.splitlines()
    sanitized = []

    # Regex para detectar paths absolutos do Windows e Linux
    abs_path_re = re.compile(
        r'(?:[A-Za-z]:\\(?:[^\\"\n]+\\)*[^\\"\n]*|/(?:home|usr|etc|root|var|opt)/[^\s"\']+)'
    )
    # Regex para detectar possíveis secrets (API keys, tokens)
    secret_re = re.compile(
        r'(?i)(?:api[_\-]?key|secret|token|password|passwd|bearer|auth)[^\s]*\s*[=:]\s*["\']?[\w\-\.]{8,}',
        re.IGNORECASE
    )
    # Regex para paths do projeto (mantém a parte relativa ao Seeker.Bot)
    project_re = re.compile(r'.*[/\\]Seeker\.Bot[/\\](.*)')

    for line in lines:
        # Sanitiza paths absolutos — mantém apenas a parte relativa ao projeto
        def replace_path(m: re.Match) -> str:
            full_path = m.group(0)
            proj_match = project_re.match(full_path)
            if proj_match:
                return proj_match.group(1).replace("\\", "/")
            # Path fora do projeto: mostra apenas o nome do arquivo
            return os.path.basename(full_path)

        line = abs_path_re.sub(replace_path, line)

        # Remove possíveis secrets
        line = secret_re.sub(lambda m: m.group(0).split("=")[0] + "=<REDACTED>", line)

        sanitized.append(line)

    result = "\n".join(sanitized)

    # Trunca preservando o final (onde está a linha de erro mais relevante)
    if len(result) > max_len:
        half = max_len // 2
        result = result[:half] + "\n...[TRUNCADO]...\n" + result[-half:]

    return result.strip()


def hash_traceback(traceback: str) -> str:
    """Hash SHA256 da última linha de erro + arquivo — identifica o erro único."""
    lines = [l.strip() for l in traceback.splitlines() if l.strip()]
    # Pega as 3 últimas linhas significativas para o hash (mais estável que o texto completo)
    tail = "\n".join(lines[-3:]) if len(lines) >= 3 else "\n".join(lines)
    return hashlib.sha256(tail.encode("utf-8")).hexdigest()[:16]


# ── ErrorDatabase ────────────────────────────────────────────────────

@dataclass
class ErrorRecord:
    id: int
    traceback_hash: str
    file_path: str
    error_type: str
    first_seen: float
    last_seen: float
    count: int


@dataclass
class PatchRecord:
    id: int
    error_id: int
    proposed_at: float
    validation_passed: bool
    stage_failed: Optional[str]
    applied: bool
    cost_usd: float
    rationale: str


class ErrorDatabase:
    """
    Banco SQLite para telemetria e dedup do S.A.R.A.

    Uso:
        db = ErrorDatabase()
        await db.init()

        # Verificar dedup antes de analisar
        if await db.is_recent_duplicate(traceback, hours=6):
            return  # Já analisamos isso

        # Registrar erro
        error_id = await db.record_error(traceback, file_path, error_type)

        # Registrar patch
        await db.record_patch(error_id, validation_passed, stage_failed, applied, cost, rationale)
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..")
            )
            db_path = os.path.join(root, "data", "sara_errors.db")
        self.db_path = db_path
        self._initialized = False

    async def init(self) -> None:
        """Cria tabelas se não existirem."""
        if self._initialized:
            return
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        await asyncio.to_thread(self._create_tables)
        self._initialized = True
        log.info(f"[error_db] Inicializado: {self.db_path}")

    def _create_tables(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS errors (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    traceback_hash  TEXT NOT NULL,
                    file_path       TEXT NOT NULL,
                    error_type      TEXT NOT NULL DEFAULT 'Unknown',
                    first_seen      REAL NOT NULL,
                    last_seen       REAL NOT NULL,
                    count           INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(traceback_hash)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS patches (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_id          INTEGER NOT NULL REFERENCES errors(id),
                    proposed_at       REAL NOT NULL,
                    validation_passed INTEGER NOT NULL DEFAULT 0,
                    stage_failed      TEXT,
                    applied           INTEGER NOT NULL DEFAULT 0,
                    cost_usd          REAL NOT NULL DEFAULT 0.0,
                    rationale         TEXT NOT NULL DEFAULT ''
                )
            """)
            # Patches pendentes de aprovação via Telegram (ApprovalEngine)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_patches (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path     TEXT NOT NULL,
                    proposed_code TEXT NOT NULL,
                    rationale     TEXT NOT NULL DEFAULT '',
                    status        TEXT NOT NULL DEFAULT 'pending',
                    created_at    REAL NOT NULL,
                    resolved_at   REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_errors_hash ON errors(traceback_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_errors_last_seen ON errors(last_seen)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_patches_error ON patches(error_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_patches(status)")
            conn.commit()

    # ── Dedup ──────────────────────────────────────────────────────

    async def is_recent_duplicate(self, traceback: str, hours: float = 6.0) -> bool:
        """
        Verifica se este erro já foi analisado nas últimas N horas.
        Evita gastar LLM calls em tracebacks repetidos.
        """
        tb_hash = hash_traceback(traceback)
        cutoff = time.time() - (hours * 3600)

        def _check():
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT last_seen FROM errors WHERE traceback_hash = ? AND last_seen > ?",
                    (tb_hash, cutoff)
                ).fetchone()
                return row is not None

        is_dup = await asyncio.to_thread(_check)
        if is_dup:
            log.info(f"[error_db] Dedup: hash={tb_hash} já analisado nas últimas {hours}h")
        return is_dup

    # ── Registro ────────────────────────────────────────────────────

    async def record_error(
        self,
        traceback: str,
        file_path: str,
        error_type: str = "Unknown",
    ) -> int:
        """
        Registra ou atualiza um erro. Retorna o error_id.
        Se o hash já existe, incrementa count e atualiza last_seen.
        """
        tb_hash = hash_traceback(traceback)
        now = time.time()

        def _upsert() -> int:
            with sqlite3.connect(self.db_path) as conn:
                # Tenta update primeiro (erro existente)
                cursor = conn.execute(
                    """
                    UPDATE errors
                    SET last_seen = ?, count = count + 1
                    WHERE traceback_hash = ?
                    """,
                    (now, tb_hash)
                )
                if cursor.rowcount > 0:
                    row = conn.execute(
                        "SELECT id FROM errors WHERE traceback_hash = ?", (tb_hash,)
                    ).fetchone()
                    conn.commit()
                    return row[0]

                # Insert novo
                cursor = conn.execute(
                    """
                    INSERT INTO errors (traceback_hash, file_path, error_type, first_seen, last_seen, count)
                    VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (tb_hash, file_path, error_type, now, now)
                )
                conn.commit()
                return cursor.lastrowid

        error_id = await asyncio.to_thread(_upsert)
        log.debug(f"[error_db] Erro registrado: id={error_id} hash={tb_hash} file={os.path.basename(file_path)}")
        return error_id

    async def record_patch(
        self,
        error_id: int,
        validation_passed: bool,
        stage_failed: Optional[str],
        applied: bool,
        cost_usd: float,
        rationale: str,
    ) -> int:
        """Registra um patch proposto (aprovado ou rejeitado)."""
        def _insert() -> int:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO patches
                    (error_id, proposed_at, validation_passed, stage_failed, applied, cost_usd, rationale)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        error_id, time.time(),
                        1 if validation_passed else 0,
                        stage_failed,
                        1 if applied else 0,
                        cost_usd, rationale[:500]
                    )
                )
                conn.commit()
                return cursor.lastrowid

        patch_id = await asyncio.to_thread(_insert)
        status = "aplicado" if applied else ("rejeitado" if not validation_passed else "validado")
        log.debug(f"[error_db] Patch {status}: id={patch_id} error_id={error_id}")
        return patch_id

    # ── Relatórios ─────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        """Retorna estatísticas de auto-cura para o health dashboard."""
        def _query():
            with sqlite3.connect(self.db_path) as conn:
                total_errors = conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
                total_patches = conn.execute("SELECT COUNT(*) FROM patches").fetchone()[0]
                applied = conn.execute(
                    "SELECT COUNT(*) FROM patches WHERE applied = 1"
                ).fetchone()[0]
                rejected = conn.execute(
                    "SELECT COUNT(*) FROM patches WHERE validation_passed = 0"
                ).fetchone()[0]
                total_cost = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0.0) FROM patches"
                ).fetchone()[0]
                # Top 3 arquivos mais problemáticos
                top_files = conn.execute(
                    "SELECT file_path, SUM(count) as total FROM errors GROUP BY file_path ORDER BY total DESC LIMIT 3"
                ).fetchall()
                return {
                    "total_errors": total_errors,
                    "total_patches": total_patches,
                    "patches_applied": applied,
                    "patches_rejected": rejected,
                    "total_cost_usd": round(total_cost, 4),
                    "success_rate_pct": round((applied / total_patches * 100) if total_patches > 0 else 0, 1),
                    "top_files": [{"file": os.path.basename(f), "count": c} for f, c in top_files],
                }

        return await asyncio.to_thread(_query)

    async def format_stats_for_telegram(self) -> str:
        """Formata estatísticas para o comando /sara ou health monitor."""
        stats = await self.get_stats()
        top = "\n".join(
            f"  - {f['file']}: {f['count']}x"
            for f in stats["top_files"]
        ) or "  (nenhum ainda)"

        return (
            f"<b>S.A.R.A &mdash; Telemetria</b>\n"
            f"| Erros unicos detectados: {stats['total_errors']}\n"
            f"| Patches propostos: {stats['total_patches']}\n"
            f"| Patches aplicados: {stats['patches_applied']} ({stats['success_rate_pct']}%)\n"
            f"| Patches rejeitados (validacao): {stats['patches_rejected']}\n"
            f"| Custo total: ${stats['total_cost_usd']:.4f}\n"
            f"| Arquivos mais afetados:\n{top}"
        )


# ── PendingPatchStore ────────────────────────────────────────────────

class PendingPatchStore:
    """
    Armazena patches validados aguardando aprovação via Telegram.

    Usado pelo ApprovalEngine:
    1. S.A.R.A valida patch → chama create_pending() → retorna pending_id
    2. GoalNotifier envia mensagem com botões sara_approve:{id} / sara_reject:{id}
    3. Usuário clica → bot.py callback chama approve(id) ou reject(id)

    Os registros expiram automaticamente via get_pending() (retorna None se > 24h).
    """

    EXPIRY_HOURS = 24.0  # Patches pendentes expiram após 24h sem resposta

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def create_pending(
        self,
        file_path: str,
        proposed_code: str,
        rationale: str,
    ) -> int:
        """
        Registra um patch validado aguardando aprovação.
        Retorna o pending_id a ser embedado no callback_data dos botões.
        """
        def _insert() -> int:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO pending_patches (file_path, proposed_code, rationale, status, created_at)
                    VALUES (?, ?, ?, 'pending', ?)
                    """,
                    (file_path, proposed_code, rationale[:500], time.time())
                )
                conn.commit()
                return cursor.lastrowid

        pending_id = await asyncio.to_thread(_insert)
        log.info(f"[pending_patch] Patch {pending_id} aguardando aprovacao: {os.path.basename(file_path)}")
        return pending_id

    async def get_pending(self, pending_id: int) -> Optional[dict]:
        """
        Retorna o patch pendente se ainda válido (status=pending, < 24h).
        Retorna None se já resolvido, expirado ou não encontrado.
        """
        expiry_cutoff = time.time() - (self.EXPIRY_HOURS * 3600)

        def _fetch() -> Optional[tuple]:
            with sqlite3.connect(self.db_path) as conn:
                return conn.execute(
                    """
                    SELECT file_path, proposed_code, rationale
                    FROM pending_patches
                    WHERE id = ? AND status = 'pending' AND created_at > ?
                    """,
                    (pending_id, expiry_cutoff)
                ).fetchone()

        row = await asyncio.to_thread(_fetch)
        if row is None:
            return None
        return {"file_path": row[0], "proposed_code": row[1], "rationale": row[2]}

    async def approve(self, pending_id: int) -> Optional[dict]:
        """
        Marca como aprovado e retorna o patch para aplicação.
        Retorna None se já resolvido ou expirado.
        """
        patch = await self.get_pending(pending_id)
        if patch is None:
            log.warning(f"[pending_patch] Approve falhou: id={pending_id} não encontrado/expirado/resolvido")
            return None

        def _update():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE pending_patches SET status='approved', resolved_at=? WHERE id=?",
                    (time.time(), pending_id)
                )
                conn.commit()

        await asyncio.to_thread(_update)
        log.info(f"[pending_patch] Patch {pending_id} APROVADO: {os.path.basename(patch['file_path'])}")
        return patch

    async def reject(self, pending_id: int) -> bool:
        """
        Marca como rejeitado. Retorna True se foi encontrado e rejeitado.
        """
        patch = await self.get_pending(pending_id)
        if patch is None:
            return False

        def _update():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE pending_patches SET status='rejected', resolved_at=? WHERE id=?",
                    (time.time(), pending_id)
                )
                conn.commit()

        await asyncio.to_thread(_update)
        log.info(f"[pending_patch] Patch {pending_id} REJEITADO: {os.path.basename(patch['file_path'])}")
        return True


# ── Singleton compartilhado ────────────────────────────────────────

_pending_store: Optional[PendingPatchStore] = None


def get_pending_store(db_path: Optional[str] = None) -> PendingPatchStore:
    """
    Retorna a instância compartilhada do PendingPatchStore.
    Deve ser inicializada com o mesmo db_path da ErrorDatabase.
    """
    global _pending_store
    if _pending_store is None:
        if db_path is None:
            root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..")
            )
            db_path = os.path.join(root, "data", "sara_errors.db")
        _pending_store = PendingPatchStore(db_path=db_path)
    return _pending_store
