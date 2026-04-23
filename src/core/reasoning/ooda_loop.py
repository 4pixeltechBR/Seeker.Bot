"""
Seeker.Bot — OODA Loop (Observe-Orient-Decide-Act)
src/core/reasoning/ooda_loop.py

Implementa loop formal de raciocínio baseado em Boyd's OODA (Observe-Orient-Decide-Act).
Integra com IntentCard para autonomy tier aware decision-making.

Benefícios:
- Raciocínio estruturado com ciclos explícitos
- Integração com IntentCard para segurança
- Verificação formal antes de ação (pre-commit hooks)
- Auditoria completa do ciclo de decisão
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Any, Callable

log = logging.getLogger("seeker.reasoning.ooda")


class DecisionPhase(Enum):
    """Fases do ciclo OODA."""

    OBSERVE = auto()  # Coletar informações
    ORIENT = auto()  # Processar com modelos mentais
    DECIDE = auto()  # Escolher ação
    ACT = auto()  # Executar


class LoopResult(Enum):
    """Resultado do ciclo OODA."""

    SUCCESS = auto()  # Ciclo completado com sucesso
    BLOCKED = auto()  # Requer aprovação manual
    DEFERRED = auto()  # Adiado para próximo ciclo
    FAILED = auto()  # Erro irrecuperável


@dataclass
class ObservationData:
    """Dados coletados na fase Observe."""

    user_input: str
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    raw_signals: list[dict] = field(default_factory=list)  # Dados brutos coletados


@dataclass
class OrientationModel:
    """Modelo mental construído na fase Orient."""

    intent_card: Optional[Any] = None  # IntentCard classificação
    risk_assessment: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    alternatives: list[dict] = field(default_factory=list)  # Ações alternativas
    constraints: list[str] = field(default_factory=list)  # Limitações aplicáveis
    reasoning: str = ""


@dataclass
class Decision:
    """Decisão tomada na fase Decide."""

    action_type: str  # Ex: "web_search", "create_goal", "send_message"
    parameters: dict[str, Any] = field(default_factory=dict)
    autonomy_tier: int = 1  # 1=MANUAL, 2=REVERSIBLE, 3=AUTONOMOUS
    rationale: str = ""
    verification_required: bool = True  # Se requer pre-commit verification


@dataclass
class ActionResult:
    """Resultado da execução na fase Act."""

    success: bool
    output: Any = None
    error: Optional[str] = None
    cost: float = 0.0
    latency_ms: float = 0.0


@dataclass
class OODAIteration:
    """Uma iteração completa do loop OODA."""

    iteration_id: str
    user_input: str
    observation: Optional[ObservationData] = None
    orientation: Optional[OrientationModel] = None
    decision: Optional[Decision] = None
    action_result: Optional[ActionResult] = None
    result: LoopResult = LoopResult.DEFERRED
    total_latency_ms: float = 0.0
    timestamp_start: float = field(default_factory=time.time)
    timestamp_end: float = 0.0

    def to_log_entry(self) -> str:
        """Formata para logging estruturado."""
        phases = []
        if self.observation:
            phases.append("OBS")
        if self.orientation:
            phases.append("ORI")
        if self.decision:
            phases.append("DEC")
        if self.action_result:
            phases.append(f"ACT:{self.action_result.latency_ms:.0f}ms")

        phase_str = "→".join(phases)
        return (
            f"[OODA {self.iteration_id}] {phase_str} result={self.result.name} "
            f"total={self.total_latency_ms:.0f}ms"
        )


class OODALoop:
    """
    Executor do loop formal OODA.
    Coordena Observe → Orient → Decide → Act com integração de IntentCard.
    """

    def __init__(self):
        """Inicializa o loop OODA."""
        self.iteration_counter = 0
        self.max_iterations_per_query = 3  # Evita loops infinitos
        self.history: list[OODAIteration] = []

    def _new_iteration_id(self) -> str:
        """Gera ID único para iteração."""
        self.iteration_counter += 1
        return f"iter_{self.iteration_counter:05d}"

    async def execute(
        self,
        user_input: str,
        observe_fn: Callable,
        orient_fn: Callable,
        decide_fn: Callable,
        act_fn: Callable,
        context: Optional[dict] = None,
    ) -> OODAIteration:
        """
        Executa loop OODA completo.

        Args:
            user_input: Input do usuário
            observe_fn: async callable(user_input, context) → ObservationData
            orient_fn: async callable(observation) → OrientationModel
            decide_fn: async callable(orientation) → Decision
            act_fn: async callable(decision) → ActionResult
            context: Contexto adicional

        Returns:
            OODAIteration com resultado completo
        """
        iteration = OODAIteration(
            iteration_id=self._new_iteration_id(),
            user_input=user_input,
        )

        try:
            # OBSERVE: Coletar informações
            start = time.time()
            iteration.observation = await observe_fn(user_input, context or {})
            observe_latency = time.time() - start
            log.debug(
                f"[{iteration.iteration_id}] OBSERVE completed in {observe_latency*1000:.1f}ms"
            )

            # ORIENT: Processar com modelos mentais
            start = time.time()
            iteration.orientation = await orient_fn(iteration.observation)
            orient_latency = time.time() - start
            log.debug(
                f"[{iteration.iteration_id}] ORIENT completed in {orient_latency*1000:.1f}ms"
            )

            # Verificar se requer approval
            if (
                iteration.orientation.intent_card
                and iteration.orientation.intent_card.requires_approval()
            ):
                iteration.result = LoopResult.BLOCKED
                log.info(
                    f"[{iteration.iteration_id}] BLOCKED: requer aprovação manual "
                    f"(tier={iteration.orientation.intent_card.autonomy_tier.name})"
                )
                return self._finalize_iteration(iteration)

            # DECIDE: Escolher ação
            start = time.time()
            iteration.decision = await decide_fn(iteration.orientation)
            decide_latency = time.time() - start
            log.debug(
                f"[{iteration.iteration_id}] DECIDE completed in {decide_latency*1000:.1f}ms"
            )

            # Verificação pré-commit se necessário
            if iteration.decision.verification_required:
                if not await self._verify_decision(iteration.decision):
                    iteration.result = LoopResult.BLOCKED
                    log.warning(
                        f"[{iteration.iteration_id}] BLOCKED: verificação pré-commit falhou"
                    )
                    return self._finalize_iteration(iteration)

            # ACT: Executar ação
            start = time.time()
            iteration.action_result = await act_fn(iteration.decision)
            act_latency = time.time() - start

            if iteration.action_result.success:
                iteration.result = LoopResult.SUCCESS
                log.info(
                    f"[{iteration.iteration_id}] SUCCESS: ação executada "
                    f"em {act_latency*1000:.1f}ms"
                )
            else:
                iteration.result = LoopResult.FAILED
                log.error(
                    f"[{iteration.iteration_id}] FAILED: {iteration.action_result.error}"
                )

        except Exception as e:
            iteration.result = LoopResult.FAILED
            log.exception(f"[{iteration.iteration_id}] Erro não capturado no loop OODA")

        return self._finalize_iteration(iteration)

    async def _verify_decision(self, decision: Decision) -> bool:
        """
        Verifica decisão antes de execução (pré-commit hook).
        Implementar customização em subclasses.
        """
        # Validações básicas
        if not decision.action_type:
            log.warning("Decision verification: action_type vazio")
            return False

        if decision.autonomy_tier == 1:  # MANUAL
            # Tier 1 sempre requer aprovação explícita do usuário
            # Em contexto real, isto seria integrado com um queue de aprovação
            log.info(f"Decision requires manual approval: {decision.action_type}")
            return False

        if decision.autonomy_tier == 2:  # REVERSIBLE
            # Tier 2 é reversível, pode executar com logs
            log.debug(f"Decision tier REVERSIBLE: {decision.action_type}")
            return True

        # Tier 3 (AUTONOMOUS) executa direto
        return True

    def _finalize_iteration(self, iteration: OODAIteration) -> OODAIteration:
        """Finaliza iteração com timestamps e metadata."""
        iteration.timestamp_end = time.time()
        iteration.total_latency_ms = (
            iteration.timestamp_end - iteration.timestamp_start
        ) * 1000
        self.history.append(iteration)
        return iteration

    def get_history(self, limit: int = 20) -> list[OODAIteration]:
        """Retorna histórico das últimas N iterações."""
        return self.history[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Retorna estatísticas do loop."""
        if not self.history:
            return {
                "total_iterations": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
            }

        total = len(self.history)
        success = sum(1 for i in self.history if i.result == LoopResult.SUCCESS)
        blocked = sum(1 for i in self.history if i.result == LoopResult.BLOCKED)
        avg_latency = sum(i.total_latency_ms for i in self.history) / total if total else 0

        return {
            "total_iterations": total,
            "success_count": success,
            "blocked_count": blocked,
            "success_rate": success / total if total else 0.0,
            "avg_latency_ms": avg_latency,
            "last_10_results": [i.result.name for i in self.history[-10:]],
        }


