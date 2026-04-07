"""
Seeker.Bot — Camada de Providers
src/providers/base.py

Interface unificada para todos os provedores de LLM.

Resiliência operacional:
  - AsyncRateLimiter por provider (previne rate limit)
  - Retry com exponential backoff (sobrevive a falhas transitórias)
  - Fallback automático entre providers
  - Strip de thinking tags
  - Connection pooling global (reutiliza conexões TCP)
"""

import asyncio
import logging
import re
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field

import httpx

from config.models import ModelConfig, ModelRouter, CognitiveRole

log = logging.getLogger("seeker.providers")


# ─────────────────────────────────────────────────────────────────────
# TIPOS
# ─────────────────────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    raw: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMRequest:
    messages: list[dict[str, str]]
    max_tokens: int = 4096
    temperature: float = 0.0
    system: str | None = None
    response_format: str | None = None


# ─────────────────────────────────────────────────────────────────────
# RATE LIMITER — token bucket com sliding window
# ─────────────────────────────────────────────────────────────────────

class AsyncRateLimiter:
    """Rate limiter assíncrono por provider. Sliding window."""

    def __init__(self, rpm: int):
        self.rpm = rpm
        self.window = 60.0
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        if self.rpm <= 0:
            return 0.0

        async with self._lock:
            now = time.monotonic()
            while self._timestamps and self._timestamps[0] < now - self.window:
                self._timestamps.popleft()

            if len(self._timestamps) >= self.rpm:
                oldest = self._timestamps[0]
                wait_time = oldest + self.window - now + 0.1
                if wait_time > 0:
                    log.info(
                        f"[rate-limit] Aguardando {wait_time:.1f}s "
                        f"({len(self._timestamps)}/{self.rpm} RPM)"
                    )
                    await asyncio.sleep(wait_time)
                now = time.monotonic()
                while self._timestamps and self._timestamps[0] < now - self.window:
                    self._timestamps.popleft()

            self._timestamps.append(time.monotonic())
            return 0.0

    @property
    def current_usage(self) -> int:
        now = time.monotonic()
        while self._timestamps and self._timestamps[0] < now - self.window:
            self._timestamps.popleft()
        return len(self._timestamps)


# Registry global de rate limiters por provider
_rate_limiters: dict[str, AsyncRateLimiter] = {}


def _get_rate_limiter(config: ModelConfig) -> AsyncRateLimiter:
    key = f"{config.provider}:{config.model_id}"
    if key not in _rate_limiters:
        rpm = config.rpm_limit if config.rpm_limit > 0 else 0
        _rate_limiters[key] = AsyncRateLimiter(rpm=rpm)
        if rpm > 0:
            log.debug(f"[rate-limit] Criado limiter para {key}: {rpm} RPM")
    return _rate_limiters[key]


# ─────────────────────────────────────────────────────────────────────
# CONNECTION POOL GLOBAL — reutiliza conexões TCP entre requests
# ─────────────────────────────────────────────────────────────────────

_client_pool: dict[str, httpx.AsyncClient] = {}


def _get_shared_client(provider: str) -> httpx.AsyncClient:
    """
    Retorna um client compartilhado por provider.
    
    Reutiliza conexões TCP entre requests — com uso constante (20+ req/dia),
    evita abrir e fechar 20+ conexões por dia.
    """
    if provider not in _client_pool or _client_pool[provider].is_closed:
        _client_pool[provider] = httpx.AsyncClient(
            timeout=60.0,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
            ),
        )
    return _client_pool[provider]


async def cleanup_client_pool():
    """Fecha todos os clients. Chamar no shutdown do bot."""
    for provider, client in _client_pool.items():
        if not client.is_closed:
            await client.aclose()
    _client_pool.clear()


