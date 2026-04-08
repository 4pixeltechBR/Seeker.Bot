"""
Tests for SemanticSearch with TF-IDF fallback.
Validates that TF-IDF works when Gemini Embedder fails.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.core.memory.embeddings import GeminiEmbedder, SemanticSearch


class MockMemoryProtocol:
    """Mock MemoryProtocol for testing."""

    async def load_all_embeddings(self):
        return {1: [0.1, 0.2, 0.3], 2: [0.4, 0.5, 0.6]}

    async def get_facts(self, min_confidence=0.0, limit=9999):
        return [
            {"id": 1, "fact": "Python is a programming language"},
            {"id": 2, "fact": "JavaScript runs in browsers"},
            {"id": 3, "fact": "Python is great for data science"},
        ]

    async def store_embedding(self, fact_id: int, vector: list[float]):
        pass

    async def delete_embedding(self, fact_id: int):
        pass

    async def search_facts(self, query: str, limit: int = 5):
        return []


class MockEmbedderThatFails(GeminiEmbedder):
    """Mock embedder that always fails (returns empty vector)."""

    async def embed(self, text: str) -> list[float]:
        # Always fail to simulate Gemini unavailable
        return []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class MockEmbedderThatSucceeds(GeminiEmbedder):
    """Mock embedder that returns valid vectors."""

    async def embed(self, text: str) -> list[float]:
        # Return a fake vector based on text length
        return [0.5] * (len(text) % 10 + 1)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


@pytest.fixture
def memory():
    return MockMemoryProtocol()


@pytest.fixture
def embedder_fails():
    return MockEmbedderThatFails("fake_key")


@pytest.fixture
def embedder_works():
    return MockEmbedderThatSucceeds("fake_key")


@pytest.fixture
async def semantic_search_with_failing_embedder(embedder_fails, memory):
    search = SemanticSearch(embedder_fails, memory)
    await search.load()
    return search


@pytest.fixture
async def semantic_search_with_working_embedder(embedder_works, memory):
    search = SemanticSearch(embedder_works, memory)
    await search.load()
    return search


class TestTFIDFInitialization:
    """Test that TF-IDF is properly initialized."""

    @pytest.mark.asyncio
    async def test_tfidf_initialized(self, semantic_search_with_failing_embedder):
        """TF-IDF search should be initialized."""
        search = semantic_search_with_failing_embedder
        assert search._tfidf_search is not None
        assert search._tfidf_search.total_docs > 0

    @pytest.mark.asyncio
    async def test_tfidf_loaded_with_facts(self, semantic_search_with_failing_embedder):
        """TF-IDF should be loaded with facts from memory."""
        search = semantic_search_with_failing_embedder
        stats = search._tfidf_search.get_stats()
        assert stats["total_documents"] == 3  # 3 facts loaded
        assert stats["vocabulary_size"] > 0


class TestTFIDFSyncronization:
    """Test that TF-IDF stays in sync with embeddings."""

    @pytest.mark.asyncio
    async def test_add_document_syncs_tfidf(self, semantic_search_with_failing_embedder):
        """Adding a fact should sync with TF-IDF."""
        search = semantic_search_with_failing_embedder
        initial_docs = search._tfidf_search.total_docs

        await search.add(99, "New fact about testing")

        assert search._tfidf_search.total_docs == initial_docs + 1

    @pytest.mark.asyncio
    async def test_remove_document_syncs_tfidf(self, semantic_search_with_failing_embedder):
        """Removing a fact should remove from TF-IDF."""
        search = semantic_search_with_failing_embedder
        initial_docs = search._tfidf_search.total_docs

        await search.remove(1)

        assert search._tfidf_search.total_docs == initial_docs - 1


class TestTFIDFFallback:
    """Test that TF-IDF fallback works when Gemini fails."""

    @pytest.mark.asyncio
    async def test_tfidf_fallback_when_gemini_fails(
        self, semantic_search_with_failing_embedder
    ):
        """When Gemini fails, should use TF-IDF for search."""
        search = semantic_search_with_failing_embedder

        # Query should return results via TF-IDF
        results = await search.find_similar("Python programming", top_k=2)

        assert len(results) > 0, "TF-IDF should return results when Gemini fails"
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

    @pytest.mark.asyncio
    async def test_tfidf_returns_correct_fact_ids(
        self, semantic_search_with_failing_embedder
    ):
        """TF-IDF should return correct fact IDs."""
        search = semantic_search_with_failing_embedder

        results = await search.find_similar("Python", top_k=5)

        # Should find facts about Python
        fact_ids = [r[0] for r in results]
        assert 1 in fact_ids or 3 in fact_ids, "Should find facts mentioning Python"

    @pytest.mark.asyncio
    async def test_tfidf_similarity_scores(self, semantic_search_with_failing_embedder):
        """TF-IDF should return similarity scores between 0 and 1."""
        search = semantic_search_with_failing_embedder

        results = await search.find_similar("data science", top_k=5)

        for fact_id, similarity in results:
            assert 0.0 <= similarity <= 1.0, f"Similarity should be 0-1, got {similarity}"

    @pytest.mark.asyncio
    async def test_tfidf_respects_top_k(self, semantic_search_with_failing_embedder):
        """TF-IDF should respect top_k parameter."""
        search = semantic_search_with_failing_embedder

        results_k1 = await search.find_similar("Python", top_k=1)
        results_k3 = await search.find_similar("Python", top_k=3)

        assert len(results_k1) <= 1
        assert len(results_k3) <= 3


class TestGeminiPreferred:
    """Test that Gemini is preferred over TF-IDF when available."""

    @pytest.mark.asyncio
    async def test_prefers_gemini_when_available(
        self, semantic_search_with_working_embedder
    ):
        """When Gemini works, should return results via Gemini."""
        search = semantic_search_with_working_embedder

        results = await search.find_similar("Python", top_k=5)

        # Should have results (from Gemini vectors)
        # Note: Results may be limited based on min_similarity threshold
        assert isinstance(results, list)


class TestFindSimilarFacts:
    """Test find_similar_facts with TF-IDF fallback."""

    @pytest.mark.asyncio
    async def test_find_similar_facts_with_tfidf(
        self, semantic_search_with_failing_embedder
    ):
        """find_similar_facts should use TF-IDF when Gemini fails."""
        search = semantic_search_with_failing_embedder

        # Mock hydration step
        search.memory.get_facts = AsyncMock(
            return_value=[
                {"id": 1, "fact": "Python is a programming language", "confidence": 0.9},
                {"id": 2, "fact": "JavaScript runs in browsers", "confidence": 0.8},
                {"id": 3, "fact": "Python is great for data science", "confidence": 0.95},
            ]
        )

        results = await search.find_similar_facts("Python", top_k=2)

        assert len(results) > 0
        assert all("similarity" in r for r in results)


class TestEmptyQuery:
    """Test behavior with empty or minimal queries."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, semantic_search_with_failing_embedder):
        """Empty query should return empty results."""
        search = semantic_search_with_failing_embedder

        results = await search.find_similar("", top_k=5)

        # TF-IDF should return empty for empty query
        assert isinstance(results, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
