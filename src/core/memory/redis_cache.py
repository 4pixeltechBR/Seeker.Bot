"""
Redis Cache Layer for Embeddings (Optional)
src/core/memory/redis_cache.py

Provides optional distributed caching for embeddings.
Falls back to local LRU if Redis unavailable.
Useful for multi-worker setups where embeddings need to be shared.
"""

import json
import logging
from typing import Optional

log = logging.getLogger("seeker.memory.redis")


class RedisEmbeddingCache:
    """
    Optional Redis cache for embeddings.
    Falls back gracefully to in-memory if Redis unavailable.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.redis = None
        self._enabled = False

        try:
            import redis.asyncio as redis

            # Try to connect
            self.redis_client = redis.from_url(redis_url)
            self._enabled = True
            log.info(f"[redis] Conectado em {redis_url}")
        except ImportError:
            log.warning("[redis] redis-py não instalado. Cache distribuído desativado. (pip install redis)")
        except Exception as e:
            log.warning(f"[redis] Conexão falhou: {e}. Usando cache local.")

    async def get(self, fact_id: int) -> Optional[list[float]]:
        """Get embedding from Redis (or None if not found/disabled)."""
        if not self._enabled or not self.redis_client:
            return None

        try:
            key = f"emb:{fact_id}"
            value = await self.redis_client.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            log.warning(f"[redis] Get falhou: {e}")
        return None

    async def set(self, fact_id: int, vector: list[float], ttl: int = 86400) -> bool:
        """
        Set embedding in Redis with TTL (default 24h).
        Useful for frequently-accessed embeddings.
        """
        if not self._enabled or not self.redis_client:
            return False

        try:
            key = f"emb:{fact_id}"
            value = json.dumps(vector)
            await self.redis_client.setex(key, ttl, value)
            return True
        except Exception as e:
            log.warning(f"[redis] Set falhou: {e}")
        return False

    async def delete(self, fact_id: int) -> bool:
        """Delete embedding from Redis."""
        if not self._enabled or not self.redis_client:
            return False

        try:
            key = f"emb:{fact_id}"
            await self.redis_client.delete(key)
            return True
        except Exception as e:
            log.warning(f"[redis] Delete falhou: {e}")
        return False

    async def clear(self) -> bool:
        """Clear all embeddings from Redis."""
        if not self._enabled or not self.redis_client:
            return False

        try:
            keys = await self.redis_client.keys("emb:*")
            if keys:
                await self.redis_client.delete(*keys)
            return True
        except Exception as e:
            log.warning(f"[redis] Clear falhou: {e}")
        return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis_client:
            try:
                await self.redis_client.close()
                self._enabled = False
            except Exception as e:
                log.warning(f"[redis] Close falhou: {e}")

    def is_enabled(self) -> bool:
        """Check if Redis is available."""
        return self._enabled


# Singleton instance
_redis_cache: Optional[RedisEmbeddingCache] = None


def get_redis_cache(redis_url: str = "redis://localhost:6379/0") -> RedisEmbeddingCache:
    """Get or create Redis cache singleton."""
    global _redis_cache
    if _redis_cache is None:
        _redis_cache = RedisEmbeddingCache(redis_url)
    return _redis_cache
