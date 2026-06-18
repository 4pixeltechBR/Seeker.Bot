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

    PLAN = "planning"  # Task decomposition
    REASONING = "reasoning"  # Deep thinking (DeepSeek Reasoner)
    CODING = "coding"  # Code generation
    VISION = "vision"  # Image understanding
    CREATIVE = "creative"  # Copywriting, content
    FAST = "fast"  # Quick classifications
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
                CognitiveRole.DEEP,       # Raciocínio profundo para planejamento
                CognitiveRole.SYNTHESIS,  # Fallback para consolidação
            ],
            CascadeRole.REASONING: [
                CognitiveRole.DEEP,       # Deep reasoning (DeepSeek R1 / V4)
                CognitiveRole.ADVERSARIAL,# Red team e verificação lógica
            ],
            CascadeRole.CODING: [
                CognitiveRole.DEEP,       # Lógica pesada e código
                CognitiveRole.FAST,       # Respostas rápidas
            ],
            CascadeRole.VISION: [
                CognitiveRole.FAST,       # Gemini Flash e modelos de visão rápidos
                CognitiveRole.JUDGE,      # NVIDIA Gemma 4 31B
            ],
            CascadeRole.CREATIVE: [
                CognitiveRole.FAST,       # Groq / Modelos leves e rápidos
                CognitiveRole.SYNTHESIS,  # Consolidação e relatórios
            ],
            CascadeRole.FAST: [
                CognitiveRole.FAST,       # Llama 4 Scout / Qwen 3
            ],
            CascadeRole.EXTRACTION: [
                CognitiveRole.FAST,       # Extração rápida
                CognitiveRole.SYNTHESIS,  # Fallback
            ],
        }

        # Circuit breaker por provider
        self._failures = {}
        self._last_failure_time = {}
        self._failure_threshold = 3
        self._recovery_time = 300.0  # 5 min de penalidade antes de tentar novamente

    async def start_health_checks(self, **kwargs) -> None:
        """
        No-op compatibility stub.

        The advanced CascadeAdapter (cascade_advanced.py) runs background
        health checks. The simple adapter doesn't — just a compatibility shim.
        """
        pass

    def stop_health_checks(self, **kwargs) -> None:
        """
        No-op compatibility stub.

        The advanced CascadeAdapter (cascade_advanced.py) runs a background
        health-check task that must be cancelled on shutdown. This simple
        adapter has no such task, but bot.py shutdown unconditionally calls
        this method, so we expose it as a no-op to preserve a unified API.
        """
        pass

    def get_health_status(self) -> dict:
        """Compatibility stub para /cascade_status funcionar sem crashar."""
        from datetime import datetime

        return {
            "timestamp": datetime.now().isoformat(),
            "overall_health": "100% (Simulado)",
            "tiers": {
                "Simples": {
                    "is_healthy": True,
                    "success_rate": "N/A",
                    "avg_latency_ms": 0,
                    "avg_cost_usd": 0.0,
                    "fallback_count": 0,
                    "last_error": "",
                }
            },
        }

    def get_cost_analysis(self) -> dict:
        """Compatibility stub para /cascade_status funcionar sem crashar."""
        return {
            "total_calls": 0,
            "total_cost_usd": 0.0,
            "average_cost_per_call": 0.0,
            "estimated_savings_vs_nim": "$0.00",
            "error_breakdown": {},
        }

    def _breaker_key(self, provider: str, model_name: str = "") -> str:
        """
        T-03 fix: circuit breaker key combines provider + model.

        Previously the breaker keyed on provider name alone, so 3 timeouts
        from nvidia/nemotron-ultra (a notoriously slow ~30s model) would
        blacklist ALL nvidia models — including nvidia/deepseek-v3.2 and
        nvidia/gemma-4-31b which respond much faster. This dropped the
        NVIDIA NIM hit-rate to ~0.1%. Per-model keys isolate the failure.
        """
        return f"{provider}:{model_name}" if model_name else provider

    def _is_circuit_open(self, provider: str, model_name: str = "") -> bool:
        """Verifica se provider/modelo está em circuit breaker."""
        key = self._breaker_key(provider, model_name)
        if key not in self._failures:
            return False

        failures = self._failures.get(key, 0)
        if failures < self._failure_threshold:
            return False

        last_fail = self._last_failure_time.get(key, 0)
        elapsed = time.time() - last_fail
        return elapsed < self._recovery_time

    def _record_failure(self, provider: str, model_name: str = "") -> None:
        """Registra falha no provider/modelo específico."""
        key = self._breaker_key(provider, model_name)
        self._failures[key] = self._failures.get(key, 0) + 1
        self._last_failure_time[key] = time.time()

        if self._failures[key] >= self._failure_threshold:
            log.warning(
                f"[cascade] Circuit breaker OPEN para {key} "
                f"({self._failures[key]} failures)"
            )

    def _record_success(self, provider: str, model_name: str = "") -> None:
        """Reset circuit breaker no sucesso."""
        key = self._breaker_key(provider, model_name)
        if key in self._failures and self._failures[key] > 0:
            log.info(f"[cascade] Circuit breaker RESET para {key}")
        self._failures[key] = 0

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
        route = self.role_routes.get(
            role, [CognitiveRole.SYNTHESIS, CognitiveRole.FAST]
        )

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

                if self._is_circuit_open(provider, model.display_name):
                    log.debug(
                        f"[cascade] Tier {tier}: {provider}/{model.display_name} "
                        f"em circuit breaker, pulando"
                    )
                    continue

                log.info(
                    f"[cascade] Tier {tier}: {provider}/{model.display_name} "
                    f"(role={role.value})"
                )

                try:
                    result = await self._call_provider(model, req)
                except Exception as e:
                    self._record_failure(provider, model.display_name)
                    log.warning(f"[cascade] Tier {tier} exceção: {e}")
                    continue

                if result:
                    self._record_success(provider, model.display_name)
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    log.info(
                        f"[cascade] ✅ Tier {tier} ({provider}/{model.display_name}) "
                        f"respondeu em {elapsed_ms}ms"
                    )
                    return {
                        "content": result.text,
                        "provider": provider,
                        "model": model.display_name,
                        "tier": tier,
                        "elapsed_ms": elapsed_ms,
                    }
                else:
                    self._record_failure(provider, model.display_name)
                    log.debug(
                        f"[cascade] Tier {tier}: {provider}/{model.display_name} "
                        f"falhou, tentando próximo"
                    )

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
                raw_content = (
                    resp.raw.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                if raw_content:
                    resp.text = raw_content
            return resp if resp.text else None

        except asyncio.TimeoutError:
            log.warning(f"[cascade] Timeout em {model.provider}")
            return None
        except Exception as e:
            log.warning(f"[cascade] Erro em {model.provider}/{model.display_name}: {e}")
            return None
