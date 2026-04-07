"""
Seeker.Bot — Deliberate Phase
src/core/phases/deliberate.py

Síntese com memória: 1-2 LLM calls, web search opcional.
Para: perguntas técnicas, explicações, tarefas que precisam de contexto.
"""

import json
import logging

from config.models import ModelRouter, CognitiveRole
from src.core.phases.base import PhaseContext, PhaseResult
from src.core.cognition.prompts import build_deliberate_prompt
from src.core.search.web import WebSearcher
from src.providers.base import LLMRequest, invoke_with_fallback

log = logging.getLogger("seeker.phases.deliberate")


class DeliberatePhase:
    """Síntese com memória, 1-2 LLM calls, web opcional."""

    def __init__(
        self,
        router: ModelRouter,
        api_keys: dict[str, str],
        searcher: WebSearcher,
    ):
        self.router = router
        self.api_keys = api_keys
        self.searcher = searcher

    async def execute(self, ctx: PhaseContext) -> PhaseResult:
        total_cost = 0.0
        llm_calls = 0

        module_ctx = ""
        if ctx.decision.forced_module:
            module_ctx = f"\nMódulo cognitivo: {ctx.decision.forced_module}"

        # ── Web Search se necessário (factual queries) ────────
        web_section = ""
        if ctx.decision.needs_web:
            log.info("[deliberate] Web search ativado (query factual)")
            try:
                search_queries = await self._generate_search_queries(ctx.user_input)
                search_results = await self.searcher.search_multiple(
                    search_queries, max_results_per_query=3
                )
                web_parts = [sr.to_context(max_results=3) for sr in search_results if sr.results]
                if web_parts:
                    web_section = "\n\n━━━ DADOS DA WEB ━━━\n" + "\n\n".join(web_parts)
                llm_calls += 1  # query generation
            except Exception as e:
                log.warning(f"[deliberate] Web search falhou: {e}")

        system = build_deliberate_prompt(
            module_context=module_ctx,
            memory_context=ctx.memory_prompt,
            session_context=ctx.session_context,
            web_context=web_section,
        )

        response = await invoke_with_fallback(
            role=CognitiveRole.SYNTHESIS,
            request=LLMRequest(
                messages=[{"role": "user", "content": ctx.user_input}],
                system=system,
                max_tokens=4000,
                temperature=0.15,
            ),
            router=self.router,
            api_keys=self.api_keys,
        )
        total_cost += response.cost_usd
        llm_calls += 1

        return PhaseResult(
            response=response.text,
            cost_usd=total_cost,
            llm_calls=llm_calls,
        )

    async def _generate_search_queries(self, user_input: str) -> list[str]:
        """Gera 2-3 queries de busca otimizadas (em inglês) via modelo FAST."""
        try:
            response = await invoke_with_fallback(
                role=CognitiveRole.FAST,
                request=LLMRequest(
                    messages=[{
                        "role": "user",
                        "content": (
                            f"Gere 2-3 queries de busca web curtas e específicas (em inglês, "
                            f"pra melhores resultados) para investigar esta pergunta:\n\n"
                            f"{user_input}\n\n"
                            f'Retorne APENAS JSON: {{"queries": ["query1", "query2"]}}'
                        ),
                    }],
                    max_tokens=200,
                    temperature=0.0,
                    response_format="json",
                ),
                router=self.router,
                api_keys=self.api_keys,
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            data = json.loads(text.strip())
            queries = data.get("queries", [])
            if queries and isinstance(queries, list):
                return [q for q in queries if isinstance(q, str) and len(q) > 3][:3]
        except Exception as e:
            log.warning(f"[deliberate] Falha ao gerar queries: {e}")

        return [user_input[:100]]
