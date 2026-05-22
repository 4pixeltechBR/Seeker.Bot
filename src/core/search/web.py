"""
Seeker.Bot — Web Search
src/core/search/web.py

Dois backends por prioridade:
  1. Tavily — AI-native, JSON otimizado pra LLMs, 1.000 credits/mês grátis
  2. Brave  — índice independente, $5 crédito/mês (~1.000 queries)

Tavily é a principal porque:
  - Resultados já vêm estruturados pra consumo de LLMs
  - Score de relevância por resultado
  - Snippets maiores e mais limpos
  - #1 em uso com agentes (LangChain, LlamaIndex, CrewAI)

Brave é o fallback porque:
  - Índice próprio (não depende de Google/Bing)
  - LLM Context API (fev/2026) — otimizado pra grounding
  - True Zero Data Retention
  - 99.99% uptime
"""

import os
import time
import json
import sqlite3
import asyncio
import logging
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

import httpx

log = logging.getLogger("seeker.search")


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = ""
    position: int = 0
    score: float = 0.0

    def to_context(self) -> str:
        score_str = f" (relevância: {self.score:.2f})" if self.score > 0 else ""
        return f"[{self.position}] {self.title}{score_str}\n{self.snippet}\nFonte: {self.url}"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "position": self.position,
            "score": self.score
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SearchResult":
        return cls(
            title=d.get("title", ""),
            url=d.get("url", ""),
            snippet=d.get("snippet", ""),
            source=d.get("source", ""),
            position=d.get("position", 0),
            score=d.get("score", 0.0)
        )


@dataclass
class SearchResponse:
    query: str
    results: list[SearchResult] = field(default_factory=list)
    backend: str = ""

    def to_context(self, max_results: int = 5) -> str:
        if not self.results:
            return f"Busca por '{self.query}': nenhum resultado."
        lines = [f"=== BUSCA WEB: '{self.query}' ({self.backend}) ==="]
        for r in self.results[:max_results]:
            lines.append(r.to_context())
            lines.append("")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "backend": self.backend,
            "results": [r.to_dict() for r in self.results]
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SearchResponse":
        results = [SearchResult.from_dict(r) for r in d.get("results", [])]
        return cls(
            query=d.get("query", ""),
            backend=d.get("backend", ""),
            results=results
        )


class SearchBackend(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> SearchResponse: ...


# ─────────────────────────────────────────────────────────────────────
# TAVILY — PRIMARY: AI-native search
# ─────────────────────────────────────────────────────────────────────


class TavilyBackend(SearchBackend):
    """
    Tavily Search API — feita de raiz pra LLMs e agentes.
    JSON estruturado com score de relevância por resultado.
    Free: 1.000 credits/mês (1 basic search = 1 credit).
    """

    BASE_URL = "https://api.tavily.com/search"

    # F-02: Circuit breaker. Apos N falhas 432 consecutivas (quota/key),
    # pula chamadas Tavily por COOLDOWN segundos em vez de tentar 25x seguidas.
    CIRCUIT_BREAKER_THRESHOLD = 3
    CIRCUIT_BREAKER_COOLDOWN = 300  # 5 min

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = None
        # Circuit breaker state
        self._consecutive_432 = 0
        self._circuit_open_until = 0.0  # monotonic timestamp

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # Atomic Clean: desabilita cota de headers e ignora ambiente
            self._client = httpx.AsyncClient(
                timeout=20.0,
                http2=False,      # Força HTTP/1.1 (evita bugs de compression/headers)
                trust_env=False,  # Ignora proxies/headers do Windows/Ambiente
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "SeekerBot/3.0 (CleanConnect)",
                    "Connection": "close" # Evita reuso de socket possivelmente sujo
                }
            )
        return self._client

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        import time
        # F-02: Circuit breaker check — pula se estamos no cooldown
        now = time.monotonic()
        if now < self._circuit_open_until:
            remaining = int(self._circuit_open_until - now)
            log.debug(f"[tavily] Circuit breaker ABERTO ({remaining}s restantes). Pulando.")
            return SearchResponse(query=query, backend="tavily")

        client = self._get_client()
        try:
            resp = await client.post(
                self.BASE_URL,
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            if resp.status_code == 432:
                # F-02: incrementa contador de falhas 432 consecutivas
                self._consecutive_432 += 1
                log.error(
                    f"[tavily] Erro 432 ({self._consecutive_432}/{self.CIRCUIT_BREAKER_THRESHOLD}). "
                    f"Tentando reset de cliente..."
                )
                # Abre circuit breaker se passou do threshold
                if self._consecutive_432 >= self.CIRCUIT_BREAKER_THRESHOLD:
                    self._circuit_open_until = now + self.CIRCUIT_BREAKER_COOLDOWN
                    log.warning(
                        f"[tavily] CIRCUIT BREAKER ABERTO por {self.CIRCUIT_BREAKER_COOLDOWN}s "
                        f"(apos {self._consecutive_432}x HTTP 432). "
                        f"Cheque quota/API key em app.tavily.com."
                    )
                # F-01: null-guard contra race condition entre coroutines simultaneas
                if self._client is not None:
                    try:
                        await self._client.aclose()
                    except Exception as close_err:
                        log.debug(f"[tavily] erro ao fechar cliente (ignorado): {close_err}")
                    self._client = None
            else:
                # F-02: qualquer resposta nao-432 reseta o contador (recovery)
                if self._consecutive_432 > 0:
                    log.info(f"[tavily] Recovery — circuit breaker RESET (status={resp.status_code})")
                self._consecutive_432 = 0

            resp.raise_for_status()
            data = resp.json()

            results = []
            for i, r in enumerate(data.get("results", [])):
                results.append(
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        snippet=r.get("content", ""),
                        source="tavily",
                        position=i + 1,
                        score=r.get("score", 0.0),
                    )
                )

            return SearchResponse(query=query, results=results, backend="tavily")
        except Exception as e:
            log.warning(f"[tavily] Busca falhou: {e}")
            return SearchResponse(query=query, backend="tavily")


