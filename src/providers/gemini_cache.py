"""
Seeker.Bot — Gemini Explicit Caching Manager
src/providers/gemini_cache.py

Gerencia caches explícitos do Gemini API:
- CachedContentManager: Tracks cached content, evita recriação
- hash-based lookup: Reutiliza caches se conteúdo é idêntico
- TTL automático: 5 minutos (padrão Gemini)

Gemini exige mínimo 4k tokens para usar caching. Combinamos SYSTEM_BASE
com session_context + memory_context determinísticos.
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("seeker.providers.gemini_cache")

GEMINI_CACHE_EXPIRY_SECONDS = 5 * 60  # 5 minutes
GEMINI_MIN_CACHED_TOKENS = 4000


@dataclass
class CachedContent:
    """Representa um conteúdo cacheado no Gemini."""

    content_hash: str
    cache_name: str  # format: "cachedContents/{id}"
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + GEMINI_CACHE_EXPIRY_SECONDS)
    estimated_tokens: int = 0

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def ttl_seconds(self) -> int:
        remaining = int(self.expires_at - time.time())
        return max(0, remaining)


class CachedContentManager:
    """
    Gerencia caches explícitos do Gemini.

    Estratégia:
      1. Hash do conteúdo (SYSTEM_BASE + session + memory)
      2. Lookup em cache em-memória
      3. Se miss ou expirado: criar novo cache via API
      4. Reutilizar cache_name em próximas requests
    """

    def __init__(self, api_key: str, model_id: str):
        self.api_key = api_key
        self.model_id = model_id
        # Dict[content_hash] -> CachedContent
        self._cache_store: dict[str, CachedContent] = {}
        self._client = None

    async def get_cache_name_or_create(
        self,
        client,  # httpx.AsyncClient
        system_content: str,
        estimated_tokens: int,
    ) -> Optional[str]:
        """
        Retorna cache_name se disponível e válido, ou None.

        Se tokens < 4k, retorna None (Gemini não suporta).
        Se tokens >= 4k e cache existe, retorna cache_name.
        Se tokens >= 4k e cache não existe, cria via API.

        Returns: "cachedContents/{id}" ou None
        """
        if estimated_tokens < GEMINI_MIN_CACHED_TOKENS:
            log.debug(
                f"[gemini-cache] Conteúdo abaixo do mínimo "
                f"({estimated_tokens} < {GEMINI_MIN_CACHED_TOKENS}). "
                f"Explicit caching desabilitado."
            )
            return None

        content_hash = self._hash_content(system_content)

        # Lookup local
        if content_hash in self._cache_store:
            cached = self._cache_store[content_hash]
            if not cached.is_expired:
                log.info(
                    f"[gemini-cache] Cache hit (TTL: {cached.ttl_seconds}s) — "
                    f"{cached.estimated_tokens} tokens"
                )
                return cached.cache_name
            else:
                log.info("[gemini-cache] Cache expirado — criando novo")
                del self._cache_store[content_hash]

        # Miss — criar novo cache via API
        log.info(f"[gemini-cache] Cache miss — criando novo ({estimated_tokens} tokens)...")
        try:
            cache_name = await self._create_cache(client, system_content, estimated_tokens)
            if cache_name:
                self._cache_store[content_hash] = CachedContent(
                    content_hash=content_hash,
                    cache_name=cache_name,
                    estimated_tokens=estimated_tokens,
                )
                log.info(f"[gemini-cache] Cache criado: {cache_name}")
                return cache_name
        except Exception as e:
            log.warning(f"[gemini-cache] Falha ao criar cache: {e}")
            return None

        return None

    async def _create_cache(self, client, content: str, estimated_tokens: int) -> Optional[str]:
        """
        Cria cache explícito via Gemini API.

        Requer: httpx async client, headers com API key.
        Retorna: "cachedContents/{id}" ou None
        """
        model_name = self.model_id if self.model_id.startswith("models/") else f"models/{self.model_id}"
        url = f"https://generativelanguage.googleapis.com/v1beta/cachedContents?key={self.api_key}"
        
        payload = {
            "model": model_name,
            "systemInstruction": {
                "parts": [{"text": content}]
            },
            "ttl": f"{GEMINI_CACHE_EXPIRY_SECONDS}s"
        }
        
        log.debug(f"[gemini-cache] POST para cachedContents com payload para modelo {model_name}")
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        
        cache_name = data.get("name")
        return cache_name

    @staticmethod
    def _hash_content(content: str) -> str:
        """Hash SHA256 do conteúdo para dedup."""
        return hashlib.sha256(content.encode()).hexdigest()

    def estimate_tokens(self, text: str) -> int:
        """
        Estima token count usando heurística simples.

        Realidade: Gemini tokenizer é complexo (BPE-like).
        Heurística: ~1.3 tokens por palavra em português.
        """
        words = len(text.split())
        return int(words * 1.3)

    def clear_expired(self):
        """Remove caches expirados do store local."""
        expired_hashes = [
            h for h, c in self._cache_store.items() if c.is_expired
        ]
        for h in expired_hashes:
            log.debug("[gemini-cache] Removendo cache expirado")
            del self._cache_store[h]

    def stats(self) -> dict:
        """Retorna estatísticas do cache manager."""
        self.clear_expired()
        return {
            "total_cached": len(self._cache_store),
            "estimated_total_tokens": sum(
                c.estimated_tokens for c in self._cache_store.values()
            ),
            "oldest_ttl": min(
                (c.ttl_seconds for c in self._cache_store.values()), default=0
            ),
        }
