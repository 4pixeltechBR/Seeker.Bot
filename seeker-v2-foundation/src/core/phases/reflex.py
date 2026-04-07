"""
Seeker.Bot — Reflex Phase
src/core/phases/reflex.py

Resposta direta: 1 LLM call, sem arbitrage, sem web, sem judge.
Para: saudações, confirmações, perguntas triviais.
"""

import logging

from config.models import ModelRouter, CognitiveRole
from src.core.phases.base import PhaseContext, PhaseResult
from src.core.cognition.prompts import build_reflex_prompt
from src.providers.base import LLMRequest, invoke_with_fallback

log = logging.getLogger("seeker.phases.reflex")


class ReflexPhase:
    """Resposta direta, 1 LLM call, sem pipeline."""

    def __init__(self, router: ModelRouter, api_keys: dict[str, str]):
        self.router = router
        self.api_keys = api_keys

    async def execute(self, ctx: PhaseContext) -> PhaseResult:
        system = build_reflex_prompt(
            memory_context=ctx.memory_prompt,
            session_context=ctx.session_context,
        )

        response = await invoke_with_fallback(
            role=CognitiveRole.FAST,
            request=LLMRequest(
                messages=[{"role": "user", "content": ctx.user_input}],
                system=system,
                max_tokens=500,
                temperature=0.1,
            ),
            router=self.router,
            api_keys=self.api_keys,
        )

        return PhaseResult(
            response=response.text,
            cost_usd=response.cost_usd,
            llm_calls=1,
        )