# ─────────────────────────────────────────────────────────────────────
# BRAVE — FALLBACK: índice independente
# ─────────────────────────────────────────────────────────────────────


class BraveBackend(SearchBackend):
    """
    Brave Search API — índice próprio, não depende de Google/Bing.
    $5 crédito grátis/mês (~1.000 queries).
    """

    BASE_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    self.BASE_URL,
                    params={"q": query, "count": max_results},
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "gzip",
                        "X-Subscription-Token": self.api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                results = []
                for i, r in enumerate(data.get("web", {}).get("results", [])):
                    results.append(
                        SearchResult(
                            title=r.get("title", ""),
                            url=r.get("url", ""),
                            snippet=r.get("description", ""),
                            source="brave",
                            position=i + 1,
                        )
                    )

                return SearchResponse(query=query, results=results, backend="brave")
        except Exception as e:
            log.warning(f"[brave] Busca falhou: {e}")
            return SearchResponse(query=query, backend="brave")


# ─────────────────────────────────────────────────────────────────────
# PAGE FETCHER
# ─────────────────────────────────────────────────────────────────────


async def fetch_page_text(url: str, max_chars: int = 5000) -> str:
    """Busca conteúdo textual de uma URL."""
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "SeekerBot/1.0 (research agent)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            if "text/html" not in resp.headers.get("content-type", ""):
                return f"[Conteúdo não-HTML: {resp.headers.get('content-type', '')}]"

            import re
            import html as html_mod

            text = resp.text
            text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            text = html_mod.unescape(text)
            return text[:max_chars]
    except Exception as e:
        return f"[Erro ao buscar {url}: {e}]"


# ─────────────────────────────────────────────────────────────────────
# GOOGLE — GLOBAL SEARCH
# ─────────────────────────────────────────────────────────────────────


class GoogleBackend(SearchBackend):
    """
    Google Custom Search API — busca global na web.
    Usa cx específico e billing habilitado no projeto para ignorar restrições de site.
    """

    BASE_URL = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: str, cx: str):
        self.api_key = api_key
        self.cx = cx

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    self.BASE_URL,
                    params={
                        "key": self.api_key,
                        "cx": self.cx,
                        "q": query,
                        "num": min(max_results, 10),
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                results = []
                for i, r in enumerate(data.get("items", [])):
                    results.append(
                        SearchResult(
                            title=r.get("title", ""),
                            url=r.get("link", ""),
                            snippet=r.get("snippet", ""),
                            source="google",
                            position=i + 1,
                        )
                    )

                return SearchResponse(query=query, results=results, backend="google")
        except Exception as e:
            log.warning(f"[google] Busca falhou: {e}")
            return SearchResponse(query=query, backend="google")


# ─────────────────────────────────────────────────────────────────────
# LOCAL SEARCH CACHE — SQLite (24 Hours TTL)
# ─────────────────────────────────────────────────────────────────────


class SearchCache:
    """
    Cache local em SQLite para evitar buscas idênticas duplicadas dentro de 24 horas.
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.getcwd(), "data", "search_cache.db")
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache (
                        query TEXT PRIMARY KEY,
                        response TEXT,
                        timestamp REAL
                    )
                """)
                conn.commit()
        except Exception as e:
            log.error(f"[search-cache] Falha ao inicializar banco de dados: {e}")

    def get(self, query: str, ttl_seconds: float = 86400) -> dict | None:
        """Busca no cache e invalida se estourar o TTL (24h)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT response, timestamp FROM cache WHERE query = ?", (query.strip().lower(),))
                row = cursor.fetchone()
                if row:
                    response_str, timestamp = row
                    if time.time() - timestamp < ttl_seconds:
                        log.debug(f"[search-cache] Hit de cache para query: {query}")
                        return json.loads(response_str)
                    else:
                        # Limpa registro expirado
                        log.debug(f"[search-cache] TTL Expirado para: {query}. Deletando.")
                        conn.execute("DELETE FROM cache WHERE query = ?", (query.strip().lower(),))
                        conn.commit()
        except Exception as e:
            log.error(f"[search-cache] Falha ao buscar no cache: {e}")
        return None

    def set(self, query: str, response_data: dict):
        """Salva a resposta da query no banco de dados"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache (query, response, timestamp) VALUES (?, ?, ?)",
                    (query.strip().lower(), json.dumps(response_data), time.time())
                )
                conn.commit()
        except Exception as e:
            log.error(f"[search-cache] Falha ao salvar no cache: {e}")


