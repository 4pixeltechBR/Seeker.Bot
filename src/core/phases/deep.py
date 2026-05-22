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
from src.core.cognition.prompts import build_deep_prompt, build_refinement_prompt, get_date_context
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
                    self._resolve_conflicts(arb, web_context), timeout=60.0
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

        refinement_loops = 0
        max_refinement = 2 if ctx.execution_mode == "headless" else 0
        current_response_text = ""
        critique_context = ""

        while refinement_loops <= max_refinement:
            prompt_bundle = build_deep_prompt(
                evidence_context=evidence,
                web_context=web_context,
                module_context=module_ctx + critique_context,
                memory_context=ctx.memory_prompt,
                session_context=ctx.session_context,
                god_mode=ctx.decision.god_mode,
            )

            user_message = get_date_context() + ctx.user_input

            try:
                response = await asyncio.wait_for(
                    invoke_with_fallback(
                        role=CognitiveRole.ADVERSARIAL
                        if ctx.decision.god_mode
                        else CognitiveRole.SYNTHESIS,
                        request=LLMRequest(
                            messages=[{"role": "user", "content": user_message}],
                            system=str(prompt_bundle),  # Backward compat: convert to string
                            max_tokens=6000,
                            temperature=0.2
                            if refinement_loops == 0
                            else 0.4,  # Aumenta temp no refinement
                        ),
                        router=self.router,
                        api_keys=self.api_keys,
                    ),
                    timeout=60.0,
                )
                total_cost += response.cost_usd
                llm_calls += 1
                current_response_text = response.text

                # Se não for headless ou já atingiu o limite, para aqui
                if (
                    ctx.execution_mode != "headless"
                    or refinement_loops >= max_refinement
                ):
                    break

                # ── Loop de Refinamento (Headless Only) ──────
                log.info(
                    f"[deep] Auto-Refinamento: Loop {refinement_loops + 1}/{max_refinement}..."
                )
                critique_prompt = build_refinement_prompt(
                    original_input=ctx.user_input,
                    draft_response=current_response_text,
                    evidence_context=evidence,
                    web_context=web_context,
                )

                critique_resp = await invoke_with_fallback(
                    role=CognitiveRole.JUDGE,
                    request=LLMRequest(
                        messages=[{"role": "user", "content": critique_prompt}],
                        max_tokens=1000,
                        temperature=0.0,
                    ),
                    router=self.router,
                    api_keys=self.api_keys,
                )
                total_cost += critique_resp.cost_usd
                llm_calls += 1

                try:
                    critique_json = parse_llm_json(critique_resp.text)
                    if (
                        critique_json.get("pass") is True
                        and critique_json.get("score", 0) >= 9
                    ):
                        log.info(
                            f"[deep] Refinamento aprovado com nota {critique_json.get('score')}. Saindo do loop."
                        )
                        break

                    log.info(
                        f"[deep] Refinamento necessário (Nota {critique_json.get('score')}: {critique_json.get('action')})"
                    )
                    critique_context = (
                        f"\n\n━━━ CRÍTICA INTERNA (Refinamento {refinement_loops + 1}) ━━━\n"
                        f"Problemas encontrados: {critique_json.get('critique')}\n"
                        f"Ação corretiva: {critique_json.get('action')}\n"
                        f"Favor integrar as melhorias acima na versão final."
                    )
                    refinement_loops += 1
                except Exception as e:
                    log.warning(
                        f"[deep] Falha ao parsear crítica: {e}. Abortando refinamento."
                    )
                    break

            except asyncio.TimeoutError:
                log.error(
                    "[deep] Síntese/Refinamento sofreu timeout (60s)", exc_info=True
                )
                if not current_response_text:
                    return PhaseResult(
                        response="[Seeker] Pipeline abortado por timeout na fase de síntese.",
                        cost_usd=total_cost,
                        llm_calls=llm_calls,
                        arbitrage=arb,
                    )
                break
            except Exception as e:
                log.error(
                    f"[deep] Síntese principal falhou fatalmente: {e}", exc_info=True
                )
                raise

        response_to_verify = current_response_text

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
                    response_text=response_to_verify,
                    evidence_context=all_evidence,
                ),
                timeout=20.0,
            )
            llm_calls += 1

            if self.gate.should_warn(verdict):
                warning = verdict.to_warning()
                if warning:
                    response_to_verify = response_to_verify + "\n\n---\n" + warning

        except asyncio.TimeoutError:
            log.warning("[deep] Verification Gate falhou por timeout (20s)")
        except Exception as e:
            log.warning(f"[deep] Verification Gate falhou: {e}")

        return PhaseResult(
            response=response_to_verify,
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
            return await asyncio.wait_for(self._web_search(user_input), timeout=25.0)
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
            parts = [
                sr.to_context(max_results=3) for sr in search_results if sr.results
            ]
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
        RESEARCH LOOPS PARALELOS — resolve conflitos da arbitragem com fontes primárias.

        Antes: loop sequencial (2 conflitos = 2 buscas em série)
        Agora: asyncio.gather paralelo (2 conflitos = 2 buscas concorrentes)

        Max MAX_RESEARCH_LOOPS zonas investigadas por chamada.
        """
        zones_to_investigate = arb.conflict_zones[: self.MAX_RESEARCH_LOOPS]
        if not zones_to_investigate:
            return existing_web

        # Dispara todos os research loops em paralelo
        tasks = [self._investigate_conflict(zone) for zone in zones_to_investigate]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Monta contexto web com os resultados
        resolved = 0
        for zone, result in zip(zones_to_investigate, results):
            if isinstance(result, Exception):
                log.warning(f"[deep] Research loop falhou para '{zone.topic}': {result}")
                continue
            if result:  # string com contexto encontrado
                existing_web += result
                zone.resolution = "Investigado via web"
                zone.needs_primary_source = False
                resolved += 1

        skipped = len(arb.conflict_zones) - len(zones_to_investigate)
        if resolved > 0:
            log.info(
                f"[deep] Research loops: {resolved}/{len(zones_to_investigate)} conflitos investigados"
                + (f" ({skipped} ignorados por limite)" if skipped else "")
            )

        return existing_web

    async def _investigate_conflict(self, zone) -> str:
        """
        Investiga UM conflito via web search.

        Retorna string de contexto a ser adicionada ao web_context,
        ou string vazia se a busca falhou ou não encontrou resultados.
        """
        query = f"{zone.topic} official documentation 2025 2026"
        log.info(f"[deep] Investigando conflito: '{query[:60]}...'")
        try:
            results = await asyncio.wait_for(
                self.searcher.search(query, max_results=3), timeout=15.0
            )
            if results.results:
                context_part = results.to_context(max_results=2)
                return (
                    f"\n\n━━━ INVESTIGAÇÃO DE CONFLITO: {zone.topic} ━━━\n"
                    f"{context_part}"
                )
        except asyncio.TimeoutError:
            log.warning(f"[deep] Research loop timeout para '{zone.topic}'")
        except Exception as e:
            log.warning(f"[deep] Research loop falhou para '{zone.topic}': {e}")
        return ""

    # _generate_search_queries removido — usa DeliberatePhase._build_search_queries (DRY)
