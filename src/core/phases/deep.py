"""
Seeker.Bot — Deep Phase
src/core/phases/deep.py

Pipeline completo: Arbitrage → Web Search → Research Loops → Synthesis → Judge.

O que é NOVO aqui vs o pipeline original:
  Research Loops — quando o arbitrage detecta conflitos entre modelos,
  em vez de apenas marcar "⚠️ conflito", gera query específica,
  busca fonte primária na web, e tenta resolver.
  
  "⚠️ conflito detectado" → "🔍 investigado → ✅/❌ resolvido"

Controlado com MAX_RESEARCH_LOOPS = 2 pra não explodir custo.
"""

import asyncio
import logging

from config.models import ModelRouter, CognitiveRole
from src.core.phases.base import PhaseContext, PhaseResult
from src.core.cognition.prompts import build_deep_prompt
from src.core.evidence.arbitrage import EvidenceArbitrage, ArbitrageResult
from src.core.search.web import WebSearcher
from src.core.utils import parse_llm_json
from src.core.healing.judge import VerificationGate
from src.providers.base import LLMRequest, invoke_with_fallback

log = logging.getLogger("seeker.phases.deep")


class DeepPhase:
    """
    Pipeline completo de análise profunda.
    
    4 fases + research loops:
      1. Evidence Arbitrage (modelos divergem onde?)
      2. Web Search (fontes primárias reais)
      2.5. Research Loops (investigar conflitos especificamente)
      3. Síntese profunda (com todo o contexto)
      4. Verification Gate (juiz independente)
    """

    MAX_RESEARCH_LOOPS = 2

    def __init__(
        self,
        router: ModelRouter,
        api_keys: dict[str, str],
        searcher: WebSearcher,
        arbitrage: EvidenceArbitrage,
        gate: VerificationGate,
    ):
        self.router = router
        self.api_keys = api_keys
        self.searcher = searcher
        self.arbitrage = arbitrage
        self.gate = gate

    async def execute(self, ctx: PhaseContext) -> PhaseResult:
        total_cost = 0.0
        llm_calls = 0

        # ── Fase 1+2: Arbitrage ∥ Web Search (PARALELO) ──────
        log.info("[deep] Fase 1+2: Arbitrage + Web em paralelo...")
        arb = None
        evidence = "Arbitragem indisponível."
        web_context = ""

        arb_result, web_result = await asyncio.gather(
            self._safe_arbitrage(ctx.user_input),
            self._safe_web_search(ctx.user_input),
            return_exceptions=False,
        )

        # Processa Arbitrage
        if arb_result is not None:
            arb = arb_result
            total_cost += arb.total_cost_usd
            llm_calls += len(arb.models_consulted)
            evidence = arb.to_summary()

        # Processa Web
        if web_result:
            web_context = web_result

        # ── Fase 2.5: Research Loops (NOVO) ──────────────────
        if arb and arb.has_conflicts:
            log.info(
                f"[deep] Fase 2.5: Research Loops "
                f"({len(arb.conflict_zones)} conflitos)..."
            )
            try:
                web_context = await asyncio.wait_for(
                    self._resolve_conflicts(arb, web_context),
                    timeout=60.0
                )
            except asyncio.TimeoutError:
                log.warning("[deep] Research Loops falhou por timeout (60s)")
            except Exception as e:
                log.warning(f"[deep] Research Loops falhou: {e}")

        # ── Fase 3: Síntese profunda ─────────────────────────
        log.info("[deep] Fase 3: Síntese...")
        module_ctx = ""
        if ctx.decision.forced_module:
            module_ctx = f"\nMódulo: {ctx.decision.forced_module}"

        system = build_deep_prompt(
            evidence_context=evidence,
            web_context=web_context,
            module_context=module_ctx,
            memory_context=ctx.memory_prompt,
            session_context=ctx.session_context,
            god_mode=ctx.decision.god_mode,
        )

        try:
            response = await asyncio.wait_for(
                invoke_with_fallback(
                    role=CognitiveRole.ADVERSARIAL if ctx.decision.god_mode else CognitiveRole.SYNTHESIS,
                    request=LLMRequest(
                        messages=[{"role": "user", "content": ctx.user_input}],
                        system=system,
                        max_tokens=6000,
                        temperature=0.2,
                    ),
                    router=self.router,
                    api_keys=self.api_keys,
                ),
                timeout=60.0
            )
            total_cost += response.cost_usd
            llm_calls += 1
        except asyncio.TimeoutError:
            log.error("[deep] Síntese principal sofreu timeout (60s)", exc_info=True)
            return PhaseResult(
                response="[Seeker] Pipeline abortado por timeout na fase de síntese.",
                cost_usd=total_cost,
                llm_calls=llm_calls,
                arbitrage=arb,
            )
        except Exception as e:
            log.error(f"[deep] Síntese principal falhou fatalmente: {e}", exc_info=True)
            raise

        # ── Fase 4: Verification Gate ────────────────────────
        log.info("[deep] Fase 4: Verification Gate...")
        verdict = None
        all_evidence = evidence
        if web_context:
            all_evidence += f"\n\n{web_context}"

        try:
            verdict = await asyncio.wait_for(
                self.gate.verify(
                    user_input=ctx.user_input,
                    response_text=response.text,
                    evidence_context=all_evidence,
                ),
                timeout=20.0
            )
            llm_calls += 1

            if self.gate.should_warn(verdict):
                warning = verdict.to_warning()
                if warning:
                    response.text = response.text + "\n\n---\n" + warning

        except asyncio.TimeoutError:
            log.warning("[deep] Verification Gate falhou por timeout (20s)")
        except Exception as e:
            log.warning(f"[deep] Verification Gate falhou: {e}")

        return PhaseResult(
            response=response.text,
            cost_usd=total_cost,
            llm_calls=llm_calls,
            arbitrage=arb,
            verdict=verdict,
        )

    async def _safe_arbitrage(self, user_input: str) -> "ArbitrageResult | None":
        """Wrapper com timeout e error handling pro gather."""
        try:
            return await asyncio.wait_for(
                self.arbitrage.arbitrate(user_input), timeout=45.0
            )
        except asyncio.TimeoutError:
            log.warning("[deep] Arbitrage falhou por timeout (45s)")
            return None
        except Exception as e:
            log.warning(f"[deep] Arbitrage falhou: {e}")
            return None

    async def _safe_web_search(self, user_input: str) -> str:
        """Wrapper com timeout e error handling pro gather."""
        try:
            return await asyncio.wait_for(
                self._web_search(user_input), timeout=25.0
            )
        except asyncio.TimeoutError:
            log.warning("[deep] Web search falhou por timeout (25s)")
            return ""
        except Exception as e:
            log.warning(f"[deep] Web search falhou: {e}")
            return ""

    async def _web_search(self, user_input: str) -> str:
        """Gera queries determinísticas e busca na web."""
        from src.core.phases.deliberate import DeliberatePhase
        try:
            # Cria instância de DeliberatePhase pra acessar _generate_search_queries
            deliberate = DeliberatePhase(self.router, self.api_keys, self.searcher)
            search_queries = await deliberate._generate_search_queries(user_input)
            search_results = await self.searcher.search_multiple(
                search_queries, max_results_per_query=3
            )
            parts = [sr.to_context(max_results=3) for sr in search_results if sr.results]
            return "\n\n".join(parts) if parts else ""
        except Exception as e:
            log.warning(f"[deep] Web search falhou: {e}")
            return ""

    async def _resolve_conflicts(
        self,
        arb: ArbitrageResult,
        existing_web: str,
    ) -> str:
        """
        RESEARCH LOOPS — resolve conflitos da arbitragem com fontes primárias.
        
        Quando a arbitragem detecta conflitos entre modelos:
        1. Gera query de busca ESPECÍFICA para o tópico em conflito
        2. Busca na web por fonte primária
        3. Adiciona o resultado ao contexto web
        4. Marca o conflito como "investigado"
        
        Max 2 loops para controlar custo (~$0.002 por loop).
        """
        resolved = 0

        for i, zone in enumerate(arb.conflict_zones):
            if i >= self.MAX_RESEARCH_LOOPS:
                log.info(
                    f"[deep] Research loops: atingiu limite "
                    f"({self.MAX_RESEARCH_LOOPS}), "
                    f"{len(arb.conflict_zones) - i} conflitos restantes"
                )
                break

            # Query específica para o conflito
            query = f"{zone.topic} official documentation 2025 2026"
            log.info(f"[deep] Research loop {i+1}: buscando '{query[:60]}...'")

            try:
                results = await self.searcher.search(query, max_results=3)
                if results.results:
                    context_part = results.to_context(max_results=2)
                    existing_web += (
                        f"\n\n━━━ INVESTIGAÇÃO DE CONFLITO: {zone.topic} ━━━\n"
                        f"{context_part}"
                    )
                    zone.resolution = f"Investigado via web ({len(results.results)} fontes)"
                    zone.needs_primary_source = False
                    resolved += 1
            except Exception as e:
                log.warning(f"[deep] Research loop falhou para '{zone.topic}': {e}")

        if resolved > 0:
            log.info(f"[deep] Research loops: {resolved}/{len(arb.conflict_zones)} conflitos investigados")

        return existing_web

    # _generate_search_queries removido — usa DeliberatePhase._build_search_queries (DRY)
