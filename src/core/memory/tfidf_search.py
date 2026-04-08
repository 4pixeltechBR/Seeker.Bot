"""
Seeker.Bot — TF-IDF Offline Semantic Search
src/core/memory/tfidf_search.py

Fallback para busca semântica quando embeddings não estão disponíveis.
Usa TF-IDF (Term Frequency-Inverse Document Frequency) para similaridade textual.

Benefícios:
- Zero custo de API
- Funciona completamente offline
- Não requer GPU/VRAM
- O(N) complexity mas rápido para ~1000 fatos
"""

import logging
import math
from collections import Counter
from typing import Optional

log = logging.getLogger("seeker.memory.tfidf")


class TFIDFSearch:
    """
    TF-IDF based semantic search para fatos.
    Funciona como fallback quando Gemini Embedder não está disponível.
    """

    def __init__(self):
        """Inicializa o motor de busca TF-IDF."""
        self.documents: dict[int, str] = {}  # fact_id → text
        self.idf_cache: dict[str, float] = {}  # word → IDF score
        self.total_docs = 0

    def add_document(self, fact_id: int, text: str) -> None:
        """Adiciona um documento (fato) ao índice."""
        self.documents[fact_id] = text
        self.total_docs = len(self.documents)
        self._rebuild_idf()

    def remove_document(self, fact_id: int) -> None:
        """Remove um documento do índice."""
        if fact_id in self.documents:
            del self.documents[fact_id]
            self.total_docs = len(self.documents)
            self._rebuild_idf()

    def _tokenize(self, text: str) -> list[str]:
        """Tokeniza texto em palavras."""
        # Simples: lowercase + split por espaço/pontuação
        text = text.lower()
        # Remove pontuação comum
        for char in ".,!?;:()[]{}\"'":
            text = text.replace(char, " ")
        tokens = text.split()
        return [t for t in tokens if len(t) > 2]  # Ignora palavras muito curtas

    def _rebuild_idf(self) -> None:
        """Reconstrói cache de IDF scores."""
        if not self.documents:
            self.idf_cache = {}
            return

        # Conta quantos documentos contêm cada palavra
        word_doc_count: dict[str, int] = Counter()
        for text in self.documents.values():
            tokens = set(self._tokenize(text))
            word_doc_count.update(tokens)

        # Calcula IDF para cada palavra
        # IDF = log(total_docs / docs_containing_word)
        self.idf_cache = {}
        for word, count in word_doc_count.items():
            self.idf_cache[word] = math.log(self.total_docs / count) if count > 0 else 0

    def _calculate_tf(self, tokens: list[str]) -> dict[str, float]:
        """Calcula Term Frequency para uma lista de tokens."""
        if not tokens:
            return {}
        tf = Counter(tokens)
        max_freq = max(tf.values()) if tf else 1
        # Normaliza TF entre 0 e 1
        return {word: count / max_freq for word, count in tf.items()}

    def _calculate_tfidf(self, text: str) -> dict[str, float]:
        """Calcula TF-IDF score para um texto."""
        tokens = self._tokenize(text)
        tf = self._calculate_tf(tokens)

        tfidf = {}
        for word, tf_score in tf.items():
            idf_score = self.idf_cache.get(word, 0)
            tfidf[word] = tf_score * idf_score

        return tfidf

    def _cosine_similarity(self, vec1: dict[str, float], vec2: dict[str, float]) -> float:
        """Calcula similaridade de cosseno entre dois vetores TF-IDF."""
        # Produto escalar
        dot_product = 0
        for word in vec1:
            if word in vec2:
                dot_product += vec1[word] * vec2[word]

        # Normas
        norm1 = math.sqrt(sum(v**2 for v in vec1.values())) if vec1 else 0
        norm2 = math.sqrt(sum(v**2 for v in vec2.values())) if vec2 else 0

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def search(
        self, query: str, top_k: int = 5, min_similarity: float = 0.1
    ) -> list[tuple[int, float]]:
        """
        Busca documentos similares ao query.

        Args:
            query: Texto a buscar
            top_k: Número máximo de resultados
            min_similarity: Score mínimo de similaridade (0-1)

        Returns:
            Lista de (fact_id, similarity_score) ordenada por score
        """
        if not self.documents:
            return []

        query_tfidf = self._calculate_tfidf(query)
        if not query_tfidf:
            # Query vazia ou sem palavras válidas
            return []

        # Calcula similaridade com cada documento
        results = []
        for fact_id, text in self.documents.items():
            doc_tfidf = self._calculate_tfidf(text)
            similarity = self._cosine_similarity(query_tfidf, doc_tfidf)

            if similarity >= min_similarity:
                results.append((fact_id, similarity))

        # Ordena por similaridade descrescente
        results.sort(key=lambda x: x[1], reverse=True)

        return results[:top_k]

    def get_stats(self) -> dict:
        """Retorna estatísticas do índice."""
        return {
            "total_documents": self.total_docs,
            "vocabulary_size": len(self.idf_cache),
            "avg_doc_size": (
                sum(len(self._tokenize(text)) for text in self.documents.values())
                / self.total_docs
                if self.total_docs > 0
                else 0
            ),
        }
