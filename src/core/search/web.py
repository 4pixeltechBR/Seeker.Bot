"""
Seeker.Bot — Web Search
src/core/search/web.py

Três backends por prioridade com queda preventiva:
  1. Gemini Grounding — busca nativa gratuita via Google AI Studio com Key Rotation Pool
  2. Tavily — AI-native, JSON otimizado pra LLMs (fallback 1)
  3. Brave — índice independente (fallback 2)

NOTA: Google Custom Search removido da chain. O recurso 'Pesquisar em toda a Web'
  foi descontinuado pelo Google em jun/2026, tornando o CSE inutilizável para buscas
  globais sem uma lista manual de sites. Backends ativos: Gemini → Tavily → Brave.
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
# TAVILY — FALLBACK: AI-native search
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

    def __init__(self, api_key: str, breaker=None):
        self.api_key = api_key
        self.breaker = breaker
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
            log.debug(f"[tavily] Circuit breaker local ABERTO ({remaining}s restantes). Pulando.")
            return SearchResponse(query=query, backend="tavily")

        if self.breaker and await self.breaker.is_blocked("tavily"):
            log.debug("[tavily] Shared rate limit breaker ativo. Pulando.")
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
            if resp.status_code in (429, 432):
                if self.breaker:
                    await self.breaker.record_failure("tavily", resp.status_code)
                # F-02: incrementa contador de falhas 432 consecutivas
                self._consecutive_432 += 1
                log.error(
                    f"[tavily] Erro {resp.status_code} ({self._consecutive_432}/{self.CIRCUIT_BREAKER_THRESHOLD}). "
                    f"Tentando reset de cliente..."
                )
                # Abre circuit breaker se passou do threshold
                if self._consecutive_432 >= self.CIRCUIT_BREAKER_THRESHOLD:
                    self._circuit_open_until = now + self.CIRCUIT_BREAKER_COOLDOWN
                    log.warning(
                        f"[tavily] CIRCUIT BREAKER ABERTO por {self.CIRCUIT_BREAKER_COOLDOWN}s "
                        f"(apos {self._consecutive_432}x HTTP {resp.status_code}). "
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
                if self.breaker:
                    await self.breaker.record_success("tavily")
                # F-02: qualquer resposta nao-432/429 reseta o contador (recovery)
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
            if self.breaker:
                await self.breaker.record_failure("tavily", 500)
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

    def __init__(self, api_key: str, breaker=None):
        self.api_key = api_key
        self.breaker = breaker

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        if self.breaker and await self.breaker.is_blocked("brave"):
            log.debug("[brave] Shared rate limit breaker ativo. Pulando.")
            return SearchResponse(query=query, backend="brave")

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
                if resp.status_code == 429:
                    if self.breaker:
                        await self.breaker.record_failure("brave", 429)
                    # Retorna sem levantar: evita contagem dupla de falha no except
                    return SearchResponse(query=query, backend="brave")
                resp.raise_for_status()

                if self.breaker:
                    await self.breaker.record_success("brave")

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
            if self.breaker:
                await self.breaker.record_failure("brave", 500)
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
# GOOGLE — CUSTOM SEARCH FALLBACK
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
# GEMINI GROUNDING — PRIMARY COGNITIVE SEARCH TOOL
# ─────────────────────────────────────────────────────────────────────


class GeminiGroundingBackend(SearchBackend):
    """
    Backend de busca web que utiliza o Gemini Search Grounding nativo.
    Dessa forma, economizamos absurdamente as cotas pagas/restritas de Tavily/Brave.

    Circuit breaker embutido: apos CIRCUIT_BREAKER_THRESHOLD falhas 429 consecutivas,
    o circuito abre por CIRCUIT_BREAKER_COOLDOWN segundos — evitando hammering em
    endpoint sabidamente saturado (ex: event_radar com 25 queries por ciclo vs 5 RPM).
    """

    # Semáforo global compartilhado para limitar a concorrência assíncrona de múltiplas skills paralelas
    _semaphore = asyncio.Semaphore(1)

    CIRCUIT_BREAKER_THRESHOLD = 3    # Falhas 429 consecutivas antes de abrir
    CIRCUIT_BREAKER_COOLDOWN  = 300  # 5 minutos — tempo de recuperação do rate limit

    def __init__(self, api_keys: str):
        # Suporta pool de chaves para resiliência máxima
        self.api_keys = [k.strip() for k in api_keys.split(",") if k.strip()]
        self.current_idx = 0
        # Circuit breaker state
        self._consecutive_429 = 0
        self._circuit_open_until = 0.0  # monotonic timestamp

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        import re
        if not self.api_keys:
            return SearchResponse(query=query, backend="gemini_grounding")

        # Circuit breaker check — pula imediatamente se estamos em cooldown
        now = time.monotonic()
        if now < self._circuit_open_until:
            remaining = int(self._circuit_open_until - now)
            log.debug(
                f"[gemini_grounding] Circuit breaker ABERTO ({remaining}s restantes). "
                f"Pulando direto para Tavily."
            )
            return SearchResponse(query=query, backend="gemini_grounding")

        # Entra na fila do semáforo global para evitar estouros de concorrência concorrentes
        async with self._semaphore:
            # Espaçamento mínimo obrigatório de 5.0s para blindar contra o limite de 15 RPM do Gemini 3.1 Flash Lite
            await asyncio.sleep(5.0)

            active_key = self.api_keys[self.current_idx]
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

            payload = {
                "contents": [{"role": "user", "parts": [{"text": f"Busque e liste informações detalhadas e atualizadas sobre a query a seguir. Retorne os links das fontes encontradas. Query: {query}"}]}],
                "tools": [{"google_search": {}}],
                "generationConfig": {
                    "temperature": 0.0,
                    "maxOutputTokens": 1024
                }
            }

            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(
                        url,
                        headers={"x-goog-api-key": active_key},
                        json=payload
                    )

                    if resp.status_code == 429:
                        self._consecutive_429 += 1
                        log.warning(
                            f"[gemini_grounding] 429 #{self._consecutive_429}/{self.CIRCUIT_BREAKER_THRESHOLD} "
                            f"(chave idx={self.current_idx})"
                        )
                        # Tenta rotacionar a chave se tiver pool
                        if len(self.api_keys) > 1:
                            self.current_idx = (self.current_idx + 1) % len(self.api_keys)
                            active_key = self.api_keys[self.current_idx]
                            await asyncio.sleep(1.0)
                            resp = await client.post(
                                url,
                                headers={"x-goog-api-key": active_key},
                                json=payload
                            )
                        # Abre circuit breaker se ultrapassou o threshold
                        if self._consecutive_429 >= self.CIRCUIT_BREAKER_THRESHOLD:
                            self._circuit_open_until = time.monotonic() + self.CIRCUIT_BREAKER_COOLDOWN
                            log.warning(
                                f"[gemini_grounding] CIRCUIT BREAKER ABERTO por {self.CIRCUIT_BREAKER_COOLDOWN}s "
                                f"(após {self._consecutive_429}x 429). Tavily assumirá o próximo ciclo."
                            )
                    else:
                        # Qualquer resposta não-429 reseta o contador
                        if self._consecutive_429 > 0:
                            log.info("[gemini_grounding] Recovery — circuit breaker RESET")
                        self._consecutive_429 = 0

                    resp.raise_for_status()
                    data = resp.json()

                    results = []
                    # Extrai do groundingMetadata retornado
                    candidate = data.get("candidates", [{}])[0]
                    metadata = candidate.get("groundingMetadata", {})
                    chunks = metadata.get("groundingChunks", [])

                    for idx, chunk in enumerate(chunks):
                        web = chunk.get("web", {})
                        uri = web.get("uri", "")
                        title = web.get("title", uri)
                        if uri:
                            results.append(
                                SearchResult(
                                    title=title,
                                    url=uri,
                                    snippet="Resultado extraído via Google Search Grounding.",
                                    source="gemini_grounding",
                                    position=len(results) + 1
                                )
                            )
                            if len(results) >= max_results:
                                break

                    # Fallback: Se não veio chunks no metadata, tenta ler do próprio texto da resposta
                    if not results:
                        text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
                        links = re.findall(r'(https?://[^\s)\]]+)', text)
                        for idx, link in enumerate(list(set(links))[:max_results]):
                            results.append(
                                SearchResult(
                                    title=f"Link de referência {idx + 1}",
                                    url=link,
                                    snippet=text[:300] + "...",
                                    source="gemini_grounding",
                                    position=idx + 1
                                )
                            )

                    return SearchResponse(query=query, results=results, backend="gemini_grounding")
            except Exception as e:
                log.warning(f"[gemini_grounding] Busca falhou ou cota esgotada: {e}")
                self._consecutive_429 += 1
                # Abre circuit breaker se a exceção também for por saturação
                if self._consecutive_429 >= self.CIRCUIT_BREAKER_THRESHOLD:
                    self._circuit_open_until = time.monotonic() + self.CIRCUIT_BREAKER_COOLDOWN
                    log.warning(
                        f"[gemini_grounding] CIRCUIT BREAKER ABERTO por {self.CIRCUIT_BREAKER_COOLDOWN}s "
                        f"(após {self._consecutive_429}x falhas). Tavily assumirá o próximo ciclo."
                    )
                # Rotaciona sob falha de rede/cota para a próxima query
                if len(self.api_keys) > 1:
                    self.current_idx = (self.current_idx + 1) % len(self.api_keys)
                return SearchResponse(query=query, backend="gemini_grounding")


# ─────────────────────────────────────────────────────────────────────
# DUCKDUCKGO — FALLBACK ABSOLUTO: Busca orgânica gratuita sem chave
# ─────────────────────────────────────────────────────────────────────


class DuckDuckGoBackend(SearchBackend):
    """
    DuckDuckGo Search Backend — Fallback gratuito sem API Key.
    Utiliza a biblioteca duckduckgo_search oficial para evitar bloqueios anti-bot.
    """
    def __init__(self, breaker=None):
        self.breaker = breaker

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        import asyncio
        from ddgs import DDGS

        if self.breaker and await self.breaker.is_blocked("duckduckgo"):
            log.debug("[duckduckgo] Shared rate limit breaker ativo. Pulando.")
            return SearchResponse(query=query, backend="duckduckgo")

        def _sync_search():
            # Tentativa única: o WebSearcher já roda os backends em paralelo com
            # timeout próprio, então retries longos aqui só adicionam latência.
            try:
                return list(DDGS().text(query, max_results=max_results))
            except Exception as e:
                log.debug(f"[duckduckgo] Erro: {e}")
            return []

        try:
            raw_results = await asyncio.to_thread(_sync_search)
            results = []
            for i, r in enumerate(raw_results):
                results.append(
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", ""),
                        snippet=r.get("body", ""),
                        source="duckduckgo",
                        position=i + 1
                    )
                )

            if self.breaker:
                await self.breaker.record_success("duckduckgo")

            return SearchResponse(query=query, results=results, backend="duckduckgo")
        except Exception as e:
            log.warning(f"[duckduckgo] Busca falhou: {e}")
            if self.breaker:
                await self.breaker.record_failure("duckduckgo", 500)
            return SearchResponse(query=query, backend="duckduckgo")


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

    @staticmethod
    def _make_key(query: str, max_results: int) -> str:
        # max_results faz parte da chave: buscas com nº de resultados diferentes não colidem
        return f"{query.strip().lower()}::n{max_results}"

    def get(self, query: str, max_results: int = 5, ttl_seconds: float = 86400) -> dict | None:
        """Busca no cache e invalida se estourar o TTL (24h)"""
        key = self._make_key(query, max_results)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT response, timestamp FROM cache WHERE query = ?", (key,))
                row = cursor.fetchone()
                if row:
                    response_str, timestamp = row
                    if time.time() - timestamp < ttl_seconds:
                        log.debug(f"[search-cache] Hit de cache para query: {query}")
                        return json.loads(response_str)
                    else:
                        # Limpa registro expirado
                        log.debug(f"[search-cache] TTL Expirado para: {query}. Deletando.")
                        conn.execute("DELETE FROM cache WHERE query = ?", (key,))
                        conn.commit()
        except Exception as e:
            log.error(f"[search-cache] Falha ao buscar no cache: {e}")
        return None

    def set(self, query: str, response_data: dict, max_results: int = 5):
        """Salva a resposta da query no banco de dados"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache (query, response, timestamp) VALUES (?, ?, ?)",
                    (self._make_key(query, max_results), json.dumps(response_data), time.time())
                )
                conn.commit()
        except Exception as e:
            log.error(f"[search-cache] Falha ao salvar no cache: {e}")


