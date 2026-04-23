"""
Seeker.Bot — BM25 Re-ranker
src/core/memory/bm25.py

Portabilidade cirúrgica do MemPalace.
Implementa Okapi BM25 para re-ranking de resultados semânticos.
"""

import math
import re

_TOKEN_RE = re.compile(r"\w{2,}", re.UNICODE)

def tokenize(text: str) -> list[str]:
    """Lowercase + strip to alphanumeric tokens of length ≥ 2."""
    return _TOKEN_RE.findall(text.lower())

def bm25_scores(
    query: str,
    documents: list[str],
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """
    Computa scores Okapi-BM25 para a query contra cada documento.
    IDF é computado sobre o corpus provido (candidatos do vector search).
    """
    n_docs = len(documents)
    query_terms = set(tokenize(query))
    if not query_terms or n_docs == 0:
        return [0.0] * n_docs

    tokenized = [tokenize(d) for d in documents]
    doc_lens = [len(toks) for toks in tokenized]
    if not any(doc_lens):
        return [0.0] * n_docs
    avgdl = sum(doc_lens) / n_docs or 1.0

    # Document frequency
    df = {term: 0 for term in query_terms}
    for toks in tokenized:
        seen = set(toks) & query_terms
        for term in seen:
            df[term] += 1

    idf = {term: math.log((n_docs - df[term] + 0.5) / (df[term] + 0.5) + 1) for term in query_terms}

    scores = []
    for toks, dl in zip(tokenized, doc_lens):
        if dl == 0:
            scores.append(0.0)
            continue
        tf: dict = {}
        for t in toks:
            if t in query_terms:
                tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for term, freq in tf.items():
            num = freq * (k1 + 1)
            den = freq + k1 * (1 - b + b * dl / avgdl)
            score += idf[term] * num / den
        scores.append(score)
    return scores

def hybrid_rank(
    results: list[dict],
    query: str,
    vector_weight: float = 0.6,
    bm25_weight: float = 0.4,
) -> list[dict]:
    """
    Re-ranka resultados por combinação de similaridade vetorial e BM25.
    
    Results deve conter dicts com 'fact' (texto) e 'similarity' (vector score).
    Mutates results para adicionar 'bm25_score' e 'hybrid_score'.
    """
    if not results:
        return results

    docs = [r.get("fact", "") for r in results]
    bm25_raw = bm25_scores(query, docs)
    max_bm25 = max(bm25_raw) if bm25_raw else 0.0
    bm25_norm = [s / max_bm25 for s in bm25_raw] if max_bm25 > 0 else [0.0] * len(bm25_raw)

    scored = []
    for r, raw, norm in zip(results, bm25_raw, bm25_norm):
        vec_sim = r.get("similarity", 0.0)
        hybrid_score = (vector_weight * vec_sim) + (bm25_weight * norm)
        r["bm25_score"] = round(raw, 3)
        r["hybrid_score"] = round(hybrid_score, 3)
        scored.append((hybrid_score, r))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [r for _, r in scored]
