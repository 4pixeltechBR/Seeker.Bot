"""
Testes para SmartEmbeddingCache — Sprint 11.2
LRU cache com hit rate tracking
"""

import pytest
import asyncio
from datetime import datetime, timedelta

from src.core.memory.embedding_cache import (
    SmartEmbeddingCache,
    CachedEmbedding,
    CacheStats,
)


class TestSmartEmbeddingCache:
    """Testes de SmartEmbeddingCache"""

    @pytest.fixture
    def cache(self):
        """Instância de cache para testes"""
        return SmartEmbeddingCache(max_size=100, evict_percentage=10.0)

    @pytest.mark.asyncio
    async def test_cache_put_and_get(self, cache):
        """Testa armazenar e recuperar embedding"""
        texto = "Hello world"
        embedding = b"embedding_bytes_123"

        # Nenhum embedding no cache inicialmente
        result = await cache.get_embedding(texto)
        assert result is None

        # Armazenar
        await cache.put_embedding(texto, embedding)

        # Recuperar
        result = await cache.get_embedding(texto)
        assert result == embedding

    @pytest.mark.asyncio
    async def test_cache_hit_rate(self, cache):
        """Testa cálculo de hit rate"""
        assert cache.stats.hit_rate == 0.0

        # 4 misses
        await cache.get_embedding("texto1")
        await cache.get_embedding("texto2")
        await cache.get_embedding("texto3")
        await cache.get_embedding("texto4")

        # Armazenar
        await cache.put_embedding("texto1", b"emb1")

        # 2 hits
        await cache.get_embedding("texto1")
        await cache.get_embedding("texto1")

        # Hit rate = 2 hits / 6 lookups = 33.3%
        assert 33 < cache.stats.hit_rate < 34

    @pytest.mark.asyncio
    async def test_cache_lru_eviction(self, cache):
        """Testa evicção LRU quando cache está cheio"""
        # Pequeno cache para teste
        small_cache = SmartEmbeddingCache(max_size=5, evict_percentage=20.0)

        # Preencher cache até max_size
        for i in range(5):
            await small_cache.put_embedding(f"texto{i}", f"emb{i}".encode())

        assert len(small_cache._cache) == 5

        # Adicionar mais um → deve evictar
        await small_cache.put_embedding("texto5", b"emb5")

        # Deve ter evictado 1 (20% de 5)
        assert len(small_cache._cache) == 5
        assert small_cache.stats.total_evictions >= 1

    @pytest.mark.asyncio
    async def test_cache_lru_priority(self, cache):
        """Testa que menos acessados são evictados primeiro"""
        small_cache = SmartEmbeddingCache(max_size=3, evict_percentage=33.0)

        # Adicionar 3 embeddings
        await small_cache.put_embedding("text_popular", b"emb1")
        await small_cache.put_embedding("text_medium", b"emb2")
        await small_cache.put_embedding("text_unpopular", b"emb3")

        # Acessar popular 5 vezes
        for _ in range(5):
            await small_cache.get_embedding("text_popular")

        # Acessar medium 2 vezes
        for _ in range(2):
            await small_cache.get_embedding("text_medium")

        # unpopular nunca é acessado novamente

        # Adicionar novo → deve evictar unpopular
        await small_cache.put_embedding("text_new", b"emb4")

        # Verificar que popular e medium ainda estão lá
        popular = await small_cache.get_embedding("text_popular")
        medium = await small_cache.get_embedding("text_medium")

        assert popular is not None
        assert medium is not None

    @pytest.mark.asyncio
    async def test_cache_ttl_expiration(self, cache):
        """Testa que embeddings expiram após TTL"""
        short_ttl_cache = SmartEmbeddingCache(
            max_size=100,
            ttl_seconds=1,  # 1 segundo
        )

        texto = "temporary text"
        embedding = b"temporary_emb"

        await short_ttl_cache.put_embedding(texto, embedding)

        # Imediatamente disponível
        result = await short_ttl_cache.get_embedding(texto)
        assert result == embedding

        # Esperar TTL expirar
        await asyncio.sleep(1.1)

        # Deve retornar None (TTL expirado)
        result = await short_ttl_cache.get_embedding(texto)
        assert result is None

    @pytest.mark.asyncio
    async def test_force_refresh(self, cache):
        """Testa force_refresh ignora cache"""
        texto = "test text"
        await cache.put_embedding(texto, b"old_embedding")

        # Normal get retorna cached
        result = await cache.get_embedding(texto)
        assert result == b"old_embedding"

        # Force refresh retorna None
        result = await cache.get_embedding(texto, force_refresh=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_access_count(self, cache):
        """Testa que access_count é incrementado"""
        texto = "test"
        await cache.put_embedding(texto, b"emb")

        key = cache._hash_texto(texto)
        cached = cache._cache[key]

        assert cached.access_count == 0

        # Acessar 3 vezes
        for _ in range(3):
            await cache.get_embedding(texto)

        assert cached.access_count == 3

    def test_cache_stats(self, cache):
        """Testa estatísticas do cache"""
        stats = cache.get_stats()

        assert stats["total_lookups"] == 0
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0
        assert stats["current_size"] == 0

    def test_cache_memory_usage(self, cache):
        """Testa estimativa de memória"""
        # Cache vazio = 0 MB
        usage = cache.get_memory_usage_mb()
        assert usage == 0.0

    @pytest.mark.asyncio
    async def test_cache_clear(self, cache):
        """Testa limpeza de cache"""
        await cache.put_embedding("text1", b"emb1")
        await cache.put_embedding("text2", b"emb2")

        assert len(cache._cache) == 2

        cache.clear()

        assert len(cache._cache) == 0

    @pytest.mark.asyncio
    async def test_cache_hot_embeddings(self, cache):
        """Testa ranking de embeddings mais acessados"""
        # Criar embeddings com diferentes access counts
        await cache.put_embedding("text1", b"emb1")
        await cache.put_embedding("text2", b"emb2")
        await cache.put_embedding("text3", b"emb3")

        # text1: 5 acessos
        for _ in range(5):
            await cache.get_embedding("text1")

        # text2: 3 acessos
        for _ in range(3):
            await cache.get_embedding("text2")

        # text3: 1 acesso
        await cache.get_embedding("text3")

        hot = cache.get_hot_embeddings(top_n=3)

        # Ordem deve ser: text1 (5), text2 (3), text3 (1)
        assert hot[0][1] == 5  # text1 com 5 acessos
        assert hot[1][1] == 3  # text2 com 3 acessos
        assert hot[2][1] == 1  # text3 com 1 acesso

    def test_cache_health_status(self, cache):
        """Testa avaliação de saúde"""
        # Sem acessos = POOR
        status = cache.get_health_status()
        # Hit rate é 0%, logo POOR
        assert status["health_status"] in ["POOR", "ACCEPTABLE"]

        # Simular boa taxa de acerto (70%)
        cache.stats.cache_hits = 70
        cache.stats.cache_misses = 30
        cache.stats.total_lookups = 100

        status = cache.get_health_status()
        assert status["health_status"] == "GOOD"

        # Simular excelente taxa (80%)
        cache.stats.cache_hits = 200
        cache.stats.cache_misses = 50
        cache.stats.total_lookups = 250

        status = cache.get_health_status()
        assert status["health_status"] == "EXCELLENT"

    @pytest.mark.asyncio
    async def test_cache_hash_consistency(self, cache):
        """Testa que hash é consistente"""
        texto = "Hello world"

        hash1 = cache._hash_texto(texto)
        hash2 = cache._hash_texto(texto)

        assert hash1 == hash2
        assert len(hash1) == 16  # SHA256[:16]

    @pytest.mark.asyncio
    async def test_cache_update_existing(self, cache):
        """Testa atualizar embedding existente"""
        texto = "update test"

        await cache.put_embedding(texto, b"old_emb")
        result = await cache.get_embedding(texto)
        assert result == b"old_emb"

        # Atualizar
        await cache.put_embedding(texto, b"new_emb")
        result = await cache.get_embedding(texto)
        assert result == b"new_emb"


class TestCacheStats:
    """Testes de CacheStats"""

    def test_hit_rate_calculation(self):
        """Testa cálculo de hit rate"""
        stats = CacheStats()

        assert stats.hit_rate == 0.0

        stats.cache_hits = 8
        stats.total_lookups = 10

        assert stats.hit_rate == 80.0

    def test_miss_rate_calculation(self):
        """Testa cálculo de miss rate"""
        stats = CacheStats()

        stats.cache_hits = 3
        stats.total_lookups = 10

        assert stats.miss_rate == 70.0


class TestCachedEmbedding:
    """Testes de CachedEmbedding"""

    def test_age_calculation(self):
        """Testa cálculo de idade"""
        cached = CachedEmbedding(
            embedding=b"test",
            timestamp_created=datetime.utcnow() - timedelta(seconds=30),
            timestamp_last_accessed=datetime.utcnow(),
        )

        age = cached.age_seconds
        assert 29 < age < 31  # ~30 segundos

    def test_time_since_access(self):
        """Testa tempo desde último acesso"""
        cached = CachedEmbedding(
            embedding=b"test",
            timestamp_created=datetime.utcnow(),
            timestamp_last_accessed=datetime.utcnow() - timedelta(seconds=10),
        )

        time_since = cached.time_since_access_seconds
        assert 9 < time_since < 11  # ~10 segundos


# Run: pytest tests/test_embedding_cache.py -v
