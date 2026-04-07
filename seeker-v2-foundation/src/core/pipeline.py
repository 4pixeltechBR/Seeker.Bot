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
from src.core.phases.base import PhaseContext, PhaseResult
from src.core.phases.reflex import ReflexPhase
from src.core.phases.deliberate import DeliberatePhase
from src.core.phases.deep import DeepPhase
from src.providers.base import LLMRequest, invoke_with_fallback

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
        self.session = SessionManager(self.memory)
        self.decay_engine: DecayEngine | None = None

        # Phases — inicializadas no init()
        self._phase_reflex: ReflexPhase | None = None
        self._phase_deliberate: DeliberatePhase | None = None
        self._phase_deep: DeepPhase | None = None

        self._initialized = False
        self._decay_task = None

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
        memory_prompt = await self._build_memory_context(user_input)
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
        )

        # ── 5. Background: session + record ───────────────────
        asyncio.create_task(self._post_process(session_id, user_input, result))

        return result

    # ─────────────────────────────────────────────────────────
    # PRIVATE
    # ─────────────────────────────────────────────────────────

    async def _build_memory_context(self, user_input: str) -> str:
        """Constrói contexto de memória, usando semantic search se disponível."""
        if self.semantic_search:
            similar_facts = await self.semantic_search.find_similar_facts(
                user_input, top_k=5, min_similarity=0.35
            )
            memory_prompt = await self.memory.format_context(query=user_input)
            if similar_facts:
                semantic_lines = ["=== FATOS SEMANTICAMENTE RELEVANTES ==="]
                for f in similar_facts:
                    sim = f.get("similarity", 0)
                    semantic_lines.append(
                        f"[{f['confidence']:.0%} | sim:{sim:.0%}] {f['fact']}"
                    )
                memory_prompt += "\n" + "\n".join(semantic_lines)
            return memory_prompt
        else:
            return await self.memory.format_context(query=user_input)

    async def _post_process(
        self,
        session_id: str,
        user_input: str,
        result: PipelineResult,
    ) -> None:
        """Background: registra sessão, extrai fatos, registra episódio."""
        try:
            # Registra resposta na sessão
            await self.session.add_turn(
                session_id, "assistant", result.response[:2000]
            )

            # Extrai fatos
            facts, summary = await self.extractor.extract(user_input, result.response)

            # Salva fatos + embeddings
            for f in facts:
                fact_id = await self.memory.upsert_fact(
                    fact=f["fact"],
                    category=f.get("category", "general"),
                    confidence=f.get("confidence", 0.5),
                    source="extracted",
                )
                # Indexa embedding do novo fato (persistido no SQLite)
                if self.semantic_search and fact_id > 0:
                    try:
                        await self.semantic_search.add(fact_id, f["fact"])
                    except Exception:
                        pass

            # Registra episódio
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
            )

            log.info(
                f"[memory] Registrado: {len(facts)} fatos, "
                f"episódio '{user_input[:40]}...'"
            )

        except Exception as e:
            log.warning(f"[memory] Falha ao registrar: {e}")

    async def _periodic_decay(self) -> None:
        """Roda decay a cada 6 horas em background."""
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