# ─────────────────────────────────────────────────────────────────────
# FILTRO DE THINKING TAGS
# ─────────────────────────────────────────────────────────────────────

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_TAG = re.compile(r"</?think>")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def _strip_thinking_tags(text: str) -> str:
    cleaned = _THINK_PATTERN.sub("", text)
    cleaned = _THINK_TAG.sub("", cleaned)
    cleaned = _MULTI_NEWLINE.sub("\n\n", cleaned)
    return cleaned.strip()


# ─────────────────────────────────────────────────────────────────────
# RETRY CONFIG
# ─────────────────────────────────────────────────────────────────────

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0
RETRY_MAX_DELAY = 15.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in RETRYABLE_STATUS_CODES
    if isinstance(error, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError)):
        return True
    if isinstance(error, asyncio.TimeoutError):
        return True
    return False


# ─────────────────────────────────────────────────────────────────────
# PROVIDER BASE
# ─────────────────────────────────────────────────────────────────────

class BaseProvider(ABC):
    """
    Contrato base para providers de LLM.
    
    complete() adiciona:
      1. Rate limiting
      2. Retry com exponential backoff
      3. Strip de thinking tags
      4. Cost tracking
    """

    def __init__(self, config: ModelConfig, api_key: str):
        self.config = config
        self.api_key = api_key
        self._rate_limiter = _get_rate_limiter(config)

    def _get_client(self) -> httpx.AsyncClient:
        """Usa o pool global de clients."""
        return _get_shared_client(self.config.provider)

    async def close(self):
        """No-op — o pool global gerencia lifecycle dos clients."""
        pass

    async def complete(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        await self._rate_limiter.acquire()

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._call(request)
                response.text = _strip_thinking_tags(response.text)
                response.latency_ms = int((time.perf_counter() - start) * 1000)
                response.cost_usd = self._calculate_cost(response)

                log.info(
                    f"[{self.config.provider}] {self.config.model_id} | "
                    f"{response.total_tokens} tok | "
                    f"{response.latency_ms}ms | "
                    f"${response.cost_usd:.4f}"
                    f"{f' (attempt {attempt})' if attempt > 1 else ''}"
                )
                return response

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES and _is_retryable(e):
                    delay = min(
                        RETRY_BASE_DELAY * (2 ** (attempt - 1)),
                        RETRY_MAX_DELAY,
                    )
                    log.warning(
                        f"[{self.config.provider}] Retry {attempt}/{MAX_RETRIES} "
                        f"em {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    break

        elapsed = int((time.perf_counter() - start) * 1000)
        log.error(
            f"[{self.config.provider}] {self.config.model_id} | "
            f"FALHA após {elapsed}ms ({MAX_RETRIES} tentativas): {last_error}"
        )
        raise last_error

    def _calculate_cost(self, response: LLMResponse) -> float:
        input_cost = (response.input_tokens / 1_000_000) * self.config.cost_per_1m_input
        output_cost = (response.output_tokens / 1_000_000) * self.config.cost_per_1m_output
        return input_cost + output_cost

    @abstractmethod
    async def _call(self, request: LLMRequest) -> LLMResponse:
        ...


# ─────────────────────────────────────────────────────────────────────
# PROVIDERS CONCRETOS
# ─────────────────────────────────────────────────────────────────────

class DeepSeekProvider(BaseProvider):
    BASE_URL = "https://api.deepseek.com/v1/chat/completions"

    async def _call(self, request: LLMRequest) -> LLMResponse:
        client = self._get_client()
        messages = list(request.messages)
        if request.system:
            messages.insert(0, {"role": "system", "content": request.system})
        payload: dict = {
            "model": self.config.model_id,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        resp = await client.post(
            self.BASE_URL,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return LLMResponse(
            text=choice["message"]["content"],
            model=data.get("model", self.config.model_id),
            provider="deepseek",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )


class GeminiProvider(BaseProvider):
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    async def _call(self, request: LLMRequest) -> LLMResponse:
        client = self._get_client()
        contents = []
        for msg in request.messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": request.max_tokens,
                "temperature": request.temperature,
            },
        }
        if request.system:
            payload["systemInstruction"] = {"parts": [{"text": request.system}]}
        if request.response_format == "json":
            payload["generationConfig"]["responseMimeType"] = "application/json"
        url = f"{self.BASE_URL}/{self.config.model_id}:generateContent?key={self.api_key}"
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        candidate = data["candidates"][0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        text = parts[0]["text"] if parts else ""
        if not text:
            raise ValueError(f"Gemini retornou resposta sem texto: {list(candidate.keys())}")
        usage = data.get("usageMetadata", {})
        return LLMResponse(
            text=text,
            model=self.config.model_id,
            provider="gemini",
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
            raw=data,
        )


class GroqProvider(BaseProvider):
    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    async def _call(self, request: LLMRequest) -> LLMResponse:
        client = self._get_client()
        messages = list(request.messages)
        if request.system:
            messages.insert(0, {"role": "system", "content": request.system})
        payload: dict = {
            "model": self.config.model_id,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        resp = await client.post(
            self.BASE_URL,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return LLMResponse(
            text=choice["message"]["content"],
            model=data.get("model", self.config.model_id),
            provider="groq",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )


class MistralProvider(BaseProvider):
    BASE_URL = "https://api.mistral.ai/v1/chat/completions"

    async def _call(self, request: LLMRequest) -> LLMResponse:
        client = self._get_client()
        messages = list(request.messages)
        if request.system:
            messages.insert(0, {"role": "system", "content": request.system})
        payload: dict = {
            "model": self.config.model_id,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        resp = await client.post(
            self.BASE_URL,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return LLMResponse(
            text=choice["message"]["content"],
            model=data.get("model", self.config.model_id),
            provider="mistral",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )


class NvidiaProvider(BaseProvider):
    BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

    async def _call(self, request: LLMRequest) -> LLMResponse:
        client = self._get_client()
        messages = list(request.messages)
        if request.system:
            messages.insert(0, {"role": "system", "content": request.system})
        payload: dict = {
            "model": self.config.model_id,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        resp = await client.post(
            self.BASE_URL,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return LLMResponse(
            text=choice["message"]["content"],
            model=data.get("model", self.config.model_id),
            provider="nvidia",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )


# ─────────────────────────────────────────────────────────────────────
# FACTORY + INVOCAÇÃO COM FALLBACK
# ─────────────────────────────────────────────────────────────────────

PROVIDER_MAP = {
    "deepseek": DeepSeekProvider,
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "mistral": MistralProvider,
    "nvidia": NvidiaProvider,
}


def create_provider(config: ModelConfig, api_keys: dict[str, str]) -> BaseProvider:
    cls = PROVIDER_MAP.get(config.provider)
    if not cls:
        raise ValueError(f"Provider desconhecido: {config.provider}")
    key = api_keys.get(config.provider, "")
    if not key:
        raise ValueError(f"API key ausente para provider: {config.provider}")
    return cls(config, key)


async def invoke_with_fallback(
    role: CognitiveRole,
    request: LLMRequest,
    router: ModelRouter,
    api_keys: dict[str, str],
) -> LLMResponse:
    """
    Invoca o modelo primário. Se falhar, tenta fallbacks.
    
    Agora usa connection pool global — close() é no-op,
    connections são reutilizadas entre requests.
    """
    primary = router.get(role)
    fallbacks = router.get_fallbacks(role)
    all_configs = [primary] + fallbacks

    last_error = None
    for config in all_configs:
        try:
            provider = create_provider(config, api_keys)
            return await provider.complete(request)
        except Exception as e:
            last_error = e
            log.warning(f"[fallback] {config.provider}/{config.model_id} falhou: {e}")
            continue

    raise RuntimeError(
        f"Todos os providers falharam para {role.value}. "
        f"Último erro: {last_error}"
    )
