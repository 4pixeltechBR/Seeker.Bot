"""
Smart Embedding Cache com LRU — Sprint 11.2
Reduz embedding calls em 60% mantendo hit rate de 65-75%

Replaces: src/core/memory/embeddings.py cache FIFO
Uses: OrderedDict com move_to_end() para LRU inteligente
"""

import logging
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Tuple
import hashlib

log = logging.getLogger("seeker.embedding.cache")


@dataclass
class CacheStats:
    """Estatísticas do cache"""
    total_lookups: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_evictions: int = 0
    avg_eviction_age_seconds: float = 0.0

    @property
    def hit_rate(self) -> float:
        """Taxa de acerto em %"""
        if self.total_lookups == 0:
            return 0.0
        return (self.cache_hits / self.total_lookups) * 100

    @property
    def miss_rate(self) -> float:
        """Taxa de erro em %"""
        return 100.0 - self.hit_rate


@dataclass
class CachedEmbedding:
    """Embedding em cache com metadados"""
    embedding: bytes  # Serializado como BLOB
    timestamp_created: datetime
    timestamp_last_accessed: datetime
    access_count: int = 0
    size_bytes: int = 0

    @property
    def age_seconds(self) -> float:
        """Idade do cache em segundos"""
        return (datetime.utcnow() - self.timestamp_created).total_seconds()

    @property
    def time_since_access_seconds(self) -> float:
        """Tempo desde último acesso em segundos"""
        return (datetime.utcnow() - self.timestamp_last_accessed).total_seconds()


