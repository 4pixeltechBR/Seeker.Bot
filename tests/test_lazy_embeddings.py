"""
Tests para lazy embeddings (FASE 7.1 Performance Optimization).

Valida que:
1. load() carrega apenas metadados (rápido)
2. find_similar() lazy-carrega vetores sob demanda
3. LRU eviction funciona quando cache fica cheio
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.core.memory.embeddings import GeminiEmbedder, SemanticSearch
from src.core.memory.tfidf_search import TFIDFSearch


class MockMemory:
    """Mock do MemoryProtocol para testes."""
    async def load_all_embeddings(self):
        """Retorna dict vazio com only IDs (lazy loading)."""
        return {1: [], 2: [], 3: []}  # IDs 1-3 existem no DB

    async def load_embedding(self, fact_id: int):
        """Carrega embedding individual sob demanda."""
        embeddings = {
            1: [0.1, 0.2, 0.3],
            2: [0.4, 0.5, 0.6],
            3: [0.7, 0.8, 0.9],
        }
        return embeddings.get(fact_id)

    async def get_facts(self, min_confidence=0.0, limit=9999):
        return [
            {"id": 1, "fact": "Python programming"},
            {"id": 2, "fact": "JavaScript basics"},
            {"id": 3, "fact": "Go lang"},
        ]

    async def store_embedding(self, fact_id, vector):
        pass

    async def delete_embedding(self, fact_id):
        pass

    async def search_facts(self, query, limit=5):
        return []


class TestLazyEmbeddings:
    """Testa lazy loading de embeddings."""

    @pytest.mark.asyncio
    async def test_load_loads_only_metadata(self):
        """load() deve carregar apenas IDs (não os vetores)."""
        memory = MockMemory()
        embedder = GeminiEmbedder("fake_key")
        search = SemanticSearch(embedder, memory)

        # Antes de load
        assert len(search._vector_ids) == 0
        assert len(search._vectors) == 0

        # Após load
        await search.load()

        # Metadados carregados (IDs)
        assert len(search._vector_ids) == 3
        assert 1 in search._vector_ids
        assert 2 in search._vector_ids
        assert 3 in search._vector_ids

        # Vetores AINDA vazios (lazy loading)
        assert len(search._vectors) == 0

    @pytest.mark.asyncio
    async def test_get_vector_lazy_loads_on_demand(self):
        """_get_vector_lazy deve carregar vetores sob demanda."""
        memory = MockMemory()
        embedder = GeminiEmbedder("fake_key")
        search = SemanticSearch(embedder, memory)
        await search.load()

        # Pedir vetor 1
        vector = await search._get_vector_lazy(1)
        assert vector == [0.1, 0.2, 0.3]
        assert len(search._vectors) == 1  # Agora em cache

        # Pedir vetor 2
        vector = await search._get_vector_lazy(2)
        assert vector == [0.4, 0.5, 0.6]
        assert len(search._vectors) == 2  # Ambos em cache

    @pytest.mark.asyncio
    async def test_lru_eviction_when_cache_full(self):
        """LRU eviction deve remover vetores menos usados quando cache fica cheio."""
        memory = MockMemory()
        embedder = GeminiEmbedder("fake_key")
        search = SemanticSearch(embedder, memory)
        search._max_cached = 2  # Cache pequeno para teste
        await search.load()

        # Carregar 2 vetores (cache cheio)
        await search._get_vector_lazy(1)
        await search._get_vector_lazy(2)
        assert len(search._vectors) == 2

        # Carregar 3º vetor → deve evocar o 1º (oldest)
        await search._get_vector_lazy(3)
        assert len(search._vectors) == 2  # Ainda 2 (LRU eviction)
        assert 1 not in search._vectors  # 1 foi evictado
        assert 2 in search._vectors  # 2 permanece
        assert 3 in search._vectors  # 3 foi adicionado

    @pytest.mark.asyncio
    async def test_get_vector_lazy_returns_none_for_nonexistent(self):
        """_get_vector_lazy retorna None se ID não existe no DB."""
        memory = MockMemory()
        embedder = GeminiEmbedder("fake_key")
        search = SemanticSearch(embedder, memory)
        await search.load()

        # Pedir vetor que não existe
        vector = await search._get_vector_lazy(999)
        assert vector is None

    @pytest.mark.asyncio
    async def test_find_similar_lazy_loads_vectors(self):
        """find_similar deve lazy-carregar vetores durante busca."""
        memory = MockMemory()

        # Mock embedder que retorna vetor da query
        embedder = AsyncMock(spec=GeminiEmbedder)
        embedder.embed = AsyncMock(return_value=[0.15, 0.25, 0.35])

        search = SemanticSearch(embedder, memory)
        await search.load()

        # Antes da busca, cache vazio
        assert len(search._vectors) == 0

        # Fazer busca
        results = await search.find_similar("Python")

        # Após busca, vetores foram lazy-carregados
        assert len(search._vectors) > 0  # Alguns vetores em cache agora

    @pytest.mark.asyncio
    async def test_add_synchronizes_vector_ids(self):
        """add() deve sincronizar _vector_ids."""
        memory = MockMemory()

        # Mock embedder para evitar chamadas reais à API
        embedder = AsyncMock(spec=GeminiEmbedder)
        embedder.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

        search = SemanticSearch(embedder, memory)
        await search.load()

        # Adicionar novo fato
        await search.add(999, "Nova linguagem")

        # Verificar que 999 está em _vector_ids
        assert 999 in search._vector_ids

    @pytest.mark.asyncio
    async def test_remove_synchronizes_vector_ids(self):
        """remove() deve sincronizar _vector_ids."""
        memory = MockMemory()
        embedder = GeminiEmbedder("fake_key")
        search = SemanticSearch(embedder, memory)
        await search.load()

        # Verificar que 1 existe
        assert 1 in search._vector_ids

        # Remover fato 1
        await search.remove(1)

        # Verificar que 1 foi removido de _vector_ids
        assert 1 not in search._vector_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
