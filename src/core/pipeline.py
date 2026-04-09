"""
Seeker.Bot — Core Pipeline
src/core/pipeline.py

Orquestrador fino: recebe input → decide profundidade → delega pra fase → registra.
Não tem lógica de LLM direta — delega tudo pras phases.

De 554 linhas → ~220 linhas.
Os prompts vivem em cognition/prompts.py.
As fases vivem em phases/{reflex,deliberate,deep}.py.
A sessão vive em memory/session.py.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass

from config.models import ModelRouter, CognitiveRole, build_default_router
from src.core.router.cognitive_load import (
    CognitiveLoadRouter, CognitiveDepth, RoutingDecision,
)
from src.core.evidence.arbitrage import EvidenceArbitrage, ArbitrageResult
from src.core.evidence.decay import DecayEngine
from src.core.search.web import WebSearcher
from src.core.healing.judge import VerificationGate, JudgeVerdict
from src.core.memory.store import MemoryStore
from src.core.memory.extractor import FactExtractor
from src.core.memory.embeddings import GeminiEmbedder, SemanticSearch
from src.core.memory.session import SessionManager
from src.core.memory.compressor import SessionCompressor
from src.core.intent_card import IntentClassifier, IntentCard
from src.core.phases.base import PhaseContext, PhaseResult
from src.core.phases.reflex import ReflexPhase
from src.core.phases.deliberate import DeliberatePhase
from src.core.phases.deep import DeepPhase
from src.providers.base import LLMRequest, invoke_with_fallback
from src.providers.cascade import CascadeAdapter
from src.core.memory.hierarchy import prioritize_facts, format_hierarchical_context
from src.core.profiling.profiler import SystemProfiler
from src.core.profiling.exporter import PrometheusExporter
from src.core.error_recovery import ErrorRecoveryManager

log = logging.getLogger("seeker.pipeline")


@dataclass
class PipelineResult:
    response: str
    depth: CognitiveDepth
    routing_reason: str
    arbitrage: ArbitrageResult | None = None
    verdict: JudgeVerdict | None = None
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0
    llm_calls: int = 0
    image_bytes: bytes | None = None
    facts_used: int = 0  # fatos de memória injetados no contexto desta resposta


class SeekerPipeline:
    """
    Orquestrador: Input → Router → Phase → Record.
    
    Uso:
        pipeline = SeekerPipeline(api_keys)
        await pipeline.init()
        result = await pipeline.process("vale a pena migrar pra K8s?")
    """

    def __init__(self, api_keys: dict[str, str], db_path: str | None = None):
        self.api_keys = api_keys
        self.model_router = build_default_router()
        self.cognitive_router = CognitiveLoadRouter()
        self.intent_classifier = IntentClassifier()  # Intent classification + autonomy tiers
        self.extractor = FactExtractor(self.model_router, api_keys)

        # Search
        tavily_key = os.getenv("TAVILY_API_KEY", "")
        brave_key = os.getenv("BRAVE_API_KEY", "")
        self.searcher = WebSearcher(tavily_key=tavily_key, brave_key=brave_key)

        # Evidence
        self.arbitrage = EvidenceArbitrage(self.model_router, api_keys, min_models=2)
        self.gate = VerificationGate(self.model_router, api_keys)

        # Embeddings
        gemini_key = api_keys.get("gemini", "")
        self.embedder = GeminiEmbedder(gemini_key) if gemini_key else None
        self.semantic_search: SemanticSearch | None = None

        # Memory
        if db_path is None:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base, "data", "seeker_memory.db")
        self.memory = MemoryStore(db_path=db_path)
        self.compressor = SessionCompressor(self.model_router, self.api_keys)
        self.session = SessionManager(self.memory, compressor=self.compressor)
        self.decay_engine: DecayEngine | None = None

        # Cascade Adapter — multi-tier LLM routing com fallback
        self.cascade_adapter = CascadeAdapter(self.model_router, api_keys)

        # Performance Profiling
        self.profiler = SystemProfiler(history_size=200)
        self.prometheus_exporter = PrometheusExporter(namespace="seeker")

        # Error Recovery — circuit breaker, telemetry, graceful degradation
        self.error_recovery = ErrorRecoveryManager()

        # Phases — inicializadas no init()
        self._phase_reflex: ReflexPhase | None = None
        self._phase_deliberate: DeliberatePhase | None = None
        self._phase_deep: DeepPhase | None = None

        self._initialized = False
        self._decay_task: asyncio.Task | None = None
        self._background_tasks: set[asyncio.Task] = set()
        self.afk_protocol = None  # Setado pelo bot.py após init

        # Métricas de uso de memória (acumuladas na sessão)
        self._memory_stats = {"responses": 0, "with_facts": 0, "total_facts_injected": 0}

    async def init(self) -> None:
        if self._initialized:
            return

        await self.memory.initialize()

        # Session — carrega contexto anterior do Telegram
        await self.session.load_session("telegram")

        # Semantic search com embeddings persistidos
        if self.embedder:
            self.semantic_search = SemanticSearch(self.embedder, self.memory)
            await self.semantic_search.load()           # Carrega do disco (0 API calls)
            await self.semantic_search.ensure_indexed()  # Só embeda fatos NOVOS
            log.info("[pipeline] Semantic search com Gemini Embedding 2 ativo")

        # Decay engine
        self.decay_engine = DecayEngine(self.memory)
        try:
            stats = await self.decay_engine.run()
            if stats["decayed"] > 0 or stats["removed"] > 0:
                log.info(
                    f"[pipeline] Decay inicial: {stats['decayed']} decayed, "
                    f"{stats['removed']} removidos"
                )
        except Exception as e:
            log.warning(f"[pipeline] Decay inicial falhou: {e}")

        # Agenda decay periódico (6h)
        self._decay_task = asyncio.create_task(self._periodic_decay())

        # Inicializa phases
        self._phase_reflex = ReflexPhase(self.model_router, self.api_keys)
        self._phase_deliberate = DeliberatePhase(
            self.model_router, self.api_keys, self.searcher,
        )
        self._phase_deep = DeepPhase(
            self.model_router, self.api_keys, self.searcher,
            self.arbitrage, self.gate,
        )

        self._initialized = True
        log.info("[pipeline] Inicializado com session context + embeddings persistidos")

    async def process(
        self,
        user_input: str,
        session_id: str = "telegram",
        afk_protocol=None,
    ) -> PipelineResult:
        """
        Ponto de entrada principal.
        Input → Session → Memory → Router → Phase → Record.
        """
        if not self._initialized:
            await self.init()

        start = time.perf_counter()

        # ── 0. Session context ────────────────────────────────
        session_context = self.session.format_context(session_id)
        await self.session.add_turn(session_id, "user", user_input)

        # ── 1. Memory recall ──────────────────────────────────
        memory_prompt, facts_used = await self._build_memory_context(user_input)
        if session_context:
            memory_prompt = session_context + "\n\n" + memory_prompt

        # ── 2. Router (0 LLM) ────────────────────────────────
        decision = self.cognitive_router.route(user_input)
        log.info(
            f"[pipeline] {decision.depth.value} | "
            f"reason='{decision.reason}' | god={decision.god_mode} | "
            f"web={decision.needs_web}"
        )

        # ── 2.5. Intent Classification + Safety Check ─────────
        intent_card = self.intent_classifier.classify(user_input, user_id=session_id)
        log.info(intent_card.to_log_entry())

        # Bloquear ações HIGH-RISK antes de continuar
        if intent_card.requires_approval():
            blocked_response = (
                f"⚠️ **Ação bloqueada por segurança**\n\n"
                f"**Tipo:** {intent_card.intent_type.name}\n"
                f"**Risco:** {intent_card.risk_level.name}\n"
                f"**Motivo:** {intent_card.reasoning}\n\n"
                f"_Esta ação requer aprovação manual._"
            )
            log.warning(f"[intent] Bloqueada: {intent_card.reasoning}")

            await self.session.add_turn(session_id, "assistant", blocked_response)
            return PipelineResult(
                response=blocked_response,
                depth=CognitiveDepth.REFLEX,
                routing_reason="Bloqueada por IntentCard (HIGH-RISK)",
                total_latency_ms=int((time.perf_counter() - start) * 1000),
            )

        # ── 3. Dispatch pra fase ──────────────────────────────
        ctx = PhaseContext(
            user_input=user_input,
            decision=decision,
            memory_prompt=memory_prompt,
            session_context=session_context,
            afk_protocol=afk_protocol or self.afk_protocol,
            intent_card=intent_card,  # Disponível para fases se precisarem
        )

        if decision.depth == CognitiveDepth.REFLEX:
            # ⏱️ Profiling: Reflex Phase
            self.profiler.start_profiling(session_id, "Reflex")
            try:
                phase_result = await self._phase_reflex.execute(ctx)
                self.profiler.end_profiling(
                    session_id, "Reflex",
                    llm_calls=phase_result.llm_calls,
                    input_tokens=getattr(phase_result, 'input_tokens', 0),
                    output_tokens=getattr(phase_result, 'output_tokens', 0),
                    cost_usd=phase_result.cost_usd,
                    provider=getattr(phase_result, 'provider', ''),
                    model=getattr(phase_result, 'model', ''),
                    success=True
                )
            except Exception as e:
                self.profiler.end_profiling(
                    session_id, "Reflex",
                    success=False,
                    error_msg=str(e)
                )
                raise

        elif decision.depth == CognitiveDepth.DEEP:
            # ⏱️ Profiling: Deep Phase
            self.profiler.start_profiling(session_id, "Deep")
            try:
                phase_result = await self._phase_deep.execute(ctx)
                self.profiler.end_profiling(
                    session_id, "Deep",
                    llm_calls=phase_result.llm_calls,
                    input_tokens=getattr(phase_result, 'input_tokens', 0),
                    output_tokens=getattr(phase_result, 'output_tokens', 0),
                    cost_usd=phase_result.cost_usd,
                    provider=getattr(phase_result, 'provider', ''),
                    model=getattr(phase_result, 'model', ''),
                    success=True
                )
            except Exception as e:
                self.profiler.end_profiling(
                    session_id, "Deep",
                    success=False,
                    error_msg=str(e)
                )
                raise

        else:
            # ⏱️ Profiling: Deliberate Phase
            self.profiler.start_profiling(session_id, "Deliberate")
            try:
                phase_result = await self._phase_deliberate.execute(ctx)
                self.profiler.end_profiling(
                    session_id, "Deliberate",
                    llm_calls=phase_result.llm_calls,
                    input_tokens=getattr(phase_result, 'input_tokens', 0),
                    output_tokens=getattr(phase_result, 'output_tokens', 0),
                    cost_usd=phase_result.cost_usd,
                    provider=getattr(phase_result, 'provider', ''),
                    model=getattr(phase_result, 'model', ''),
                    success=True
                )
            except Exception as e:
                self.profiler.end_profiling(
                    session_id, "Deliberate",
                    success=False,
                    error_msg=str(e)
                )
                raise

        # ── 4. Monta resultado ────────────────────────────────
        result = PipelineResult(
            response=phase_result.response,
            depth=decision.depth,
            routing_reason=decision.reason,
            arbitrage=phase_result.arbitrage,
            verdict=phase_result.verdict,
            total_cost_usd=phase_result.cost_usd,
            total_latency_ms=int((time.perf_counter() - start) * 1000),
            llm_calls=phase_result.llm_calls,
            image_bytes=phase_result.image_bytes,
            facts_used=facts_used,
        )

        # Acumula métricas de uso de memória
        self._memory_stats["responses"] += 1
        if facts_used > 0:
            self._memory_stats["with_facts"] += 1
        self._memory_stats["total_facts_injected"] += facts_used

        # ── 5. Background: session + record ───────────────────
        self._spawn_background(self._post_process(session_id, user_input, result))

        return result

    # ─────────────────────────────────────────────────────────
    # LIFECYCLE
    # ─────────────────────────────────────────────────────────

    def get_memory_stats(self) -> dict:
        """Estatísticas de uso de memória semântica nesta sessão."""
        s = self._memory_stats
        total = s["responses"]
        rate = (s["with_facts"] / total * 100) if total > 0 else 0.0
        avg = (s["total_facts_injected"] / total) if total > 0 else 0.0
        return {
            "responses": total,
            "with_facts": s["with_facts"],
            "usage_rate_pct": round(rate, 1),
            "avg_facts_per_response": round(avg, 1),
        }

    def format_memory_footer(self) -> str:
        """Formata footer com métricas de memória para Telegram."""
        stats = self.get_memory_stats()
        rate = stats["usage_rate_pct"]
        avg = stats["avg_facts_per_response"]

        # Avalia se sistema está usando memória efetivamente
        if rate < 5:
            memory_status = "⚠️ (pouco utilizada)"
        elif rate < 30:
            memory_status = "📊 (moderada)"
        else:
            memory_status = "✅ (excelente)"

        return (
            f"\n---\n"
            f"<i>Memória: {memory_status} {rate}% das respostas usam fatos. "
            f"Média: {avg} fatos/resposta.</i>"
        )

    def get_performance_dashboard(self) -> dict:
        """Retorna dashboard de performance agregado"""
        all_stats = self.profiler.get_all_stats()
        worst = self.profiler.get_worst_offenders(limit=10)

        dashboard = {
            "timestamp": time.time(),
            "goals": {},
            "worst_offenders": [],
            "system_health": {}
        }

        # Agregações por goal
        for goal_id, goal_metrics in all_stats.items():
            dashboard["goals"][goal_id] = goal_metrics.to_dict()

        # Top 10 worst (latência)
        for metric in worst[:10]:
            dashboard["worst_offenders"].append({
                "goal_id": metric.goal_id,
                "phase": metric.phase_name,
                "latency_ms": f"{metric.latency_ms:.0f}",
                "cost_usd": f"${metric.cost_usd:.4f}",
                "provider": metric.provider,
                "timestamp": metric.timestamp.isoformat()
            })

        # Health metrics
        if all_stats:
            total_goals = len(all_stats)
            total_success = sum(1 for g in all_stats.values() if g.success_rate > 80)
            dashboard["system_health"] = {
                "total_goals": total_goals,
                "healthy_goals": total_success,
                "health_pct": f"{(total_success / total_goals * 100):.1f}%" if total_goals > 0 else "0%",
                "total_cost_usd": f"${sum(g.total_cost_usd for g in all_stats.values()):.2f}",
                "avg_latency_ms": f"{(sum(g.avg_latency_ms for g in all_stats.values()) / total_goals):.0f}" if total_goals > 0 else "0"
            }

        return dashboard

    def format_perf_report(self) -> str:
        """Formata relatório de performance para Telegram"""
        dashboard = self.get_performance_dashboard()
        health = dashboard["system_health"]
        worst = dashboard["worst_offenders"]

        report = (
            f"<b>📊 PERFORMANCE DASHBOARD</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>System Health</b>\n"
            f"├ Goals: {health.get('total_goals', 0)} ({health.get('health_pct', 'N/A')} saudáveis)\n"
            f"├ Total Cost: {health.get('total_cost_usd', '$0.00')}\n"
            f"└ Avg Latency: {health.get('avg_latency_ms', '0')}ms\n\n"
        )

        if worst:
            report += "<b>Top 10 Worst Offenders</b> (by latency)\n"
            for i, offender in enumerate(worst, 1):
                report += (
                    f"{i}. [{offender['phase']}] {offender['goal_id']}\n"
                    f"   └ {offender['latency_ms']}ms | {offender['cost_usd']} | {offender['provider']}\n"
                )
        else:
            report += "<i>Aguardando dados de performance...</i>"

        return report

    def _spawn_background(self, coro) -> asyncio.Task:
        """Cria background task com tracking e logging de erro."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            log.error(f"[pipeline] Background task falhou: {exc}", exc_info=exc)

    async def close(self) -> None:
        """
        Shutdown gracioso com três fases:
        1. Cancela decay periódico
        2. Aguarda background tasks com commit final
        3. Fecha recursos (embedder, VLM, memória)
        """
        # Fase 1: Cancela decay periódico
        if self._decay_task and not self._decay_task.done():
            self._decay_task.cancel()
            try:
                await self._decay_task
            except asyncio.CancelledError:
                log.info("[pipeline] Decay task cancelada com sucesso")
            except Exception as e:
                log.error(f"[pipeline] Erro ao cancelar decay task: {e}", exc_info=True)

        # Fase 2: Aguarda background tasks pendentes com commit final (max 10s)
        if self._background_tasks:
            log.info(f"[pipeline] Aguardando {len(self._background_tasks)} background tasks...")
            done, pending = await asyncio.wait(
                self._background_tasks, timeout=10.0
            )
            if done:
                log.info(f"[pipeline] {len(done)} background tasks completadas")
            if pending:
                log.warning(f"[pipeline] {len(pending)} background tasks ainda pendentes após timeout, cancelando...")
                for t in pending:
                    t.cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(t), timeout=2.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        pass

        # Fase 2b: Commit final para dados que possam estar pendentes
        try:
            await self.memory.commit()
            log.info("[pipeline] Commit final da memória completo")
        except Exception as e:
            log.error(f"[pipeline] Erro no commit final: {e}", exc_info=True)

        # Fase 3: Fecha recursos
        # Fecha embedder (httpx pool)
        if self.embedder:
            try:
                await self.embedder.close()
            except Exception as e:
                log.error(f"[pipeline] Erro ao fechar embedder: {e}", exc_info=True)

        # Fecha VLM client se existir
        vlm = getattr(self, "vlm_client", None)
        if vlm:
            try:
                await vlm.close()
            except Exception as e:
                log.error(f"[pipeline] Erro ao fechar VLM client: {e}", exc_info=True)

        # Fecha memória
        try:
            await self.memory.close()
        except Exception as e:
            log.error(f"[pipeline] Erro ao fechar memória: {e}", exc_info=True)

        log.info("[pipeline] Shutdown gracioso completo")

    # ─────────────────────────────────────────────────────────
    # PRIVATE
    # ─────────────────────────────────────────────────────────

    async def _build_memory_context(self, user_input: str) -> tuple[str, int]:
        """Constrói contexto de memória com prioridade hierárquica.

        Retorna (memory_prompt, facts_used) onde facts_used é a contagem
        de fatos semânticos injetados no contexto desta resposta.
        """
        # Busca fatos
        facts = await self.memory.get_facts(min_confidence=0.3, limit=20)

        # Busca semântica
        semantic_matches = None
        if self.semantic_search:
            semantic_matches = await self.semantic_search.find_similar_facts(
                user_input, top_k=5, min_similarity=0.35
            )

        # Mescla fatos + matches semânticos antes de priorizar
        all_facts = list(facts) if facts else []
        if semantic_matches:
            seen = {f.get('fact', '') for f in all_facts}
            for sm in semantic_matches:
                if sm.get('fact', '') not in seen:
                    all_facts.append(sm)

        # Prioriza por camada hierárquica
        prioritized = prioritize_facts(all_facts, limit=15)
        facts_used = len(prioritized)

        # Formata com prioridade
        memory_prompt = format_hierarchical_context(prioritized, limit=15)

        # Adiciona episódios recentes (não afetados pela hierarquia)
        episodes = await self.memory.get_recent_episodes(limit=5)
        if episodes:
            ep_lines = ["\n=== INTERAÇÕES RECENTES ==="]
            for ep in episodes:
                icon = {"reflex": "⚡", "deliberate": "🧠", "deep": "🔬"}.get(ep["depth"], "")
                ep_lines.append(f"{icon} {ep['user_input'][:100]}")
                if ep["response_summary"]:
                    ep_lines.append(f"   → {ep['response_summary'][:100]}")
            memory_prompt += "\n".join(ep_lines)

        # Fatos relevantes por busca textual (fallback se semântica falhar)
        if not semantic_matches and user_input:
            relevant = await self.memory.search_facts(user_input, limit=5)
            seen_ids = {f.get("fact_id") for f in prioritized}
            new_facts = [f for f in relevant if f.get("id", -1) not in seen_ids]
            if new_facts:
                memory_prompt += "\n=== FATOS RELEVANTES (busca textual) ==="
                for f in new_facts:
                    memory_prompt += f"\n[{f['confidence']:.0%}] {f['fact']}"
                facts_used += len(new_facts)

        return memory_prompt, facts_used

    async def _post_process(
        self,
        session_id: str,
        user_input: str,
        result: PipelineResult,
    ) -> None:
        """Background: registra sessão, extrai fatos, registra episódio."""
        try:
            # Respostas de sistema (0 LLM calls) não precisam de extração
            if result.llm_calls == 0:
                await self.session.add_turn(session_id, "assistant", result.response[:2000])
                return

            # Registra resposta na sessão
            await self.session.add_turn(
                session_id, "assistant", result.response[:2000]
            )

            # Extrai fatos
            facts, summary = await self.extractor.extract(user_input, result.response)

            # Salva fatos + embeddings (sem commit individual)
            for f in facts:
                fact_id = await self.memory.upsert_fact(
                    fact=f["fact"],
                    category=f.get("category", "general"),
                    confidence=f.get("confidence", 0.5),
                    source="extracted",
                    _batch=True,
                )
                # Indexa embedding do novo fato (persistido no SQLite)
                if self.semantic_search and fact_id > 0:
                    try:
                        await self.semantic_search.add(fact_id, f["fact"])
                    except Exception:
                        pass

            # Registra episódio (sem commit individual)
            await self.memory.record_episode(
                session_id=session_id,
                user_input=user_input,
                response_summary=summary,
                depth=result.depth.value,
                module=result.routing_reason[:50],
                had_arbitrage=result.arbitrage is not None,
                had_conflicts=(
                    result.arbitrage.has_conflicts if result.arbitrage else False
                ),
                cost_usd=result.total_cost_usd,
                latency_ms=result.total_latency_ms,
                _batch=True,
            )

            # Commit único para todo o _post_process
            await self.memory.commit()

            log.info(
                f"[memory] Registrado: {len(facts)} fatos, "
                f"episódio '{user_input[:40]}...'"
            )

        except Exception as e:
            log.warning(f"[memory] Falha ao registrar: {e}")

    async def _periodic_decay(self) -> None:
        """
        Roda decay a cada 6 horas em background com tratamento robusto de erros.

        Garante que:
        1. Erros não matam a task
        2. CancelledError é propagado para shutdown gracioso
        3. Logs explicam falhas para debug
        """
        try:
            iteration = 0
            while True:
                try:
                    # Sleep com interrupção graciosa
                    await asyncio.sleep(6 * 3600)
                    iteration += 1

                    if not self.decay_engine:
                        log.warning("[decay] Decay engine não inicializado")
                        continue

                    # Roda decay
                    stats = await self.decay_engine.run()
                    log.info(
                        f"[decay] Ciclo #{iteration} completo: "
                        f"{stats['total']} avaliados, "
                        f"{stats['decayed']} decayed, "
                        f"{stats['removed']} removidos"
                    )

                    # Re-indexa embeddings se houve remoções
                    if self.semantic_search and stats["removed"] > 0:
                        try:
                            await self.semantic_search.ensure_indexed()
                            log.info("[decay] Embeddings re-indexados após remoções")
                        except Exception as e:
                            log.warning(
                                f"[decay] Falha ao re-indexar embeddings: {e}",
                                exc_info=True
                            )

                except asyncio.CancelledError:
                    # Propagate para que o close() saiba que foi cancelado
                    log.info(
                        f"[decay] Task cancelada após {iteration} ciclos "
                        f"(shutdown gracioso)"
                    )
                    raise

                except Exception as e:
                    # Erros na execução do decay não devem matar a task
                    log.error(
                        f"[decay] Erro no ciclo #{iteration}: {e}",
                        exc_info=True
                    )
                    # Continua no próximo ciclo

        except asyncio.CancelledError:
            # Re-raise para respeitarasyncio.CancelledError como sinalizador
            raise
        except Exception as e:
            log.error(
                f"[decay] Task encerrada por erro fatal: {e}",
                exc_info=True
            )
            raise
