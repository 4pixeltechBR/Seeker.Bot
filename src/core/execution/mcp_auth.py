"""
core.execution.mcp_auth — Middleware de autenticação Bearer para MCP server.

Regras:
  - Conexões loopback (127.0.0.1, ::1, localhost): bypass — sem auth.
    Justificativa: uso local (opencode rodando na mesma máquina) não deve
    friccionar com token. Se alguém abrir a porta para a rede, aí sim exigimos.
  - Conexões remotas: exigem `Authorization: Bearer <SEEKER_MCP_API_KEY>`.
  - Rate limit simples: 10 req/s por IP via token bucket em memória.

Log:
  - Toda chamada autenticada registra IP + endpoint chamado.
  - Tentativas falhas registram IP + motivo (sem header, token errado, etc.).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

log = logging.getLogger("seeker.execution.mcp_auth")

LOOPBACK_IPS = {"127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1", "::ffff:127.0.0.1"}

# Rate limit
RATE_LIMIT_PER_SECOND = 10
TOKEN_BUCKET_CAPACITY = 20  # burst


# ── Token bucket simples (thread-safe) ─────────────────────────────────


class _TokenBucket:
    """Token bucket thread-safe para rate limiting por IP."""

    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Tenta consumir 1 token. Retorna True se permitido."""
        with self._lock:
            now = time.time()
            tokens, last_ts = self._buckets.get(key, (self.capacity, now))
            # Recarrega tokens baseado no tempo decorrido
            elapsed = now - last_ts
            tokens = min(self.capacity, tokens + elapsed * self.rate)
            if tokens >= 1.0:
                tokens -= 1.0
                self._buckets[key] = (tokens, now)
                return True
            self._buckets[key] = (tokens, now)
            return False


_bucket = _TokenBucket(RATE_LIMIT_PER_SECOND, TOKEN_BUCKET_CAPACITY)


# ── Auth check ────────────────────────────────────────────────────────


def get_api_key() -> Optional[str]:
    """Retorna a API key configurada (None se não configurada)."""
    # Tenta carregar do .env se ainda não estiver em os.environ
    if not os.getenv("SEEKER_MCP_API_KEY"):
        try:
            from dotenv import load_dotenv
            # Tenta config/.env (path padrão do Seeker)
            from pathlib import Path
            env_path = Path(__file__).resolve().parent.parent.parent.parent / "config" / ".env"
            if env_path.exists():
                load_dotenv(env_path, override=False)
        except ImportError:
            pass
    return os.getenv("SEEKER_MCP_API_KEY", "").strip() or None


def is_loopback(ip: str) -> bool:
    """Retorna True se IP é loopback."""
    return ip in LOOPBACK_IPS


def check_bearer(headers: dict[str, str], remote_ip: str) -> tuple[bool, str]:
    """Verifica autenticação Bearer.

    Returns:
        (allowed, reason) — reason é "ok", "loopback_bypass", "missing_header",
        "invalid_token", "rate_limited", "no_api_key_configured".
    """
    # Rate limit primeiro (antes de tudo)
    if not _bucket.allow(remote_ip):
        log.warning(f"[mcp_auth] Rate limit exceeded for IP={remote_ip}")
        return False, "rate_limited"

    # Loopback bypass
    if is_loopback(remote_ip):
        return True, "loopback_bypass"

    # Requer token
    api_key = get_api_key()
    if not api_key:
        log.error(
            "[mcp_auth] SEEKER_MCP_API_KEY não configurada no .env mas "
            "conexão remota recebida. Bloqueando."
        )
        return False, "no_api_key_configured"

    auth_header = headers.get("Authorization", "") or headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        log.warning(
            f"[mcp_auth] Conexão remota sem Authorization header. "
            f"IP={remote_ip}, header={auth_header[:40]!r}"
        )
        return False, "missing_header"

    token = auth_header[len("Bearer "):].strip()
    if not token or token != api_key:
        log.warning(
            f"[mcp_auth] Token inválido. IP={remote_ip}, "
            f"token_len={len(token)}, expected_len={len(api_key)}"
        )
        return False, "invalid_token"

    log.debug(f"[mcp_auth] Auth OK for IP={remote_ip}")
    return True, "ok"


def format_401(reason: str) -> dict[str, str]:
    """Retorna WWW-Authenticate header para 401."""
    return {
        "WWW-Authenticate": f'Bearer realm="seeker-mcp", error="{reason}"',
    }