# ─────────────────────────────────────────────────────────────────────
# WEB SEARCHER — Google → Tavily → Brave
# ─────────────────────────────────────────────────────────────────────


class WebSearcher:
    """
    Google (primary) → Tavily (fallback) → Brave (fallback).

    Uso:
        searcher = WebSearcher(google_key="...", google_cx="...", tavily_key="tvly-...", brave_key="BSA...")
        results = await searcher.search("MCP Anthropic 2026")
    """

    def __init__(self, tavily_key: str = "", brave_key: str = "", cost_tracker=None, google_key: str = "", google_cx: str = ""):
        self.backends: list[SearchBackend] = []
        self.cost_tracker = cost_tracker
        self.cache = SearchCache()

        # Válvula de segurança anti-loop (Sprint 12)
        self._session_query_count = 0
        self._last_search_time = 0.0
        self.max_session_queries = int(os.getenv("MAX_SEARCHES_PER_SESSION", "4"))

        if not google_key:
            google_key = os.getenv("GOOGLE_SEARCH_API_KEY", "")
        if not google_cx:
            google_cx = os.getenv("GOOGLE_SEARCH_CX", "")

        if google_key and google_cx:
            self.backends.append(GoogleBackend(google_key, google_cx))
            log.info("[search] ✅ Google Custom Search (primary) — ativado com escopo global")

        if tavily_key:
            keys = [k.strip() for k in tavily_key.split(",") if k.strip()]
            for k in keys:
                self.backends.append(TavilyBackend(k))
            log.info(f"[search] ✅ Tavily (fallback) — {len(keys)} key(s) carregada(s)")

        if brave_key:
            self.backends.append(BraveBackend(brave_key))
            log.info("[search] ✅ Brave (fallback) — índice independente")

        if not self.backends:
            log.warning("[search] ⚠️ Nenhum backend de busca configurado!")

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        # 1. Tenta recuperar do cache local primeiro (24h TTL)
        # O cache NÃO consome cota externa e NÃO conta para a trava de loop!
        cached_data = self.cache.get(query)
        if cached_data:
            log.info(f"[search] Cache HIT para query: '{query[:40]}'")
            return SearchResponse.from_dict(cached_data)

        # 2. Válvula de segurança anti-loop
        # Se a inatividade for maior que 30s, assume que é uma nova interação/requisição
        now = time.time()
        if now - self._last_search_time > 30.0:
            self._session_query_count = 0
        
        self._last_search_time = now

        if self._session_query_count >= self.max_session_queries:
            log.warning(
                f"[search] 🛑 Válvula de segurança acionada! "
                f"Limite de {self.max_session_queries} buscas por sessão atingido "
                f"(prevenção de loops de IA). Pulando busca externa."
            )
            return SearchResponse(query=query)

        # 3. Executa a busca através dos backends configurados com queda preventiva por cota
        for backend in self.backends:
            backend_name = backend.__class__.__name__.lower().replace("backend", "")
            
            # Verifica limites preventivos de cota antes de bater na API
            if self.cost_tracker and hasattr(self.cost_tracker, "quota_manager"):
                if not self.cost_tracker.quota_manager.has_quota(backend_name):
                    log.warning(f"[search] ⚠️ Cota preventiva diária/mensal esgotada para '{backend_name}'. Pulando.")
                    continue

            response = await backend.search(query, max_results)
            if response.results:
                log.info(
                    f"[search] '{query[:40]}' → {len(response.results)} "
                    f"resultados via {response.backend}"
                )
                # Incrementa contador de busca real desta sessão
                self._session_query_count += 1

                # Registra consumo de cota
                if self.cost_tracker and hasattr(self.cost_tracker, "quota_manager"):
                    self.cost_tracker.quota_manager.consume_usage(response.backend)
                
                # Salva no cache
                self.cache.set(query, response.to_dict())
                return response
            log.warning(f"[search] {response.backend} sem resultados, tentando próximo")

        return SearchResponse(query=query)

    async def search_multiple(
        self,
        queries: list[str],
        max_results_per_query: int = 3,
    ) -> list[SearchResponse]:
        return await asyncio.gather(
            *[self.search(q, max_results_per_query) for q in queries]
        )

    async def fetch(self, url: str, max_chars: int = 5000) -> str:
        return await fetch_page_text(url, max_chars)