class StreamingOODALoop(OODALoop):
    """
    Variante do OODA que suporta streaming de resultados intermediários.
    Útil para feedback em tempo real ao usuário.
    """

    def __init__(self, on_phase_complete: Optional[Callable] = None):
        """
        Inicializa loop com callback opcional.

        Args:
            on_phase_complete: async callable(phase: DecisionPhase, data: Any) → None
        """
        super().__init__()
        self.on_phase_complete = on_phase_complete

    async def execute(
        self,
        user_input: str,
        observe_fn: Callable,
        orient_fn: Callable,
        decide_fn: Callable,
        act_fn: Callable,
        context: Optional[dict] = None,
    ) -> OODAIteration:
        """Executa com callbacks após cada fase."""
        iteration = OODAIteration(
            iteration_id=self._new_iteration_id(),
            user_input=user_input,
        )

        try:
            # OBSERVE
            start = time.time()
            iteration.observation = await observe_fn(user_input, context or {})
            observe_latency = time.time() - start
            if self.on_phase_complete:
                await self.on_phase_complete(DecisionPhase.OBSERVE, iteration.observation)

            # ORIENT
            start = time.time()
            iteration.orientation = await orient_fn(iteration.observation)
            orient_latency = time.time() - start
            if self.on_phase_complete:
                await self.on_phase_complete(DecisionPhase.ORIENT, iteration.orientation)

            if (
                iteration.orientation.intent_card
                and iteration.orientation.intent_card.requires_approval()
            ):
                iteration.result = LoopResult.BLOCKED
                return self._finalize_iteration(iteration)

            # DECIDE
            start = time.time()
            iteration.decision = await decide_fn(iteration.orientation)
            decide_latency = time.time() - start
            if self.on_phase_complete:
                await self.on_phase_complete(DecisionPhase.DECIDE, iteration.decision)

            if iteration.decision.verification_required:
                if not await self._verify_decision(iteration.decision):
                    iteration.result = LoopResult.BLOCKED
                    return self._finalize_iteration(iteration)

            # ACT
            start = time.time()
            iteration.action_result = await act_fn(iteration.decision)
            act_latency = time.time() - start
            if self.on_phase_complete:
                await self.on_phase_complete(DecisionPhase.ACT, iteration.action_result)

            iteration.result = (
                LoopResult.SUCCESS if iteration.action_result.success else LoopResult.FAILED
            )

        except Exception as e:
            iteration.result = LoopResult.FAILED
            log.exception(f"[{iteration.iteration_id}] Erro em StreamingOODALoop")

        return self._finalize_iteration(iteration)