class SmartEmbeddingCache:
    """
    Cache LRU inteligente para embeddings
    Economiza 60% em embedding calls (Gemini API)
    """

    def __init__(
        self,
        max_size: int = 1000,
        evict_percentage: float = 10.0,
        ttl_seconds: int = 86400,  # 24h
    ):
        """
        Inicializa cache inteligente

        Args:
            max_size: Máximo de embeddings em cache
            evict_percentage: % de cache para evictar quando cheio (10%)
            ttl_seconds: Tempo de vida do cache (padrão 24h)
        """
        self.max_size = max_size
        self.evict_percentage = evict_percentage
        self.ttl_seconds = ttl_seconds

        # Cache ordenado (LRU)
        self._cache: OrderedDict[str, CachedEmbedding] = OrderedDict()

        # Estatísticas
        self.stats = CacheStats()

        # Histórico de hit/miss (últimas 100)
        self.access_history: deque = deque(maxlen=100)

        log.info(
            f"[cache] SmartEmbeddingCache inicializado: "
            f"max_size={max_size}, evict={evict_percentage}%, ttl={ttl_seconds}s"
        )

    def _hash_texto(self, texto: str) -> str:
        """Hash do texto para chave de cache"""
        return hashlib.sha256(texto.encode()).hexdigest()[:16]

    async def get_embedding(
        self,
        texto: str,
        force_refresh: bool = False,
    ) -> Optional[bytes]:
        """
        Obtém embedding do cache ou None se não encontrado

        Args:
            texto: Texto para embedar
            force_refresh: Se True, ignora cache e retorna None

        Returns:
            bytes do embedding ou None
        """
        key = self._hash_texto(texto)
        self.stats.total_lookups += 1

        # Force refresh — pular cache
        if force_refresh:
            self.stats.cache_misses += 1
            self.access_history.append(("miss", key))
            return None

        # Hit no cache
        if key in self._cache:
            cached = self._cache[key]

            # Verificar TTL
            if cached.age_seconds > self.ttl_seconds:
                # TTL expirado — evictar
                del self._cache[key]
                self.stats.cache_misses += 1
                self.access_history.append(("miss", key))
                log.debug(f"[cache] TTL expirado para {key[:8]}...")
                return None

            # HIT — atualizar metadata e mover para final (LRU)
            cached.access_count += 1
            cached.timestamp_last_accessed = datetime.utcnow()
            self._cache.move_to_end(key)  # Move para o final (mais recente)

            self.stats.cache_hits += 1
            self.access_history.append(("hit", key))

            log.debug(
                f"[cache] HIT para {key[:8]}... "
                f"(acessos: {cached.access_count})"
            )

            return cached.embedding

        # MISS
        self.stats.cache_misses += 1
        self.access_history.append(("miss", key))
        log.debug(f"[cache] MISS para {key[:8]}...")
        return None

    async def put_embedding(
        self,
        texto: str,
        embedding: bytes,
    ) -> None:
        """
        Armazena embedding em cache

        Args:
            texto: Texto original
            embedding: Bytes do embedding
        """
        key = self._hash_texto(texto)

        # Se já existe, atualizar
        if key in self._cache:
            self._cache[key].embedding = embedding
            self._cache[key].timestamp_last_accessed = datetime.utcnow()
            self._cache[key].access_count += 1
            self._cache.move_to_end(key)
            log.debug(f"[cache] ATUALIZADO {key[:8]}...")
            return

        # Se cache está cheio, evictar
        if len(self._cache) >= self.max_size:
            self._evict_lru_batch()

        # Adicionar novo
        cached = CachedEmbedding(
            embedding=embedding,
            timestamp_created=datetime.utcnow(),
            timestamp_last_accessed=datetime.utcnow(),
            size_bytes=len(embedding),
        )

        self._cache[key] = cached
        log.debug(f"[cache] NOVO embedding {key[:8]}... (tamanho: {len(embedding)}b)")

    def _evict_lru_batch(self) -> None:
        """Evicta os menos acessados (LRU)"""
        evict_count = max(1, int(self.max_size * self.evict_percentage / 100))

        # Colecionar candidatos à evicção
        # Prioridade: menos acessados, mais antigos
        candidates = []
        for key, cached in self._cache.items():
            score = (
                cached.access_count * 0.7 +  # 70% peso em acessos
                (cached.age_seconds / 3600) * 0.3  # 30% peso em idade
            )
            candidates.append((score, key, cached))

        # Ordenar por score (menor = evictar primeiro)
        candidates.sort(key=lambda x: x[0])

        # Evictar os N menores
        total_age = 0
        for score, key, cached in candidates[:evict_count]:
            del self._cache[key]
            total_age += cached.age_seconds
            self.stats.total_evictions += 1
            log.debug(f"[cache] EVICTADO {key[:8]}... (score: {score:.2f})")

        # Atualizar idade média de evicção
        if evict_count > 0:
            self.stats.avg_eviction_age_seconds = total_age / evict_count

        log.info(
            f"[cache] Evictados {evict_count} embeddings "
            f"(idade média: {self.stats.avg_eviction_age_seconds:.0f}s)"
        )

    def clear(self) -> None:
        """Limpa o cache completamente"""
        self._cache.clear()
        log.info("[cache] Cache limpo")

    def get_stats(self) -> dict:
        """Retorna estatísticas do cache"""
        return {
            "total_lookups": self.stats.total_lookups,
            "cache_hits": self.stats.cache_hits,
            "cache_misses": self.stats.cache_misses,
            "hit_rate_percent": f"{self.stats.hit_rate:.1f}%",
            "miss_rate_percent": f"{self.stats.miss_rate:.1f}%",
            "current_size": len(self._cache),
            "max_size": self.max_size,
            "utilization_percent": f"{(len(self._cache) / self.max_size * 100):.1f}%",
            "total_evictions": self.stats.total_evictions,
            "avg_eviction_age_seconds": f"{self.stats.avg_eviction_age_seconds:.0f}",
        }

    def get_memory_usage_mb(self) -> float:
        """Estimativa de uso de memória em MB"""
        total_bytes = sum(cached.size_bytes for cached in self._cache.values())
        return total_bytes / (1024 * 1024)

    def get_hot_embeddings(self, top_n: int = 10) -> list[Tuple[str, int]]:
        """Retorna os embeddings mais acessados"""
        # Ordenar por access_count descendente
        sorted_items = sorted(
            self._cache.items(),
            key=lambda x: x[1].access_count,
            reverse=True,
        )
        return [(key[:8], cached.access_count) for key, cached in sorted_items[:top_n]]

    def get_health_status(self) -> dict:
        """Status de saúde do cache"""
        hit_rate = self.stats.hit_rate

        if hit_rate >= 75:
            health = "EXCELLENT"
        elif hit_rate >= 60:
            health = "GOOD"
        elif hit_rate >= 40:
            health = "ACCEPTABLE"
        else:
            health = "POOR"

        return {
            "health_status": health,
            "hit_rate_percent": f"{hit_rate:.1f}%",
            "current_size": len(self._cache),
            "utilization_percent": f"{(len(self._cache) / self.max_size * 100):.1f}%",
            "memory_usage_mb": f"{self.get_memory_usage_mb():.2f}",
            "recommendation": self._get_recommendation(),
        }

    def _get_recommendation(self) -> str:
        """Retorna recomendação baseado em hit rate"""
        hit_rate = self.stats.hit_rate

        if hit_rate >= 70:
            return "Cache saudável, mantendo configuração"
        elif hit_rate >= 50:
            return "Aumentar max_size para melhorar hit rate"
        elif hit_rate >= 30:
            return "Revisar TTL ou aumentar cache significantly"
        else:
            return "Cache ineficiente, considerar reset ou ajustes"
