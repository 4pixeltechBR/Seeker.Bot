"""
Seeker.Bot — API Cascade Layer
Integração com Seeker.ai API Cascade para cost reduction (40%) + resilience.

Stratégia em tiers:
1. NVIDIA NIM (elite models, free tier)
2. Groq (fast inference, free tier)
3. Gemini Flash (vision, cheap)
4. DeepSeek (reasoner models, ~$1.40/M tokens)
5. Local Ollama (CPU fallback, zero cost)

Uso:
    from src.providers.cascade import CascadeAdapter
    cascade = CascadeAdapter(model_router, api_keys)
    result = await cascade.call(role="planning", messages=[...])
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from config.models import ModelRouter, CognitiveRole
from src.providers.base import LLMRequest, LLMResponse

log = logging.getLogger("seeker.cascade")


class CascadeRole(str, Enum):
    """Roles mapeados para Seeker.Bot tasks."""
    PLAN = "planning"           # Task decomposition
    REASONING = "reasoning"     # Deep thinking (DeepSeek Reasoner)
    CODING = "coding"          # Code generation
    VISION = "vision"          # Image understanding
    CREATIVE = "creative"      # Copywriting, content
    FAST = "fast"              # Quick classifications
    EXTRACTION = "extraction"  # Fact/data extraction


@dataclass
class CascadeState:
    """Tracks cascade execution."""
    role: CascadeRole
    tier: int
    provider: str
    model: str
    elapsed_ms: int
    tokens_estimated: int


class CascadeAdapter:
    """
    Adapta ModelRouter para usar cascade strategy.
    Mantém compatibilidade com código existente.
    """

    def __init__(self, model_router: ModelRouter, api_keys: dict[str, str]):
        self.model_router = model_router
        self.api_keys = api_keys

        # Routing por role (simplificado para Seeker.Bot)
        self.role_routes = {
            CascadeRole.PLAN: [
                CognitiveRole.SYNTHESIS,      # DeepSeek (primo de OpenAI)
                CognitiveRole.SYNTHESIS,      # Fallback to secondary
            ],
            CascadeRole.REASONING: [
                CognitiveRole.SYNTHESIS,      # Deep reasoner
            ],
            CascadeRole.CODING: [
                CognitiveRole.SYNTHESIS,
                CognitiveRole.FAST,
            ],
            CascadeRole.VISION: [
                CognitiveRole.FAST,           # Gemini Flash (vision doesn't need deep reasoning)
            ],
            CascadeRole.CREATIVE: [
                CognitiveRole.FAST,           # Groq (rápido)
                CognitiveRole.SYNTHESIS,      # Fallback
            ],
            CascadeRole.FAST: [
                CognitiveRole.FAST,           # Groq/Llama
            ],
            CascadeRole.EXTRACTION: [
                CognitiveRole.FAST,           # Rápido é suficiente
                CognitiveRole.SYNTHESIS,
            ],
        }

        # Circuit breaker por provider
        self._failures = {}
        self._last_failure_time = {}
        self._failure_threshold = 3
        self._recovery_time = 60.0  # segundos

    def start_health_checks(self) -> None:
        """
        No-op compatibility stub.

        The advanced CascadeAdapter (cascade_advanced.py) runs background
        health checks. The simple adapter doesn't — just a compatibility shim.
        """
        return None

    def stop_health_checks(self) -> None:
        """
        No-op compatibility stub.

        The advanced CascadeAdapter (cascade_advanced.py) runs a background
        health-check task that must be cancelled on shutdown. This simple
        adapter has no such task, but bot.py shutdown unconditionally calls
        this method, so we expose it as a no-op to preserve a unified API.
        """
        return None

    def _is_circuit_open(self, provider: str) -> bool:
        """Verifica se provider está em circuit breaker."""
        if provider not in self._failures:
            return False

        failures = self._failures.get(provider, 0)
        if failures < self._failure_threshold:
            return False

        last_fail = self._last_failure_time.get(provider, 0)
        elapsed = time.time() - last_fail
        return elapsed < self._recovery_time

    def _record_failure(self, provider: str) -> None:
        """Registra falha no provider."""
        self._failures[provider] = self._failures.get(provider, 0) + 1
        self._last_failure_time[provider] = time.time()

        if self._failures[provider] >= self._failure_threshold:
            log.warning(
                f"[cascade] Circuit breaker OPEN para {provider} "
                f"({self._failures[provider]} failures)"
            )

    def _record_success(self, provider: str) -> None:
        """Reset circuit breaker no sucesso."""
        if provider in self._failures and self._failures[provider] > 0:
            log.info(f"[cascade] Circuit breaker RESET para {provider}")
        self._failures[provider] = 0

    async def call(
        self,
        role: CascadeRole | str,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 512,
    ) -> dict:
        """
        Cascading LLM call com fallback.

        Returns:
            {
                "content": str,
                "provider": str,
                "model": str,
                "tier": int,
                "elapsed_ms": int,
            }
        """
        # Handle role conversion: pass through enum members, convert plain strings
        if not isinstance(role, CascadeRole):
            try:
                role = CascadeRole(str(role).lower())
            except ValueError:
                log.warning(f"[cascade] Invalid role '{role}', defaulting to FAST")
                role = CascadeRole.FAST

        t0 = time.perf_counter()
        route = self.role_routes.get(role, [CognitiveRole.SYNTHESIS, CognitiveRole.FAST])

        # Monta request uma vez
        req = LLMRequest(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        tier = 0
        for cognitive_role in route:
            # Tenta primary + fallbacks de cada cognitive_role
            primary = self.model_router.get(cognitive_role)
            fallbacks = self.model_router.get_fallbacks(cognitive_role)
            for model in [primary] + fallbacks:
                provider = model.provider
                tier += 1

                if self._is_circuit_open(provider):
                    log.debug(f"[cascade] Tier {tier}: {provider} em circuit breaker, pulando")
                    continue

                log.info(
                    f"[cascade] Tier {tier}: {provider}/{model.display_name} "
                    f"(role={role.value})"
                )

                try:
                    result = await self._call_provider(model, req)
                except Exception as e:
                    self._record_failure(provider)
                    log.warning(f"[cascade] Tier {tier} exceção: {e}")
                    continue

                if result:
                    self._record_success(provider)
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    log.info(f"[cascade] ✅ Tier {tier} ({provider}) respondeu em {elapsed_ms}ms")
                    return {
                        "content": result.text,
                        "provider": provider,
                        "model": model.display_name,
                        "tier": tier,
                        "elapsed_ms": elapsed_ms,
                    }
                else:
                    self._record_failure(provider)
                    log.debug(f"[cascade] Tier {tier}: {provider} falhou, tentando próximo")

        # Fallback final: sem resposta
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log.error(f"[cascade] Todos os tiers falharam após {elapsed_ms}ms")
        return {
            "content": None,
            "provider": "none",
            "model": "none",
            "tier": 0,
            "elapsed_ms": elapsed_ms,
        }

    async def _call_provider(self, model, req: LLMRequest) -> Optional[LLMResponse]:
        """Chama provider diretamente pelo modelo selecionado."""
        try:
            from src.providers.base import create_provider

            provider_instance = create_provider(model, self.api_keys)
            resp = await asyncio.wait_for(
                provider_instance.complete(req),
                timeout=45.0,
            )
            if not resp:
                return None
            # Alguns modelos (ex: Nemotron) retornam só <think> — extrair conteúdo raw
            if not resp.text and resp.raw:
                raw_content = resp.raw.get("choices", [{}])[0].get("message", {}).get("content", "")
                if raw_content:
                    resp.text = raw_content
            return resp if resp.text else None

        except asyncio.TimeoutError:
            log.warning(f"[cascade] Timeout em {model.provider}")
            return None
        except Exception as e:
            log.warning(f"[cascade] Erro em {model.provider}/{model.display_name}: {e}")
            return None
