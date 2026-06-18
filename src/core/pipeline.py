"""
Seeker.Bot — Core Pipeline
src/core/pipeline.py

Main orchestrator for cognitive request processing. Routes incoming requests through
a multi-tier cognitive system (REFLEX → DELIBERATE → DEEP) based on complexity analysis.

Architecture:
    - CognitiveLoadRouter: Analyzes request → decides depth (0 LLM, regex-based)
    - PhaseResult: Abstract execution model (each phase implements independently)
    - MemoryStore: 4-table SQLite for episodic, semantic, facts, embeddings
    - CascadeAdapter: 6-tier LLM fallback (Gemini → Groq → NVIDIA → DeepSeek → Mistral → Cache)
    - EvidenceArbitrage: Triangulates 2-3 models for hallucination detection
    - VerificationGate: Independent judge verifies critical claims
    - SafetyLayer: Governs autonomy tiers and action permissions

Key Components:
    - ReflexPhase: Direct response, no LLM calls (status checks, simple facts)
    - DeliberatePhase: Memory + web search (1-2 LLM calls)
    - DeepPhase: Evidence arbitrage + triangulation + research loops (3+ LLM calls)
    - RL Infrastructure: Bandit model learns which provider works best per role
    - Decay Engine: Confidence degrades over time (half-life per domain)

Usage:
    pipeline = SeekerPipeline(api_keys={'gemini': '...', 'groq': '...', ...})
    await pipeline.init()
    result = await pipeline.process("Pergunta complexa", user_id=123)
    # result: PipelineResult(response, depth, cost_usd, latency_ms, facts_used, ...)
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field

from config.models import build_default_router
from src.core.router.cognitive_load import (
    CognitiveLoadRouter,
    CognitiveDepth,
    ExecutionMode,
)
from src.skills.knowledge_vault import VaultSearcher
from src.core.evidence.arbitrage import EvidenceArbitrage, ArbitrageResult
from src.core.evidence.decay import DecayEngine
from src.core.search.web import WebSearcher
from src.core.healing.judge import VerificationGate, JudgeVerdict
from src.core.memory.store import MemoryStore
from src.core.memory.extractor import FactExtractor
from src.core.memory.embeddings import GeminiEmbedder, SemanticSearch
from src.core.memory.session import SessionManager
from src.core.memory.compressor import SessionCompressor
from src.core.memory.session_store import SessionStore
from src.core.intent_card import IntentClassifier
from src.core.safety_layer_enhanced import (
    SafetyLayer,
    SafetyPolicy,
    AutonomyTier,
    ActionType,
)
from src.core.phases.base import PhaseContext
from src.core.phases.reflex import ReflexPhase
from src.core.phases.deliberate import DeliberatePhase
from src.core.phases.deep import DeepPhase
from src.providers.cascade import CascadeAdapter
from src.core.rl import (
    RewardCollector,
    StateEncoder,
    SeekerState,
    CascadeBandit,
    BanditMode,
)
from src.core.batch_operations import BatchOperationsManager
from src.core.metrics import Sprint11Tracker, IntegrityMonitor
from src.core.memory.hierarchy import score_fact, format_4layer_context
from src.core.profiling.profiler import SystemProfiler
from src.core.profiling.exporter import PrometheusExporter
from src.core.error_recovery import ErrorRecoveryManager
from src.core.budget import RastreadorCustos
from src.core.data import ArmazemDados, Indexador, GerenciadorRetencao
from src.core.analytics import DashboardFinanceiro, Forecaster, Reporter
from src.core.memory.obsidian import ObsidianExporter
from src.core.exporters.drive import GoogleDriveExporter

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
    new_facts_count: int = 0  # fatos extraídos deste turno
    _extraction: dict = field(
        default_factory=dict
    )  # Cache de extração para post-process
    decision_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )  # ID p/ RL feedback


class SeekerPipeline:
    """
    Main request orchestrator. Routes requests through cognitive phases and manages
    all infrastructure (memory, providers, search, evidence verification).

    Args:
        api_keys: Dict of provider keys {'gemini', 'groq', 'nvidia_nim', 'deepseek', 'mistral'}
        db_path: SQLite database path (defaults to data/seeker_memory.db)

    Attributes:
        cognitive_router: Routes requests to REFLEX, DELIBERATE, or DEEP based on complexity
        memory: 4-table SQLite store for episodic, semantic, facts, and embeddings
        cascade_adapter: 6-tier LLM fallback with automatic provider ranking
        arbitrage: Evidence triangulation with 2-3 models in parallel
        gate: Verification gate (independent judge) for critical claims
        session: Session manager with compression and context windowing
        safety_layer: Governs autonomous actions and autonomy tiers

    Example:
        api_keys = {
            'gemini': 'sk-...',
            'groq': 'gsk_...',
            'nvidia_nim': 'nvapi-...',
        }
        pipeline = SeekerPipeline(api_keys)
        await pipeline.init()
        result = await pipeline.process("Qual é o melhor framework Python para ML?", user_id=123)
        print(f"Response: {result.response}")
        print(f"Depth: {result.depth} | Cost: ${result.total_cost_usd:.4f} | Latency: {result.total_latency_ms}ms")
    """

    def __init__(self, api_keys: dict[str, str], db_path: str | None = None):
        self.api_keys = api_keys
        self.model_router = build_default_router()
        self.cognitive_router = CognitiveLoadRouter(self.model_router, api_keys)
        self.intent_classifier = (
            IntentClassifier()
        )  # Intent classification + autonomy tiers
        self.extractor = FactExtractor(self.model_router, api_keys)
        self.integrity = IntegrityMonitor()

        # Budget & Cost Tracking — rastreamento de gastos com LLM
        self.cost_tracker = RastreadorCustos(
            limite_diario_usd=10.0,
            limite_mensal_usd=200.0,
        )

        # Search
        tavily_key = os.getenv("TAVILY_API_KEY", "")
        brave_key = os.getenv("BRAVE_API_KEY", "")
        gemini_key = api_keys.get("gemini", "") or os.getenv("GEMINI_API_KEY", "")
        self.searcher = WebSearcher(
            tavily_key=tavily_key, 
            brave_key=brave_key,
            cost_tracker=self.cost_tracker,
            gemini_key=gemini_key
        )

        # Evidence
        self.arbitrage = EvidenceArbitrage(self.model_router, api_keys, min_models=2)
        self.gate = VerificationGate(self.model_router, api_keys)

        # Embeddings
        gemini_key = api_keys.get("gemini", "")
        self.embedder = GeminiEmbedder(gemini_key) if gemini_key else None
        self.semantic_search: SemanticSearch | None = None

        # Memory
        if db_path is None:
            base = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            db_path = os.path.join(base, "data", "seeker_memory.db")
        self.memory = MemoryStore(db_path=db_path)
        
        # Session Store - Isolamento para evitar lock-contention
        self.session_store = SessionStore()
        self.compressor = SessionCompressor(
            self.model_router, 
            self.api_keys, 
            session_store=self.session_store
        )
        self.session = SessionManager(self.session_store, compressor=self.compressor)
        self.decay_engine: DecayEngine | None = None

        # Cascade Adapter — multi-tier LLM routing com fallback
        self.cascade_adapter = CascadeAdapter(self.model_router, api_keys)
        
        # Signature Guardrail para detecção de loops
        from src.core.rate_limiting.signature import SignatureGuardrail
        self.signature_guardrail = SignatureGuardrail()

        # RL Infrastructure — coleta dados para aprendizado (Sprint 1)
        self.reward_collector = RewardCollector()
        self.state_encoder = StateEncoder()

        # Sprint 2 — LinUCB Bandit (shadow mode: prediz mas não age)
        self.cascade_bandit = CascadeBandit(mode=BanditMode.SHADOW)
        self.cascade_bandit.load()  # carrega modelo salvo se existir

        # Batch Operations Manager — consolidação de commits (Sprint 11.3)
        self.batch_manager = BatchOperationsManager(max_pending=100)

        # Safety Layer — controle de autonomia e ações (Sprint 7.3)
        safety_policy = SafetyPolicy()
        self.safety_layer = SafetyLayer(safety_policy)

        # Sprint 11 Metrics Tracker — monitoramento de otimizações (Fase 4)
        self.sprint11_tracker = Sprint11Tracker()

        # Performance Profiling
        self.profiler = SystemProfiler(history_size=200)
        self.prometheus_exporter = PrometheusExporter(namespace="seeker")

        # Error Recovery — circuit breaker, telemetry, graceful degradation
        self.error_recovery = ErrorRecoveryManager()

        vault_path = os.getenv("OBSIDIAN_VAULT_PATH")
        self.obsidian_exporter = (
            ObsidianExporter(self.memory, vault_path) if vault_path else None
        )

        # Google Drive Exporter
        drive_creds = os.getenv("GOOGLE_DRIVE_CREDENTIALS") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config",
            "credentials.json",
        )
        # Fallback para o nome bizarro se existir
        if not os.path.exists(drive_creds) and os.path.exists(drive_creds + ".json"):
            drive_creds += ".json"

        drive_folder = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
        self.drive_exporter = None
        if drive_folder and os.path.exists(drive_creds):
            # Validação rápida: service account JSON tem o campo "type": "service_account"
            try:
                with open(drive_creds, "r") as f:
                    creds_data = json.load(f)
                    if creds_data.get("type") == "service_account":
                        self.drive_exporter = GoogleDriveExporter(
                            drive_creds, drive_folder
                        )
                    else:
                        log.warning(
                            f"[pipeline] Arquivo {drive_creds} não é uma Service Account válida. "
                            "O exporter de dossiês para o Drive será desativado."
                        )
            except Exception as e:
                log.warning(f"[pipeline] Falha ao ler credenciais do Drive: {e}")
        else:
            log.debug(
                "[pipeline] Google Drive Exporter desativado (sem folder_id ou credenciais)"
            )

        # Data Manager — armazenamento eficiente de fatos semânticos
        data_db_path = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ),
            "data",
            "seeker_data.db",
        )
        self.data_store = ArmazemDados(db_path=data_db_path)
        self.data_indexador = Indexador(self.data_store)
        self.data_gerenciador = GerenciadorRetencao(self.data_store)

        # Analytics — Dashboard financeiro, previsões e relatórios
        self.analytics_dashboard = DashboardFinanceiro(
            cost_tracker=self.cost_tracker,
            profiler=self.profiler,
        )
        self.analytics_forecaster = Forecaster(
            cost_tracker=self.cost_tracker,
            tamanho_historico=30,
        )
        self.analytics_reporter = Reporter(
            dashboard=self.analytics_dashboard,
            forecaster=self.analytics_forecaster,
        )

        # Phases — inicializadas no init()
        self._phase_reflex: ReflexPhase | None = None
        self._phase_deliberate: DeliberatePhase | None = None
        self._phase_deep: DeepPhase | None = None

        self._initialized = False
        self._decay_task: asyncio.Task | None = None
        self._background_tasks: set[asyncio.Task] = set()
        self.afk_protocol = None  # Setado pelo bot.py após init
        
        from src.skills.subagent_dispatcher import SubagentDispatcher
        self.subagent_dispatcher = SubagentDispatcher(self)
        
        from src.skills.agent_browser import AgentBrowser
        self.agent_browser = AgentBrowser(self)

        from src.skills.x_search import XSearcher
        self.x_searcher = XSearcher(self)

        from src.skills.tts import TTSGenerator
        self.tts_generator = TTSGenerator(self)

        from src.skills.image_gen import ImageGenerator
        self.image_generator = ImageGenerator(self)

        from src.skills.microsoft_graph import MSGraphClient
        self.ms_graph = MSGraphClient(self)

        from src.skills.kanban import KanbanBoard
        self.kanban_board = KanbanBoard(self)

        from src.skills.osv_check import OSVScanner
        self.osv_scanner = OSVScanner(self)

        from src.skills.fuzzy_match import FuzzyMatcher
        self.fuzzy_matcher = FuzzyMatcher(self)

        # Métricas de uso de memória (acumuladas na sessão)
        self._memory_stats = {
            "responses": 0,
            "with_facts": 0,
            "total_facts_injected": 0,
        }

    async def init(self) -> None:
        if self._initialized:
            return

        await self.memory.initialize()

        # Session — carrega contexto anterior do Telegram
        await self.session.load_session("telegram")

        # Semantic search com embeddings persistidos
        if self.embedder:
            self.semantic_search = SemanticSearch(self.embedder, self.memory)
            await self.semantic_search.load()  # Carrega do disco (0 API calls)
            await self.semantic_search.ensure_indexed()  # Só embeda fatos NOVOS
            log.info("[pipeline] Semantic search com Gemini Embedding 2 ativo")

        # Decay engine
        self._vault_searcher = None  # Lazy load
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
            self.model_router,
            self.api_keys,
            self.searcher,
            self.signature_guardrail,
        )
        self._phase_deep = DeepPhase(
            self.model_router,
            self.api_keys,
            self.searcher,
            self.arbitrage,
            self.gate,
            self.signature_guardrail,
        )

        self._initialized = True
        log.info("[pipeline] Inicializado com session context + embeddings persistidos")

    async def process(
        self,
        user_input: str,
        session_id: str = "telegram",
        execution_mode: str = "interactive",
        afk_protocol=None,
    ) -> PipelineResult:
        """
        Ponto de entrada principal.
        Input → Session → Memory → Router → Phase → Record.
        """
        if not self._initialized:
            await self.init()

        start = time.perf_counter()

        # Reseta o guardrail de assinaturas a cada novo turno do usuário,
        # garantindo que pesquisas legítimas de tópicos distintos não sejam
        # bloqueadas por histórico de turnos anteriores.
        self.signature_guardrail.reset_turn(session_id)

        # ── 0. Session context ────────────────────────────────
        session_context = self.session.format_context(session_id)
        await self.session.add_turn(session_id, "user", user_input)

        # ── 1. Memory recall ──────────────────────────────────
        memory_prompt, facts_used = await self._build_memory_context(user_input)
        if session_context:
            memory_prompt = session_context + "\n\n" + memory_prompt

        # ── 2. Router (0 LLM) ────────────────────────────────
        mode_enum = ExecutionMode(execution_mode.lower())
        decision = await self.cognitive_router.route(user_input, mode=mode_enum)
        log.info(
            f"[pipeline] {decision.depth.value} | "
            f"reason='{decision.reason}' | god={decision.god_mode} | "
            f"web={decision.needs_web}"
        )

        # ── RL: captura estado antes da execução ──────────────
        decision_id = str(uuid.uuid4())
        rl_state = SeekerState(
            query=user_input,
            budget_daily_used_usd=self.cost_tracker._gastos_diarios.get(
                str(time.strftime("%Y-%m-%d")), 0.0
            ),
            budget_daily_limit_usd=self.cost_tracker.limite_diario_usd,
            budget_monthly_used_usd=self.cost_tracker._gastos_mensais.get(
                str(time.strftime("%Y-%m")), 0.0
            ),
            budget_monthly_limit_usd=self.cost_tracker.limite_mensal_usd,
            session_turns=len(self.session._cache.get(session_id, [])),
        )
        self.reward_collector.open_event(
            decision_id=decision_id,
            action_taken=decision.depth.value,
            context=f"query={user_input[:80]!r}",
            state_snapshot=self.state_encoder.describe(rl_state),
        )

        # ── Sprint 2: LinUCB Bandit (shadow) ─────────────────────────
        # Prediz qual depth seria ideal. Em SHADOW: só loga, não interfere.
        # Em ACTIVE/FULL (futuro): substituirá o CognitiveLoadRouter.
        try:
            rl_features = self.state_encoder.encode(rl_state)
            bandit_decision = self.cascade_bandit.predict(
                features=rl_features,
                router_arm=decision.depth.value,
                decision_id=decision_id,
            )
            if not bandit_decision.agrees:
                log.info(
                    f"[bandit:shadow] Diverge: router={bandit_decision.router_arm} "
                    f"→ bandit sugeriria={bandit_decision.recommended_arm} "
                    f"(α={bandit_decision.alpha:.3f})"
                )
        except Exception as e:
            log.debug(f"[bandit] Erro no predict (ignorado): {e}")

        # Fecha eventos stale de decisões anteriores sem feedback
        self.reward_collector.close_stale_events()

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

        # ── 2.7. Vault Retrieval (Obsidian) ───────────────────
        vault_context = ""
        if decision.needs_vault:
            if not self._vault_searcher:
                self._vault_searcher = VaultSearcher()

            vault_context = self._vault_searcher.get_context_for_llm(user_input)
            if vault_context:
                log.info(
                    f"[pipeline] Contexto do cofre injetado ({len(vault_context)} chars)"
                )
                memory_prompt += f"\n\n{vault_context}"

        # ── 3. Dispatch pra fase com Active Research Loops ────
        ctx = PhaseContext(
            user_input=user_input,
            decision=decision,
            memory_prompt=memory_prompt,
            session_context=session_context,
            afk_protocol=afk_protocol or self.afk_protocol,
        )

        max_active_loops = 2
        active_loop = 0
        phase_result = None

        while active_loop < max_active_loops:
            if decision.depth == CognitiveDepth.REFLEX:
                # ⏱️ Profiling: Reflex Phase
                self.profiler.start_profiling(session_id, "Reflex")
                try:
                    phase_result = await self._phase_reflex.execute(ctx)
                    self.profiler.end_profiling(
                        session_id,
                        "Reflex",
                        llm_calls=phase_result.llm_calls,
                        input_tokens=getattr(phase_result, "input_tokens", 0),
                        output_tokens=getattr(phase_result, "output_tokens", 0),
                        cost_usd=phase_result.cost_usd,
                        provider=getattr(phase_result, "provider", ""),
                        model=getattr(phase_result, "model", ""),
                        success=True,
                    )
                except Exception as e:
                    self.profiler.end_profiling(
                        session_id, "Reflex", success=False, error_msg=str(e)
                    )
                    raise

            elif decision.depth == CognitiveDepth.DEEP:
                # ⏱️ Profiling: Deep Phase
                self.profiler.start_profiling(session_id, "Deep")
                try:
                    phase_result = await self._phase_deep.execute(ctx)
                    self.profiler.end_profiling(
                        session_id,
                        "Deep",
                        llm_calls=phase_result.llm_calls,
                        input_tokens=getattr(phase_result, "input_tokens", 0),
                        output_tokens=getattr(phase_result, "output_tokens", 0),
                        cost_usd=phase_result.cost_usd,
                        provider=getattr(phase_result, "provider", ""),
                        model=getattr(phase_result, "model", ""),
                        success=True,
                    )
                except Exception as e:
                    self.profiler.end_profiling(
                        session_id, "Deep", success=False, error_msg=str(e)
                    )
                    raise

            else:
                # ⏱️ Profiling: Deliberate Phase
                self.profiler.start_profiling(session_id, "Deliberate")
                try:
                    phase_result = await self._phase_deliberate.execute(ctx)
                    self.profiler.end_profiling(
                        session_id,
                        "Deliberate",
                        llm_calls=phase_result.llm_calls,
                        input_tokens=getattr(phase_result, "input_tokens", 0),
                        output_tokens=getattr(phase_result, "output_tokens", 0),
                        cost_usd=phase_result.cost_usd,
                        provider=getattr(phase_result, "provider", ""),
                        model=getattr(phase_result, "model", ""),
                        success=True,
                    )
                except Exception as e:
                    self.profiler.end_profiling(
                        session_id, "Deliberate", success=False, error_msg=str(e)
                    )
                    raise

            # Intercepta tags de ferramentas para o Active Loop
            if phase_result and phase_result.response:
                response_text = phase_result.response
                has_tool_call = False
                tool_output = ""
                
                # Verifica se há alguma ferramenta registrada via adaptadores dinâmicos
                from src.core.execution.adapters.manager import find_registered_tag, execute_ported_tool
                ported_tag_info = find_registered_tag(response_text)
                
                if ported_tag_info:
                    tag, arg = ported_tag_info
                    log.info(f"[pipeline] Active Loop - Ferramenta Portada Detectada: Tag='{tag}', Arg='{arg}'")
                    has_tool_call = True
                    try:
                        # Roteia para o executor do adaptador correspondente
                        res = await execute_ported_tool(tag, arg, response_text, session_id)
                        tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA PORTADA ({tag}) ━━━\n{res}"
                    except Exception as e:
                        tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA PORTADA ({tag}) - ERRO ━━━\n{e}"

                # 1. SEARCH_REQUIRED
                elif "[SEARCH_REQUIRED:" in response_text:
                    start_idx = response_text.find("[SEARCH_REQUIRED:") + len("[SEARCH_REQUIRED:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        query_solicitada = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                        log.info(f"[pipeline] Active Loop - SEARCH_REQUIRED: '{query_solicitada}'")
                        has_tool_call = True
                        try:
                            search_results = await self.searcher.search(query_solicitada, max_results=3)
                            tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (SEARCH_REQUIRED) ━━━\n{search_results.to_context(max_results=3)}"
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (SEARCH_REQUIRED) - ERRO ━━━\n{e}"
                
                # 2. READ_FILE
                elif "[READ_FILE:" in response_text:
                    start_idx = response_text.find("[READ_FILE:") + len("[READ_FILE:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        path_solicitado = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                        path_solicitado = self.fuzzy_matcher.find_closest_path(path_solicitado)
                        log.info(f"[pipeline] Active Loop - READ_FILE: '{path_solicitado}'")
                        has_tool_call = True
                        try:
                            allowed, reason = await self.check_action_safety(
                                action_type=ActionType.READ_FILE,
                                goal_name="read_file_tool",
                                action_details={"path": path_solicitado}
                            )
                            if allowed and self._is_sensitive_path(path_solicitado):
                                allowed = False
                                reason = "Leitura de arquivo sensível (segredos/credenciais) bloqueada."
                            if allowed:
                                from src.core.execution.registry import execute_read_file
                                content = await execute_read_file(path_solicitado)
                                tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (READ_FILE: {path_solicitado}) ━━━\n{content}"
                            else:
                                tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (READ_FILE: {path_solicitado}) - AÇÃO BLOQUEADA ━━━\n{reason}"
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (READ_FILE: {path_solicitado}) - ERRO ━━━\n{e}"
                
                # 3. WRITE_FILE
                elif "[WRITE_FILE:" in response_text:
                    start_idx = response_text.find("[WRITE_FILE:") + len("[WRITE_FILE:")
                    end_path_idx = response_text.find("]", start_idx)
                    if end_path_idx != -1:
                        path_solicitado = response_text[start_idx:end_path_idx].strip().strip('"').strip("'")
                        path_solicitado = self.fuzzy_matcher.find_closest_path(path_solicitado)
                        content_start = end_path_idx + 1
                        content_end = response_text.find("[/WRITE_FILE]", content_start)
                        if content_end != -1:
                            conteudo = response_text[content_start:content_end].strip()
                            log.info(f"[pipeline] Active Loop - WRITE_FILE: '{path_solicitado}' ({len(conteudo)} chars)")
                            has_tool_call = True
                            try:
                                allowed, reason = await self.check_action_safety(
                                    action_type=ActionType.WRITE_FILE,
                                    goal_name="write_file_tool",
                                    action_details={"path": path_solicitado}
                                )
                                if allowed:
                                    from src.core.execution.registry import execute_write_file
                                    res = await execute_write_file(path_solicitado, conteudo)
                                    tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (WRITE_FILE: {path_solicitado}) ━━━\n{res}"
                                else:
                                    tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (WRITE_FILE: {path_solicitado}) - AÇÃO BLOQUEADA ━━━\n{reason}"
                            except Exception as e:
                                tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (WRITE_FILE: {path_solicitado}) - ERRO ━━━\n{e}"
                
                # 4. PATCH_FILE
                elif "[PATCH_FILE:" in response_text:
                    start_idx = response_text.find("[PATCH_FILE:") + len("[PATCH_FILE:")
                    end_path_idx = response_text.find("]", start_idx)
                    if end_path_idx != -1:
                        path_solicitado = response_text[start_idx:end_path_idx].strip().strip('"').strip("'")
                        path_solicitado = self.fuzzy_matcher.find_closest_path(path_solicitado)
                        log.info(f"[pipeline] Active Loop - PATCH_FILE: '{path_solicitado}'")
                        has_tool_call = True
                        try:
                            allowed, reason = await self.check_action_safety(
                                action_type=ActionType.WRITE_FILE,
                                goal_name="patch_file_tool",
                                action_details={"path": path_solicitado}
                            )
                            if allowed:
                                from src.core.execution.registry import execute_patch_file
                                res = await execute_patch_file(response_text, path_solicitado)
                                tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (PATCH_FILE: {path_solicitado}) ━━━\n{res}"
                            else:
                                tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (PATCH_FILE: {path_solicitado}) - AÇÃO BLOQUEADA ━━━\n{reason}"
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (PATCH_FILE: {path_solicitado}) - ERRO ━━━\n{e}"
                
                # 5. TERMINAL_EXECUTE
                elif "[TERMINAL_EXECUTE:" in response_text:
                    start_idx = response_text.find("[TERMINAL_EXECUTE:") + len("[TERMINAL_EXECUTE:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        cmd_solicitado = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                        log.info(f"[pipeline] Active Loop - TERMINAL_EXECUTE: '{cmd_solicitado}'")
                        has_tool_call = True
                        try:
                            allowed, reason = await self.check_action_safety(
                                action_type=ActionType.EXECUTE_COMMAND,
                                goal_name="terminal_execute_tool",
                                action_details={"command": cmd_solicitado}
                            )
                            if allowed:
                                from src.core.execution.registry import execute_terminal_command
                                out = await execute_terminal_command(cmd_solicitado)
                                tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (TERMINAL_EXECUTE) ━━━\n{out}"
                            else:
                                tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (TERMINAL_EXECUTE) - AÇÃO BLOQUEADA ━━━\n{reason}"
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (TERMINAL_EXECUTE) - ERRO ━━━\n{e}"
                
                # 6. SEARCH_SESSION
                elif "[SEARCH_SESSION:" in response_text:
                    start_idx = response_text.find("[SEARCH_SESSION:") + len("[SEARCH_SESSION:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        query_solicitada = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                        log.info(f"[pipeline] Active Loop - SEARCH_SESSION: '{query_solicitada}'")
                        has_tool_call = True
                        try:
                            results = await self.session_store.search_session_turns(
                                query=query_solicitada,
                                session_id=session_id
                            )
                            if results:
                                formatted = "\n".join([
                                    f"- [{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['timestamp']))}] {r['role']}: {r['content']}"
                                    for r in results
                                ])
                                tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (SEARCH_SESSION: {query_solicitada}) ━━━\n{formatted}"
                            else:
                                tool_output = f"\n\n━━━ RETORNO DA FERRAMENTA (SEARCH_SESSION: {query_solicitada}) ━━━\nNenhuma mensagem correspondente encontrada no histórico da sessão."
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DA SEARCH_SESSION: {query_solicitada}) - ERRO ━━━\n{e}"
                
                # 7. DELEGATE_TASK
                elif "[DELEGATE_TASK:" in response_text:
                    import re
                    goals = re.findall(r"\[DELEGATE_TASK:\s*(.*?)\]", response_text)
                    if goals:
                        goals = [g.strip().strip('"').strip("'") for g in goals]
                        log.info(f"[pipeline] Active Loop - DELEGATE_TASK: detectadas {len(goals)} tarefas: {goals}")
                        has_tool_call = True
                        try:
                            results = await self.subagent_dispatcher.dispatch_parallel_goals(goals, session_id=session_id)
                            formatted = ""
                            for i, (goal, res) in enumerate(zip(goals, results), 1):
                                formatted += f"\n\n━━━ SUBAGENTE #{i} ({goal}) ━━━\n{res}"
                            tool_output = f"\n\n━━━ RETORNO DA DELEGAÇÃO DE TAREFAS ━━━{formatted}"
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DA DELEGAÇÃO - ERRO ━━━\n{e}"
                
                # 8. BROWSER_OPEN
                elif "[BROWSER_OPEN:" in response_text:
                    start_idx = response_text.find("[BROWSER_OPEN:") + len("[BROWSER_OPEN:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        url = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                        log.info(f"[pipeline] Active Loop - BROWSER_OPEN: '{url}'")
                        has_tool_call = True
                        try:
                            allowed, reason = await self.check_action_safety(
                                action_type=ActionType.EXECUTE_COMMAND,
                                goal_name="browser_open",
                                action_details={"url": url}
                            )
                            if allowed:
                                tool_output = await self.agent_browser.navigate(url)
                            else:
                                tool_output = f"\n\n━━━ RETORNO DO BROWSER (OPEN) - AÇÃO BLOQUEADA ━━━\n{reason}"
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DO BROWSER (OPEN) - ERRO ━━━\n{e}"

                # 9. BROWSER_CLICK
                elif "[BROWSER_CLICK:" in response_text:
                    start_idx = response_text.find("[BROWSER_CLICK:") + len("[BROWSER_CLICK:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        selector = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                        log.info(f"[pipeline] Active Loop - BROWSER_CLICK: '{selector}'")
                        has_tool_call = True
                        try:
                            tool_output = await self.agent_browser.click(selector)
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DO BROWSER (CLICK) - ERRO ━━━\n{e}"

                # 10. BROWSER_FILL
                elif "[BROWSER_FILL:" in response_text:
                    start_idx = response_text.find("[BROWSER_FILL:") + len("[BROWSER_FILL:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        parts = response_text[start_idx:end_idx].split("|", 1)
                        selector = parts[0].strip().strip('"').strip("'")
                        value = parts[1].strip().strip('"').strip("'") if len(parts) > 1 else ""
                        log.info(f"[pipeline] Active Loop - BROWSER_FILL: selector='{selector}', value='{value}'")
                        has_tool_call = True
                        try:
                            tool_output = await self.agent_browser.fill(selector, value)
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DO BROWSER (FILL) - ERRO ━━━\n{e}"

                # 11. BROWSER_SNAPSHOT
                elif "[BROWSER_SNAPSHOT]" in response_text:
                    log.info("[pipeline] Active Loop - BROWSER_SNAPSHOT")
                    has_tool_call = True
                    try:
                        tool_output = await self.agent_browser.get_accessibility_tree()
                    except Exception as e:
                        tool_output = f"\n\n━━━ RETORNO DO BROWSER (SNAPSHOT) - ERRO ━━━\n{e}"

                # 12. X_SEARCH
                elif "[X_SEARCH:" in response_text:
                    start_idx = response_text.find("[X_SEARCH:") + len("[X_SEARCH:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        query = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                        log.info(f"[pipeline] Active Loop - X_SEARCH: '{query}'")
                        has_tool_call = True
                        try:
                            tool_output = await self.x_searcher.search(query)
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DO X_SEARCH - ERRO ━━━\n{e}"

                # 13. TTS
                elif "[TTS:" in response_text:
                    start_idx = response_text.find("[TTS:") + len("[TTS:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        text_to_speak = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                        log.info(f"[pipeline] Active Loop - TTS: '{text_to_speak}'")
                        has_tool_call = True
                        try:
                            res_path = await self.tts_generator.generate_speech(text_to_speak)
                            tool_output = f"\n\n━━━ RETORNO DO TTS ━━━\nÁudio gerado e salvo em: {res_path}"
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DO TTS - ERRO ━━━\n{e}"

                # 14. GENERATE_IMAGE
                elif "[GENERATE_IMAGE:" in response_text:
                    start_idx = response_text.find("[GENERATE_IMAGE:") + len("[GENERATE_IMAGE:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        prompt_img = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                        log.info(f"[pipeline] Active Loop - GENERATE_IMAGE: '{prompt_img}'")
                        has_tool_call = True
                        try:
                            allowed, reason = await self.check_action_safety(
                                action_type=ActionType.WRITE_FILE,
                                goal_name="generate_image",
                                action_details={"prompt": prompt_img}
                            )
                            if allowed:
                                res_path = await self.image_generator.generate(prompt_img)
                                tool_output = f"\n\n━━━ RETORNO DO GENERATE_IMAGE ━━━\nImagem gerada e salva em: {res_path}"
                            else:
                                tool_output = f"\n\n━━━ RETORNO DO GENERATE_IMAGE - AÇÃO BLOQUEADA ━━━\n{reason}"
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DO GENERATE_IMAGE - ERRO ━━━\n{e}"

                # 15. SEND_EMAIL
                elif "[SEND_EMAIL:" in response_text:
                    start_idx = response_text.find("[SEND_EMAIL:") + len("[SEND_EMAIL:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        parts = response_text[start_idx:end_idx].split("|", 2)
                        to = parts[0].strip().strip('"').strip("'")
                        subject = parts[1].strip().strip('"').strip("'") if len(parts) > 1 else "Sem Assunto"
                        body = parts[2].strip().strip('"').strip("'") if len(parts) > 2 else ""
                        log.info(f"[pipeline] Active Loop - SEND_EMAIL: to='{to}', subject='{subject}'")
                        has_tool_call = True
                        try:
                            allowed, reason = await self.check_action_safety(
                                action_type=ActionType.EXECUTE_COMMAND,
                                goal_name="send_email",
                                action_details={"to": to, "subject": subject}
                            )
                            if allowed:
                                tool_output = await self.ms_graph.send_email(to, subject, body)
                            else:
                                tool_output = f"\n\n━━━ RETORNO DO SEND_EMAIL - AÇÃO BLOQUEADA ━━━\n{reason}"
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DO SEND_EMAIL - ERRO ━━━\n{e}"

                # 16. KANBAN_ADD
                elif "[KANBAN_ADD:" in response_text:
                    start_idx = response_text.find("[KANBAN_ADD:") + len("[KANBAN_ADD:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        title = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                        log.info(f"[pipeline] Active Loop - KANBAN_ADD: '{title}'")
                        has_tool_call = True
                        try:
                            tool_output = self.kanban_board.add_task(title)
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DO KANBAN_ADD - ERRO ━━━\n{e}"

                # 17. KANBAN_MOVE
                elif "[KANBAN_MOVE:" in response_text:
                    start_idx = response_text.find("[KANBAN_MOVE:") + len("[KANBAN_MOVE:")
                    end_idx = response_text.find("]", start_idx)
                    if end_idx != -1:
                        parts = response_text[start_idx:end_idx].split("|", 1)
                        task_id = parts[0].strip().strip('"').strip("'")
                        coluna = parts[1].strip().strip('"').strip("'") if len(parts) > 1 else "backlog"
                        log.info(f"[pipeline] Active Loop - KANBAN_MOVE: task_id='{task_id}', coluna='{coluna}'")
                        has_tool_call = True
                        try:
                            tool_output = self.kanban_board.move_task(task_id, coluna)
                        except Exception as e:
                            tool_output = f"\n\n━━━ RETORNO DO KANBAN_MOVE - ERRO ━━━\n{e}"

                # 18. KANBAN_LIST
                elif "[KANBAN_LIST]" in response_text:
                    log.info("[pipeline] Active Loop - KANBAN_LIST")
                    has_tool_call = True
                    try:
                        tool_output = self.kanban_board.list_tasks()
                    except Exception as e:
                        tool_output = f"\n\n━━━ RETORNO DO KANBAN_LIST - ERRO ━━━\n{e}"

                # 19. OSV_CHECK
                elif "[OSV_CHECK]" in response_text:
                    log.info("[pipeline] Active Loop - OSV_CHECK")
                    has_tool_call = True
                    try:
                        tool_output = await self.osv_scanner.scan_vulnerabilities()
                    except Exception as e:
                        tool_output = f"\n\n━━━ RETORNO DO OSV_CHECK - ERRO ━━━\n{e}"

                if has_tool_call:
                    log.info(f"[pipeline] Active Loop {active_loop + 1}/{max_active_loops} completado. Atualizando contextos.")
                    if not ctx.vault_context:
                        ctx.vault_context = ""
                    ctx.vault_context += tool_output
                    ctx.vault_context += "\n(Nota: Use os dados retornados pela ferramenta acima para concluir sua resposta. Se precisar realizar mais ações, emita a tag correspondente.)"
                    ctx.memory_prompt += tool_output
                    active_loop += 1
                    continue

            # Se não exigiu busca ou atingiu limite de iterações, sai do loop
            break

        # ── 4. Monta resultado ────────────────────────────────
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        result = PipelineResult(
            response=phase_result.response,
            depth=decision.depth,
            routing_reason=decision.reason,
            arbitrage=phase_result.arbitrage,
            verdict=phase_result.verdict,
            total_cost_usd=phase_result.cost_usd,
            total_latency_ms=elapsed_ms,
            llm_calls=phase_result.llm_calls,
            image_bytes=phase_result.image_bytes,
            facts_used=facts_used,
            decision_id=decision_id,
        )

        # ── Integridade: registra métricas (Sprint 12) ────────
        if result.arbitrage:
            self.integrity.record_arbitrage(
                has_conflicts=result.arbitrage.has_conflicts,
                cost=result.arbitrage.total_cost_usd
            )

        # ── RL: registra sinal técnico ────────────────────────
        self.reward_collector.record_technical(
            decision_id=decision_id,
            success=True,
            cost_usd=phase_result.cost_usd,
            latency_ms=elapsed_ms,
        )

        # ── Sprint 2: update bandit com reward técnico imediato ───────
        # O reward final (com feedback do Victor) chega depois via observe_follow_up.
        # Aqui fazemos um update preliminar com sinal técnico para o bandit
        # começar a aprender mesmo antes do feedback comportamental.
        try:
            tech_event = self.reward_collector._open_events.get(decision_id)
            if tech_event:
                self.cascade_bandit.update(
                    decision_id=decision_id,
                    reward=tech_event.reward_technical,
                )
        except Exception as e:
            log.debug(f"[bandit] Erro no update técnico (ignorado): {e}")

        # Acumula métricas de uso de memória
        self._memory_stats["responses"] += 1
        if facts_used > 0:
            self._memory_stats["with_facts"] += 1
        self._memory_stats["total_facts_injected"] += facts_used

        # ── 5. Knowledge Extraction — RESOLVED T-11 ───────────
        # Era síncrono no caminho crítico (~500ms LLM call). Movido para
        # background: _post_process já faz extractor.extract() como fallback
        # quando result._extraction está vazio. Resultado: user vê a resposta
        # imediatamente; a extração acontece em paralelo.
        self._spawn_background(self._post_process(session_id, user_input, result))

        return result

        return result

    # ─────────────────────────────────────────────────────────
    # RL FEEDBACK
    # ─────────────────────────────────────────────────────────

    def observe_follow_up(
        self,
        decision_id: str,
        message: str,
        response_delay_seconds: float = 0.0,
    ) -> None:
        """
        Registra resposta do Victor após o bot ter dado output.
        Chamado pelo bot.py sempre que Victor envia uma nova mensagem.

        Args:
            decision_id: ID retornado no PipelineResult.decision_id
            message: Texto da mensagem do Victor
            response_delay_seconds: Segundos desde que o bot respondeu
        """
        self.reward_collector.observe_user_message(
            decision_id=decision_id,
            message=message,
            response_delay_seconds=response_delay_seconds,
        )

        # Sprint 2: update do bandit com reward total (técnico + comportamental)
        try:
            event = self.reward_collector._open_events.get(decision_id)
            if event:
                self.cascade_bandit.update(
                    decision_id=decision_id,
                    reward=event.reward_total,
                )
                # Phase 2: Check if bandit should auto-activate
                self.check_bandit_readiness()
        except Exception:
            pass  # bandit nunca quebra o fluxo

    def get_rl_stats(self) -> dict:
        """Estatísticas do sistema de RL — para /perf ou debug."""
        return self.reward_collector.get_stats()

    def get_bandit_stats(self) -> str:
        """Formata stats do LinUCB Bandit para Telegram."""
        return self.cascade_bandit.format_stats()

    def get_integrity_report(self) -> str:
        """Retorna relatório de integridade formatado para Telegram."""
        return self.integrity.format_for_telegram()

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

    def check_bandit_readiness(self) -> bool:
        """
        Periodically check if bandit should transition to ACTIVE mode.
        Called from observe_follow_up to monitor bandit stats.
        Returns True if transition occurred.
        """
        if self.cascade_bandit.try_activate():
            return True
        return False

    def get_sprint11_report(self) -> str:
        """Retorna relatório de otimizações Sprint 11 formatado para Telegram"""
        return self.sprint11_tracker.format_for_telegram()

    async def check_action_safety(
        self,
        action_type: ActionType,
        goal_name: str,
        current_tier: AutonomyTier = AutonomyTier.L1_LOGGED,
        action_details: dict | None = None,
    ) -> tuple[bool, str]:
        """
        Verifica se uma ação é permitida pela safety policy.

        Returns: (allowed, reason)
        """
        allowed, reason = await self.safety_layer.check_action(
            action_type, goal_name, current_tier, action_details
        )
        return allowed, reason

    @staticmethod
    def _is_sensitive_path(path: str) -> bool:
        """Bloqueia leitura de arquivos com segredos/credenciais (anti-exfiltração no active loop)."""
        if not path:
            return False
        p = str(path).lower().replace("\\", "/")
        name = p.rsplit("/", 1)[-1]
        sensitive_names = {
            ".env", "credentials", "credentials.json", "secrets.json",
            "id_rsa", "id_ed25519", ".npmrc", ".pypirc", ".netrc",
        }
        if name in sensitive_names:
            return True
        sensitive_markers = (
            ".env", "secret", "credential", "api_key", "apikey", "id_rsa",
            ".pem", ".key", "token", "/.ssh/", "/.aws/", "/.gnupg/",
        )
        return any(m in p for m in sensitive_markers)

    def get_safety_policy(self) -> dict:
        """Exporta a política de segurança atual em formato estruturado"""
        return self.safety_layer.export_policy()

    def get_safety_audit_log(self, limit: int = 100) -> list[dict]:
        """Retorna log de auditoria de ações de segurança"""
        return self.safety_layer.get_audit_log(limit)

    def configure_safety_policy(self):
        """Retorna a política para configuração pelo bot/CLI"""
        return self.safety_layer.policy

    def get_performance_dashboard(self) -> dict:
        """Retorna dashboard de performance agregado"""
        all_stats = self.profiler.get_all_stats()
        worst = self.profiler.get_worst_offenders(limit=10)

        dashboard = {
            "timestamp": time.time(),
            "goals": {},
            "worst_offenders": [],
            "system_health": {},
        }

        # Agregações por goal
        for goal_id, goal_metrics in all_stats.items():
            dashboard["goals"][goal_id] = goal_metrics.to_dict()

        # Top 10 worst (latência)
        for metric in worst[:10]:
            dashboard["worst_offenders"].append(
                {
                    "goal_id": metric.goal_id,
                    "phase": metric.phase_name,
                    "latency_ms": f"{metric.latency_ms:.0f}",
                    "cost_usd": f"${metric.cost_usd:.4f}",
                    "provider": metric.provider,
                    "timestamp": metric.timestamp.isoformat(),
                }
            )

        # Health metrics
        if all_stats:
            total_goals = len(all_stats)
            total_success = sum(1 for g in all_stats.values() if g.success_rate > 80)
            dashboard["system_health"] = {
                "total_goals": total_goals,
                "healthy_goals": total_success,
                "health_pct": f"{(total_success / total_goals * 100):.1f}%"
                if total_goals > 0
                else "0%",
                "total_cost_usd": f"${sum(g.total_cost_usd for g in all_stats.values()):.2f}",
                "avg_latency_ms": f"{(sum(g.avg_latency_ms for g in all_stats.values()) / total_goals):.0f}"
                if total_goals > 0
                else "0",
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
            log.info(
                f"[pipeline] Aguardando {len(self._background_tasks)} background tasks..."
            )
            done, pending = await asyncio.wait(self._background_tasks, timeout=10.0)
            if done:
                log.info(f"[pipeline] {len(done)} background tasks completadas")
            if pending:
                log.warning(
                    f"[pipeline] {len(pending)} background tasks ainda pendentes após timeout, cancelando..."
                )
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

        # Fecha agent browser (Playwright)
        if hasattr(self, "agent_browser"):
            try:
                await self.agent_browser.close()
            except Exception as e:
                log.error(f"[pipeline] Erro ao fechar agent browser: {e}", exc_info=True)

        log.info("[pipeline] Shutdown gracioso completo")

    # ─────────────────────────────────────────────────────────
    # PRIVATE
    # ─────────────────────────────────────────────────────────

    async def _build_memory_context(self, user_input: str) -> tuple[str, int]:
        """Constrói contexto de memória usando o 4-Layer Stack.

        L0: Identity (constante)
        L1: Essential (top N fatos por score)
        L2: On-Demand (busca semântica híbrida BM25+Vector)
        L3: Search (fallback textual se semântica falhar)

        Retorna (memory_prompt, facts_used).
        """
        # L1: Essential — todos os fatos, priorizados por score
        facts = await self.memory.get_facts(min_confidence=0.3, limit=50)
        scored = [(score_fact(f), f) for f in facts]
        scored.sort(key=lambda x: x[0], reverse=True)
        essential = [f for _, f in scored[:10]]
        facts_used = len(essential)

        # L2: On-Demand — busca semântica híbrida (BM25 + Vector)
        search_results = []
        if self.semantic_search and user_input:
            search_results = await self.semantic_search.find_similar_facts(
                user_input, top_k=5, min_similarity=0.35
            )
            # Deduplica contra L1
            seen = {f.get("fact", "") for f in essential}
            search_results = [
                sr for sr in search_results if sr.get("fact", "") not in seen
            ]
            facts_used += len(search_results)

        # L3: Fallback textual se semântica não encontrou nada
        if not search_results and user_input:
            relevant = await self.memory.search_facts(user_input, limit=5)
            seen_ids = {f.get("id") for f in essential}
            search_results = [f for f in relevant if f.get("id", -1) not in seen_ids]
            facts_used += len(search_results)

        # Auditoria Temporal (Verificação de fatos obsoletos)
        audit_context = await self.memory.get_verification_context()

        # Episódios recentes (continuidade conversacional)
        episodes = await self.memory.get_recent_episodes(limit=5)

        memory_prompt = format_4layer_context(
            essential_facts=essential,
            on_demand_facts=search_results if search_results else None,
            episodes=episodes if episodes else None,
        )

        if audit_context:
            memory_prompt += f"\n\n{audit_context}"

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
                await self.session.add_turn(
                    session_id, "assistant", result.response[:2000]
                )
                return

            # Registra resposta na sessão
            await self.session.add_turn(session_id, "assistant", result.response[:2000])

            # Extrai fatos e relacionamentos estruturados (Knowledge Graph)
            extraction = result._extraction or await self.extractor.extract(
                user_input, result.response
            )
            facts = extraction.get("facts", [])
            entities = extraction.get("entities", [])
            triples = extraction.get("triples", [])
            summary = extraction.get("summary", "")

            # Salva Entidades
            for ent in entities:
                try:
                    await self.memory.add_entity(
                        name=ent["name"],
                        entity_type=ent.get("type", "unknown"),
                        properties=ent.get("props"),
                    )
                except Exception:
                    pass

            # Salva Triplas
            for t in triples:
                try:
                    await self.memory.add_triple(
                        subject=t["subject"],
                        predicate=t["predicate"],
                        object_=t["object"],
                        valid_from=t.get("valid_from"),
                        confidence=t.get("confidence", 1.0),
                        adapter_name=result.routing_reason[:50],
                    )
                except Exception:
                    pass

            # Salva fatos + embeddings (sem commit individual)
            for f in facts:
                fact_id = await self.memory.upsert_fact(
                    fact=f["fact"],
                    category=f.get("category", "general"),
                    confidence=f.get("confidence", 0.5),
                    source="extracted",
                    _batch=True,
                )
                # Indexa embedding do novo fato
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

            # Sincroniza Knowledge Graph com Obsidian (Fase 3)
            if self.obsidian_exporter:
                asyncio.create_task(self.obsidian_exporter.sync_all())

            # Registra latência e consolidação no Sprint 11 Tracker (Fase 4)
            self.sprint11_tracker.record_latency(result.total_latency_ms)
            commits_avoided = max(0, len(facts))  # 1 commit por fato evitado
            self.sprint11_tracker.record_batch_consolidation(
                len(facts) + 1
            )  # +1 para episódio

            # Log de consolidação: compara commits evitados com batch operations
            # Sem batch: ~7 commits (1 por fato + 1 episódio)
            # Com batch: 1 commit único
            # Economia: ~6 commits evitados * ~15ms = ~90ms latência reduzida
            log.info(
                f"[memory] ✓ Batch commit: {len(facts)} fatos + episódio consolidados "
                f"(~{commits_avoided} commits evitados, ~{commits_avoided * 15}ms latência reduzida)"
            )

            # Closed Learning Loop: autogeração de skills para tarefas complexas da fase DEEP
            if result.depth.value == "deep" and result.total_cost_usd > 0.01:
                self._spawn_background(self._self_learning_loop(session_id, user_input, result.response))

        except Exception as e:
            log.warning(f"[memory] Falha ao registrar: {e}")

    async def _self_learning_loop(
        self,
        session_id: str,
        user_input: str,
        response: str,
    ) -> None:
        """Closed Learning Loop: analisa tarefas complexas e propõe novas skills Python."""
        log.info("[pipeline] Iniciando Closed Learning Loop...")
        try:
            from src.providers.base import LLMRequest, invoke_with_fallback
            from config.models import CognitiveRole
            from src.core.utils import parse_llm_json
            from src.skills.skill_creator.coder import CodeGenerator

            prompt = (
                "Você é o analista de aprendizado autônomo do Seeker.Bot.\n"
                "Recentemente o usuário fez uma pergunta complexa e o bot gerou uma resposta detalhada.\n\n"
                f"ENTRADA DO USUÁRIO:\n{user_input}\n\n"
                f"RESPOSTA DO BOT:\n{response}\n\n"
                "Sua tarefa é avaliar se essa interação específica contém um padrão de automação complexo "
                "que deveria ser encapsulado em uma nova Skill em Python (na pasta src/skills/) para uso futuro.\n"
                "Exemplos de automações válidas: raspadores de sites específicos, geradores de relatórios específicos, "
                "cálculos matemáticos/financeiros iterativos, etc.\n"
                "Não crie skills para interações puramente informativas ou simples conversa de chat.\n\n"
                "Responda ESTRITAMENTE em formato JSON com esta estrutura:\n"
                "{\n"
                '  "deseja_criar_skill": true ou false,\n'
                '  "motivo": "Justificativa curta.",\n'
                '  "prompt_para_coder": "Um prompt muito detalhado e técnico contendo requisitos exatos para o Seeker.Bot Coder codificar e salvar essa skill na pasta src/skills/nome_da_skill/goal.py (seguindo a estrutura padrão de AutonomousGoal)."\n'
                "}"
            )

            req = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                system="Responda apenas com JSON estrito, sem blocos markdown.",
                temperature=0.0,
            )

            resp = await invoke_with_fallback(
                CognitiveRole.FAST,
                req,
                self.model_router,
                self.api_keys,
            )

            data = parse_llm_json(resp.text)
            if data.get("deseja_criar_skill"):
                log.info(f"[pipeline] Closed Learning Loop propôs criar skill. Motivo: {data.get('motivo')}")
                coder = CodeGenerator(self)
                res_coder = await coder.process_coding_request(data.get("prompt_para_coder"))
                log.info(f"[pipeline] Closed Learning Loop resultado: {res_coder}")

        except Exception as e:
            log.warning(f"[pipeline] Falha no Closed Learning Loop: {e}", exc_info=True)

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
                                exc_info=True,
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
                    log.error(f"[decay] Erro no ciclo #{iteration}: {e}", exc_info=True)
                    # Continua no próximo ciclo

        except asyncio.CancelledError:
            # Re-raise para respeitarasyncio.CancelledError como sinalizador
            raise
        except Exception as e:
            log.error(f"[decay] Task encerrada por erro fatal: {e}", exc_info=True)
            raise
