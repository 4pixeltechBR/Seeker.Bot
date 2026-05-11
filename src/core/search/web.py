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
# WEB SEARCHER — Tavily → Brave
# ─────────────────────────────────────────────────────────────────────


class WebSearcher:
    """
    Tavily (primary) → Brave (fallback).

    Uso:
        searcher = WebSearcher(tavily_key="tvly-...", brave_key="BSA...")
        results = await searcher.search("MCP Anthropic 2026")
    """

    def __init__(self, tavily_key: str = "", brave_key: str = "", cost_tracker=None):
        self.backends: list[SearchBackend] = []
        self.cost_tracker = cost_tracker

        if tavily_key:
            keys = [k.strip() for k in tavily_key.split(",") if k.strip()]
            for k in keys:
                self.backends.append(TavilyBackend(k))
            log.info(f"[search] ✅ Tavily (primary) — {len(keys)} key(s) carregada(s)")

        if brave_key:
            self.backends.append(BraveBackend(brave_key))
            log.info("[search] ✅ Brave (fallback) — índice independente")

        if not self.backends:
            log.warning("[search] ⚠️ Nenhum backend de busca configurado!")

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        for backend in self.backends:
            response = await backend.search(query, max_results)
            if response.results:
                log.info(
                    f"[search] '{query[:40]}' → {len(response.results)} "
                    f"resultados via {response.backend}"
                )
                # Registra consumo de cota (Sprint 11)
                if self.cost_tracker and hasattr(self.cost_tracker, "quota_manager"):
                    self.cost_tracker.quota_manager.consume_usage(response.backend)
                
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
