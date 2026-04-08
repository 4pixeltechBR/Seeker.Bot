"""
Seeker.Bot — Embedding Search
src/core/memory/embeddings.py

Busca semântica com embeddings PERSISTIDOS.

Diferenças do original:
  - Embeddings salvos no SQLite via MemoryProtocol (sobrevivem a restart)
  - Startup: carrega vetores do disco (1 query SQL, ~50ms para 5.000 fatos)
  - Novos fatos: embeda e persiste incrementalmente
  - Zero API calls no restart — só embeda fatos NOVOS

Usa Gemini Embedding 2: 100 RPM, 1.000/dia grátis.

"usuário gosta de futebol" encontra "interesse em jogos do Flamengo"
— o LIKE não encontra, o embedding sim.
"""

import asyncio
import logging
import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from src.core.memory.tfidf_search import TFIDFSearch

if TYPE_CHECKING:
    from src.core.memory.protocol import MemoryProtocol

log = logging.getLogger("seeker.memory.embeddings")


@dataclass
class EmbeddingResult:
    text: str
    vector: list[float]
    model: str = ""


class GeminiEmbedder:
    """
    Gera embeddings via Gemini Embedding 2.
    100 RPM, 1.000 requisições/dia grátis.
    
    Cache em memória por sessão — evita re-embedar o mesmo texto
    dentro da mesma execução (comum no ClaimComparator).
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    MODEL = "gemini-embedding-001"

    CACHE_MAX = 500
    CACHE_EVICT = 100

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._client = httpx.AsyncClient(timeout=10.0)

    async def embed(self, text: str) -> list[float]:
        """Gera embedding para um texto. Cache LRU em memória por sessão."""
        cache_key = text[:200]
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)  # LRU: move para o final
            return self._cache[cache_key]

        try:
            resp = await self._client.post(
                f"{self.BASE_URL}/{self.MODEL}:embedContent",
                headers={"x-goog-api-key": self.api_key},
                json={
                    "model": f"models/{self.MODEL}",
                    "content": {
                        "parts": [{"text": text[:2000]}]
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            vector = data["embedding"]["values"]

            # Cache LRU — evicta os menos usados recentemente
            self._cache[cache_key] = vector
            while len(self._cache) > self.CACHE_MAX:
                self._cache.popitem(last=False)  # Remove o mais antigo (LRU)

            return vector

        except Exception as e:
            log.warning(f"[embedding] Falha: {e}")
            return []

    async def close(self):
        """Fecha client HTTP persistente."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embeda múltiplos textos em paralelo (com rate limit awareness)."""
        # Limita concorrência para não estourar os 100 RPM
        semaphore = asyncio.Semaphore(10)

        async def _embed_with_semaphore(text: str) -> list[float]:
            async with semaphore:
                return await self.embed(text)

        tasks = [_embed_with_semaphore(t) for t in texts]
        return await asyncio.gather(*tasks)

    @staticmethod
    def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """Similaridade cosseno entre dois vetores."""
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0

        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)


