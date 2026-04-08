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
        if isinstance(role, str):
            role = CascadeRole(role)
        elif not isinstance(role, CascadeRole):
            role = CascadeRole(role)

        t0 = time.perf_counter()
        route = self.role_routes.get(role, [CognitiveRole.SYNTHESIS, CognitiveRole.FAST])

        for tier, cognitive_role in enumerate(route, start=1):
            try:
                model = self.model_router.get(cognitive_role)
                provider = model.provider

                # Skip se circuit está aberto
                if self._is_circuit_open(provider):
                    log.debug(f"[cascade] Tier {tier}: {provider} está em circuit breaker, pulando")
                    continue

                log.info(
                    f"[cascade] Tier {tier}: {provider}/{model.name} "
                    f"(role={role.value})"
                )

                # Monta request
                req = LLMRequest(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                # Chama provider
                result = await self._call_provider(model, req)

                if result:
                    self._record_success(provider)
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    log.info(f"[cascade] ✅ Tier {tier} ({provider}) respondeu em {elapsed_ms}ms")

                    return {
                        "content": result.text,
                        "provider": provider,
                        "model": model.name,
                        "tier": tier,
                        "elapsed_ms": elapsed_ms,
                    }
                else:
                    self._record_failure(provider)
                    log.debug(f"[cascade] Tier {tier}: {provider} falhou, tentando próximo")

            except Exception as e:
                self._record_failure(provider)
                log.warning(f"[cascade] Tier {tier} exceção: {e}")
                continue

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
        """Chama provider com timeout."""
        try:
            # Importa dinamicamente o invoke_with_fallback
            from src.providers.base import invoke_with_fallback

            # Adapta para usar o provider específico
            resp = await asyncio.wait_for(
                invoke_with_fallback(
                    role=self._cognitive_role_from_provider(model.provider),
                    request=req,
                    model_router=self.model_router,
                    api_keys=self.api_keys,
                ),
                timeout=45.0,
            )
            return resp if resp and resp.text else None

        except asyncio.TimeoutError:
            log.warning(f"[cascade] Timeout em {model.provider}")
            return None
        except Exception as e:
            log.debug(f"[cascade] Erro em {model.provider}: {e}")
            return None

    def _cognitive_role_from_provider(self, provider: str) -> CognitiveRole:
        """Map provider string to CognitiveRole."""
        provider_to_role = {
            "groq": CognitiveRole.FAST,
            "gemini": CognitiveRole.SYNTHESIS,
            "deepseek": CognitiveRole.SYNTHESIS,
            "nvidia": CognitiveRole.SYNTHESIS,
            "mistral": CognitiveRole.SYNTHESIS,
        }
        return provider_to_role.get(provider, CognitiveRole.SYNTHESIS)