# ─────────────────────────────────────────────────────────────────────
# WEB SEARCHER — Gemini Grounding → Google → Tavily → Brave
# ─────────────────────────────────────────────────────────────────────


class WebSearcher:
    """
    Gemini Grounding (primary) → DuckDuckGo (fallback 1) → Tavily (fallback 2) → Brave (fallback 3).
    Google Custom Search removido: recurso 'Pesquisar em toda a Web' descontinuado pelo Google.

    Uso:
        searcher = WebSearcher(google_key="...", google_cx="...", tavily_key="tvly-...", brave_key="BSA...", gemini_key="...")
        results = await searcher.search("MCP Anthropic 2026")
    """

    def __init__(self, tavily_key: str = "", brave_key: str = "", cost_tracker=None, google_key: str = "", google_cx: str = "", gemini_key: str = ""):
        self.backends: list[SearchBackend] = []
        self.cost_tracker = cost_tracker
        self.cache = SearchCache()

        # Instancia o SharedRateLimitBreaker
        from src.core.rate_limiting.shared_breaker import SharedRateLimitBreaker
        self.breaker = SharedRateLimitBreaker()

        # Válvula de segurança anti-loop
        self._session_query_count = 0
        self._last_search_time = 0.0
        self.max_session_queries = int(os.getenv("MAX_SEARCHES_PER_SESSION", "4"))
        # Atraso entre queries no batch (rate-shaping). Configurável via env.
        self._batch_delay = float(os.getenv("SEARCH_BATCH_DELAY", "5.0"))

        # Adiciona Gemini Grounding como PRIORITÁRIO absoluto se a chave estiver configurada
        if gemini_key:
            self.backends.append(GeminiGroundingBackend(gemini_key))
            log.info("[search] ✅ Gemini Grounding (primary) — ativado com pool rotativo de chaves")

        # DuckDuckGo como Fallback de segurança prioritário e gratuito (sem API Key)
        self.backends.append(DuckDuckGoBackend(self.breaker))
        log.info("[search] ✅ DuckDuckGo (fallback prioritário) — ativado (sem API Key)")

        # Google Custom Search DESATIVADO: Google descontinuou 'Pesquisar em toda a Web' no CSE.
        # O backend só pesquisaria sites específicos cadastrados — inútil para o Seeker.
        # Ref: https://support.google.com/programmable-search (jun/2026)
        # Mantemos as variáveis no .env para reeativação futura caso o Google reverta.
        if os.getenv("GOOGLE_SEARCH_API_KEY") or google_key:
            _key = google_key or os.getenv("GOOGLE_SEARCH_API_KEY")
            _cx = google_cx or os.getenv("GOOGLE_SEARCH_CX")
            if _key and _cx:
                self.backends.append(GoogleBackend(_key, _cx))
                log.info("[search] ✅ Google Custom Search — ativado")
            else:
                log.debug("[search] ⚠️ Google Custom Search ignorado: falta API_KEY ou CX")

        if tavily_key:
            keys = [k.strip() for k in tavily_key.split(",") if k.strip()]
            for k in keys:
                self.backends.append(TavilyBackend(k, self.breaker))
            log.info(f"[search] ✅ Tavily (fallback) — {len(keys)} key(s) carregada(s)")

        if brave_key:
            self.backends.append(BraveBackend(brave_key, self.breaker))
            log.info("[search] ✅ Brave (fallback) — índice independente")

        if not self.backends:
            log.warning("[search] ⚠️ Nenhum backend de busca configurado!")

    async def search(self, query: str, max_results: int = 5, bypass_limit: bool = False) -> SearchResponse:
        # 1. Tenta recuperar do cache local primeiro (24h TTL) — fora do event loop
        cached_data = await asyncio.to_thread(self.cache.get, query, max_results)
        if cached_data:
            log.info(f"[search] Cache HIT para query: '{query[:40]}'")
            return SearchResponse.from_dict(cached_data)

        # 2. Válvula de segurança anti-loop
        now = time.time()
        if now - self._last_search_time > 30.0:
            self._session_query_count = 0
        
        self._last_search_time = now

        if not bypass_limit and self._session_query_count >= self.max_session_queries:
            log.warning(
                f"[search] 🛑 Válvula de segurança acionada! "
                f"Limite de {self.max_session_queries} buscas por sessão atingido "
                f"(prevenção de loops de IA). Pulando busca externa."
            )
            return SearchResponse(query=query)

        # 3. Executa a busca em PARALELO em todos os backends elegíveis e usa o
        #    primeiro resultado não-vazio que chegar (race). Reduz latência de
        #    ~N×timeout (sequencial) para ~1×timeout do backend mais rápido.
        eligible = []
        for backend in self.backends:
            backend_name = backend.__class__.__name__.lower().replace("backend", "")
            # Verifica limites preventivos de cota antes de bater na API
            if self.cost_tracker and hasattr(self.cost_tracker, "quota_manager"):
                if not self.cost_tracker.quota_manager.has_quota(backend_name):
                    log.warning(f"[search] ⚠️ Cota preventiva diária/mensal esgotada para '{backend_name}'. Pulando.")
                    continue
            eligible.append(backend)

        if not eligible:
            return SearchResponse(query=query)

        per_backend_timeout = float(os.getenv("SEARCH_BACKEND_TIMEOUT", "8.0"))

        async def _run(b: SearchBackend) -> SearchResponse:
            try:
                return await asyncio.wait_for(b.search(query, max_results), timeout=per_backend_timeout)
            except asyncio.TimeoutError:
                log.debug(f"[search] {b.__class__.__name__} timeout ({per_backend_timeout}s)")
            except Exception as e:
                log.debug(f"[search] {b.__class__.__name__} erro: {e}")
            return SearchResponse(query=query, backend=b.__class__.__name__.lower().replace("backend", ""))

        tasks = [asyncio.create_task(_run(b)) for b in eligible]
        winner: SearchResponse | None = None
        try:
            for coro in asyncio.as_completed(tasks):
                response = await coro
                if response.results:
                    winner = response
                    break
                log.debug(f"[search] {response.backend} sem resultados")
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()

        if winner and winner.results:
            log.info(
                f"[search] '{query[:40]}' → {len(winner.results)} "
                f"resultados via {winner.backend}"
            )
            self._session_query_count += 1

            # Registra consumo de cota
            if self.cost_tracker and hasattr(self.cost_tracker, "quota_manager"):
                self.cost_tracker.quota_manager.consume_usage(winner.backend)

            # Salva no cache (fora do event loop)
            await asyncio.to_thread(self.cache.set, query, winner.to_dict(), max_results)
            return winner

        log.warning(f"[search] Nenhum backend retornou resultados para '{query[:40]}'")
        return SearchResponse(query=query)

    async def search_multiple(
        self,
        queries: list[str],
        max_results_per_query: int = 3,
        bypass_limit: bool = False,
    ) -> list[SearchResponse]:
        results = []
        for i, q in enumerate(queries):
            res = await self.search(q, max_results_per_query, bypass_limit=bypass_limit)
            results.append(res)
            # Atraso de suavização configurável entre queries consecutivas (anti rate-limit)
            if i < len(queries) - 1:
                await asyncio.sleep(self._batch_delay)
        return results

    async def fetch(self, url: str, max_chars: int = 5000) -> str:
        return await fetch_page_text(url, max_chars)
