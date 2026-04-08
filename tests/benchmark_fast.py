"""
Fast Benchmark focado em LAZY LOADING (sem TF-IDF overhead)
tests/benchmark_fast.py

Isola os ganhos de FASE 7.1-7.3 sem overhead de inicialização.
"""

import asyncio
import time
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock
import logging

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.memory.embeddings import GeminiEmbedder, SemanticSearch

log = logging.getLogger("benchmark")
logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(levelname)s: %(message)s"
)


class SimpleMockMemory:
    """Memory mock sem TF-IDF para teste rápido."""

    def __init__(self, num_facts: int = 5000):
        self.num_facts = num_facts
        self._embeddings = {}
        import random
        random.seed(42)
        for i in range(1, num_facts + 1):
            self._embeddings[i] = [random.random() for _ in range(768)]

    async def load_all_embeddings(self):
        """Retorna apenas IDs (lazy)."""
        return {fid: [] for fid in self._embeddings.keys()}

    async def load_embedding(self, fact_id: int):
        """Carrega individual."""
        return self._embeddings.get(fact_id)

    async def get_facts(self, min_confidence=0.0, limit=9999):
        return [{"id": i, "fact": f"Fact {i}"} for i in range(1, min(limit+1, self.num_facts+1))]

    async def store_embedding(self, fact_id, vector):
        pass

    async def delete_embedding(self, fact_id):
        pass

    async def search_facts(self, query, limit=5):
        return []

    async def commit(self):
        pass

    async def close(self):
        pass


async def test_startup_latency():
    """Testa startup com lazy loading."""
    print("\n" + "="*60)
    print("TEST 1: Startup Latency (Lazy Loading)")
    print("="*60)

    memory = SimpleMockMemory(num_facts=5000)
    embedder = AsyncMock(spec=GeminiEmbedder)

    search = SemanticSearch(embedder, memory)

    start = time.perf_counter()
    await search.load()
    elapsed = time.perf_counter() - start

    print(f"\n[OK] Startup time: {elapsed*1000:.1f}ms")
    print(f"  IDs loaded: {len(search._vector_ids)}")
    print(f"  Vectors in RAM: {len(search._vectors)} (lazy)")
    print(f"  Target <50ms: {'[OK]' if elapsed < 0.05 else '[FAIL] TOO SLOW'}")

    if elapsed > 0.05:
        print(f"\n[WARNING]  Startup slower than 50ms target!")
        print(f"   Current: {elapsed*1000:.1f}ms")
        print(f"   Issue: Likely TF-IDF loading or ensure_indexed() call")


async def test_lazy_load_individual():
    """Testa lazy load de um vetor individual."""
    print("\n" + "="*60)
    print("TEST 2: Single Vector Lazy Load")
    print("="*60)

    memory = SimpleMockMemory(num_facts=1000)
    embedder = AsyncMock(spec=GeminiEmbedder)
    search = SemanticSearch(embedder, memory)
    await search.load()

    start = time.perf_counter()
    vector = await search._get_vector_lazy(1)
    elapsed = time.perf_counter() - start

    print(f"\n[OK] Load 1 vector: {elapsed*1000:.2f}ms")
    print(f"  Vector size: {len(vector)} dims")

    # Batch load 100 vectors
    start = time.perf_counter()
    for i in range(1, 101):
        await search._get_vector_lazy(i)
    elapsed = time.perf_counter() - start

    print(f"[OK] Load 100 vectors: {elapsed*1000:.1f}ms ({elapsed*100:.2f}ms/vector)")


async def test_lru_cache():
    """Testa que LRU eviction funciona."""
    print("\n" + "="*60)
    print("TEST 3: LRU Cache Eviction")
    print("="*60)

    memory = SimpleMockMemory(num_facts=1000)
    embedder = AsyncMock(spec=GeminiEmbedder)
    search = SemanticSearch(embedder, memory)
    search._max_cached = 100
    await search.load()

    # Fill cache with 100
    for i in range(1, 101):
        await search._get_vector_lazy(i)

    print(f"\n[OK] Filled cache: {len(search._vectors)} vectors")
    initial_set = set(search._vectors.keys())

    # Add 50 more → should evict 50 oldest
    for i in range(101, 151):
        await search._get_vector_lazy(i)

    print(f"[OK] After adding 50 more: {len(search._vectors)} vectors")
    final_set = set(search._vectors.keys())

    evicted = initial_set - final_set
    print(f"[OK] Evicted oldest: {len(evicted)} vectors")
    print(f"[OK] New vectors present: {all(i in final_set for i in range(101, 151))}")


async def test_semantic_search_latency():
    """Testa latência de find_similar com lazy loading."""
    print("\n" + "="*60)
    print("TEST 4: find_similar Performance")
    print("="*60)

    memory = SimpleMockMemory(num_facts=1000)

    # Mock embedder com retorno consistente
    embedder = AsyncMock(spec=GeminiEmbedder)
    embedder.embed = AsyncMock(return_value=[0.5]*768)

    search = SemanticSearch(embedder, memory)
    search._max_cached = 500
    await search.load()

    # Cold cache
    start = time.perf_counter()
    results = await search.find_similar("test query", top_k=5)
    elapsed_cold = time.perf_counter() - start

    print(f"\n[OK] find_similar (cold cache): {elapsed_cold*1000:.1f}ms")
    print(f"  Matches: {len(results)}")
    print(f"  Cached vectors: {len(search._vectors)}")

    # Warm cache
    start = time.perf_counter()
    results = await search.find_similar("another query", top_k=5)
    elapsed_warm = time.perf_counter() - start

    print(f"[OK] find_similar (warm cache): {elapsed_warm*1000:.1f}ms")
    speedup = elapsed_cold / elapsed_warm if elapsed_warm > 0 else 1.0
    print(f"  Speedup: {speedup:.1f}x")


async def main():
    print("\n" + "="*60)
    print("FAST PERFORMANCE BENCHMARK — FASE 7 (Lazy Loading Only)")
    print("="*60)

    try:
        await test_startup_latency()
        await test_lazy_load_individual()
        await test_lru_cache()
        await test_semantic_search_latency()

        print("\n" + "="*60)
        print("✅ All tests completed")
        print("="*60)

    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
