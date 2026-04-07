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
from src.core.phases.base import PhaseContext, PhaseResult
from src.core.phases.reflex import ReflexPhase
from src.core.phases.deliberate import DeliberatePhase
from src.core.phases.deep import DeepPhase
from src.providers.base import LLMRequest, invoke_with_fallback
from src.core.memory.hierarchy import prioritize_facts, format_hierarchical_context

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

        # ── 3. Dispatch pra fase ──────────────────────────────
        ctx = PhaseContext(
            user_input=user_input,
            decision=decision,
            memory_prompt=memory_prompt,
            session_context=session_context,
            afk_protocol=afk_protocol or self.afk_protocol,
        )

        if decision.depth == CognitiveDepth.REFLEX:
            phase_result = await self._phase_reflex.execute(ctx)
        elif decision.depth == CognitiveDepth.DEEP:
            phase_result = await self._phase_deep.execute(ctx)
        else:
            phase_result = await self._phase_deliberate.execute(ctx)

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
        """Shutdown gracioso: cancela decay, aguarda tasks, fecha memória."""
        # Cancela decay periódico
        if self._decay_task and not self._decay_task.done():
            self._decay_task.cancel()
            try:
                await self._decay_task
            except asyncio.CancelledError:
                pass
            log.info("[pipeline] Decay task cancelada")

        # Aguarda background tasks pendentes (max 10s)
        if self._background_tasks:
            log.info(f"[pipeline] Aguardando {len(self._background_tasks)} background tasks...")
            done, pending = await asyncio.wait(
                self._background_tasks, timeout=10.0
            )
            for t in pending:
                t.cancel()

        # Fecha embedder (httpx pool)
        if self.embedder:
            await self.embedder.close()

        # Fecha VLM client se existir
        vlm = getattr(self, "vlm_client", None)
        if vlm:
            await vlm.close()

        # Fecha memória
        await self.memory.close()
        log.info("[pipeline] Shutdown completo")

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
        """Roda decay a cada 6 horas em background."""
        try:
            while True:
                await asyncio.sleep(6 * 3600)
                try:
                    if self.decay_engine:
                        stats = await self.decay_engine.run()
                        log.info(f"[decay] Periódico: {stats}")

                        # Re-indexa embeddings se houve remoções
                        if self.semantic_search and stats["removed"] > 0:
                            await self.semantic_search.ensure_indexed()
                except Exception as e:
                    log.warning(f"[decay] Periódico falhou: {e}")
        except asyncio.CancelledError:
            log.info("[decay] Task de decay cancelada (shutdown)")
            raise