class SemanticSearch:
    """
    Busca semântica com embeddings PERSISTIDOS no SQLite.

    Startup: carrega todos os vetores de uma vez (1 query SQL).
    Novos fatos: embeda e persiste incrementalmente.
    Busca: cosine similarity em RAM sobre vetores já carregados.

    Performance projetada:
      100 fatos  → startup ~5ms,  busca <1ms
      1.000      → startup ~20ms, busca ~3ms
      5.000      → startup ~80ms, busca ~15ms
      50.000     → startup ~800ms, busca ~150ms (hora de FAISS)
    """

    FAISS_WARNING_THRESHOLD = 30_000

    def __init__(self, embedder: GeminiEmbedder, memory: "MemoryProtocol"):
        self.embedder = embedder
        self.memory = memory
        self._vectors: dict[int, list[float]] = {}
        self._tfidf_search = TFIDFSearch()  # Fallback offline para quando Gemini falha
        self._loaded = False

    async def load(self) -> None:
        """
        Carrega embeddings do SQLite. UMA query, zero API calls.
        Chamado no startup do pipeline.
        Também carrega fatos em TF-IDF para fallback offline.
        """
        self._vectors = await self.memory.load_all_embeddings()
        self._loaded = True
        log.info(f"[semantic] {len(self._vectors)} embeddings carregados do disco")

        # Carregar fatos em TF-IDF como fallback
        facts = await self.memory.get_facts(min_confidence=0.0, limit=9999)
        for fact in facts:
            self._tfidf_search.add_document(fact["id"], fact["fact"])
        log.info(f"[semantic] TF-IDF carregado com {len(facts)} documentos (fallback offline)")

        if len(self._vectors) > self.FAISS_WARNING_THRESHOLD:
            log.warning(
                f"[semantic] {len(self._vectors)} vetores em memória. "
                f"Considere migrar para FAISS/hnswlib para busca eficiente."
            )

    async def ensure_indexed(self) -> None:
        """
        Garante que fatos sem embedding sejam indexados.
        Roda no startup DEPOIS do load() — só embeda fatos NOVOS.
        """
        if not self._loaded:
            await self.load()

        facts = await self.memory.get_facts(min_confidence=0.0, limit=9999)
        to_embed = [f for f in facts if f["id"] not in self._vectors]

        if not to_embed:
            return

        log.info(f"[semantic] Indexando {len(to_embed)} fatos novos...")

        # Batch de 20 para respeitar rate limit (100 RPM Gemini Embed)
        BATCH_SIZE = 20
        indexed = 0

        for i in range(0, len(to_embed), BATCH_SIZE):
            batch = to_embed[i:i + BATCH_SIZE]
            texts = [f["fact"] for f in batch]
            vectors = await self.embedder.embed_batch(texts)

            for fact, vector in zip(batch, vectors):
                if vector:
                    self._vectors[fact["id"]] = vector
                    await self.memory.store_embedding(fact["id"], vector)
                    # Sincronizar com TF-IDF
                    self._tfidf_search.add_document(fact["id"], fact["fact"])
                    indexed += 1

        log.info(f"[semantic] {indexed} fatos indexados ({len(self._vectors)} total)")

    async def add(self, fact_id: int, text: str) -> None:
        """Embeda e persiste UM fato novo (chamado após upsert_fact). Sincroniza com TF-IDF."""
        if fact_id < 0:
            return
        vector = await self.embedder.embed(text)
        if vector:
            self._vectors[fact_id] = vector
            await self.memory.store_embedding(fact_id, vector)

        # Sincronizar com TF-IDF sempre (mesmo se Gemini falhar)
        self._tfidf_search.add_document(fact_id, text)

    async def remove(self, fact_id: int) -> None:
        """Remove embedding (chamado pelo DecayEngine ao deletar fato). Remove também de TF-IDF."""
        self._vectors.pop(fact_id, None)
        self._tfidf_search.remove_document(fact_id)  # Remover de TF-IDF também
        try:
            await self.memory.delete_embedding(fact_id)
        except Exception:
            pass  # Já pode ter sido deletado via CASCADE

    async def find_similar(
        self,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.3,
    ) -> list[tuple[int, float]]:
        """
        Retorna: [(fact_id, similarity)] ordenado por similaridade.

        Tenta Gemini primeiro; se falhar, fallback para TF-IDF offline.
        Faz cosine similarity em Python puro sobre vetores em RAM.
        """
        # Tentar Gemini primeiro
        query_vec = await self.embedder.embed(query)
        if query_vec:
            scores = []
            for fact_id, fact_vec in self._vectors.items():
                sim = GeminiEmbedder.cosine_similarity(query_vec, fact_vec)
                if sim >= min_similarity:
                    scores.append((fact_id, sim))

            if scores:
                scores.sort(key=lambda x: x[1], reverse=True)
                log.debug(f"[semantic] {len(scores)} matches via Gemini")
                return scores[:top_k]

        # Fallback: TF-IDF quando Gemini falha ou retorna vec vazio
        log.debug("[semantic] Gemini indisponível/vazio, usando TF-IDF fallback")
        tfidf_results = self._tfidf_search.search(query, top_k=top_k, min_similarity=0.1)

        if tfidf_results:
            log.debug(f"[semantic] {len(tfidf_results)} matches via TF-IDF")
        else:
            log.debug("[semantic] Nenhum match semântico (Gemini + TF-IDF)")

        return tfidf_results

    async def find_similar_facts(
        self,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.3,
    ) -> list[dict]:
        """
        Encontra fatos semanticamente similares à query.
        Retorna lista de dicts com fact data + similarity score.
        
        Método de compatibilidade — o pipeline usa este.
        Internamente delega pra find_similar() + hydration dos fatos.
        """
        similar_ids = await self.find_similar(query, top_k, min_similarity)
        if not similar_ids:
            # Fallback pra LIKE
            log.debug("[semantic] Nenhum match semântico, usando LIKE")
            return await self.memory.search_facts(query, limit=top_k)

        # Hydrata com dados completos dos fatos
        all_facts = await self.memory.get_facts(min_confidence=0.0, limit=9999)
        fact_map = {f["id"]: f for f in all_facts}

        results = []
        for fact_id, similarity in similar_ids:
            if fact_id in fact_map:
                fact = dict(fact_map[fact_id])
                fact["similarity"] = round(similarity, 3)
                results.append(fact)

        return results
