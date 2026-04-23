"""
Seeker.Bot — Reward Collector
src/core/rl/reward_collector.py

Captura sinais de feedback do Victor e do sistema para compor o
reward signal usado pelos algoritmos de RL.

Dois tipos de sinal:
  BEHAVIORAL — comportamento do Victor após uma resposta
  TECHNICAL  — métricas objetivas do sistema (custo, latência, sucesso)

Reward composto final:
  R = w_behav * R_behavioral + w_tech * R_technical

Sinais comportamentais (inferidos, não perguntamos ao Victor):
  + Resposta rápida (<30s)        → engajou, gostou
  + Follow-up no mesmo tópico    → aprofundou, valeu a pena
  + Emoji positivo (👍✅🔥)       → aprovação explícita
  + Usou o output (ação seguinte) → output foi útil
  - Resposta muito lenta (>15min) → provavelmente ignorou
  - Pediu "simplifica" / "tl;dr" → foi profundo demais
  - Pediu "explica mais"          → foi raso demais
  - Reclamou / "errado"           → erro de conteúdo
  - Comando /forget               → quer apagar da memória

Sinais técnicos:
  + Sucesso do call LLM           → +1.0
  - Custo USD                     → -cost_usd * 50
  - Latência ms                   → -latency_ms * 0.001
  - Fallback ativado              → -0.5 por fallback
  - Timeout                       → -2.0
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

log = logging.getLogger("seeker.rl.reward")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────

REWARD_DB_PATH = os.path.join(os.getcwd(), "data", "rl_rewards.jsonl")

# Weights do reward composto
W_BEHAVIORAL = 0.7
W_TECHNICAL  = 0.3

# Janela de observação comportamental (segundos)
BEHAVIORAL_WINDOW_SECONDS = 900  # 15 minutos

# Regex pra detectar sentimento negativo na mensagem do Victor
NEGATIVE_PATTERNS = re.compile(
    r"simplifica|tl[;:]?dr|muito\s+longo|muito\s+extenso|"
    r"errado|incorreto|não\s+é\s+isso|esquece|forget|"
    r"explica\s+melhor|mais\s+detalhes|não\s+entendi|"
    r"confuso|viagem|loucura",
    re.IGNORECASE,
)

POSITIVE_PATTERNS = re.compile(
    r"perfeito|exato|isso\s+mesmo|excelente|ótimo|massa|"
    r"legal|show|bom\s+trabalho|valeu|obrigado|funcionou|"
    r"deu\s+certo|top|incrível|sensacional",
    re.IGNORECASE,
)

POSITIVE_EMOJIS = {"👍", "✅", "🔥", "💯", "🎯", "😊", "🚀", "👏", "🤩"}
NEGATIVE_EMOJIS = {"👎", "❌", "😤", "🙄", "😒", "🤦"}


# ─────────────────────────────────────────────────────────────────────────────
# MODELOS
# ─────────────────────────────────────────────────────────────────────────────

class SignalSource(str, Enum):
    BEHAVIORAL  = "behavioral"   # Comportamento do Victor
    TECHNICAL   = "technical"    # Métricas do sistema
    EXPLICIT    = "explicit"     # Feedback explícito (/feedback, botão)


class RewardSign(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL  = "neutral"


@dataclass
class RewardSignal:
    """
    Sinal individual de reward. Um evento gera um ou mais sinais.

    Cada sinal tem valor normalizado em [-1, +1]:
      +1 = reward máximo
      -1 = penalidade máxima
       0 = neutro
    """
    source: SignalSource
    sign: RewardSign
    value: float          # [-1, +1]
    reason: str           # Legível para debug
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        self.value = max(-1.0, min(1.0, self.value))  # clamp


@dataclass
class RewardEvent:
    """
    Evento de aprendizado — associa uma decisão ao seu reward observado.

    Representa uma linha no dataset de treinamento:
      (decision_id, state_snapshot, action_taken, reward_total, signals)

    Salvo em JSONL para backfill e análise posterior.
    """
    decision_id: str                         # UUID da decisão
    action_taken: str                        # "reflex" | "deliberate" | "deep" | tier name
    context: str                             # Resumo textual do contexto
    signals: list[RewardSignal] = field(default_factory=list)
    reward_behavioral: float = 0.0
    reward_technical: float = 0.0
    reward_total: float = 0.0
    state_snapshot: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None       # Quando o evento foi finalizado

    @property
    def is_open(self) -> bool:
        """Evento ainda aguardando sinais comportamentais."""
        return self.closed_at is None

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    def add_signal(self, signal: RewardSignal) -> None:
        self.signals.append(signal)
        self._recompute()

    def _recompute(self) -> None:
        """Recalcula rewards agregados."""
        behavioral = [s.value for s in self.signals if s.source == SignalSource.BEHAVIORAL]
        technical  = [s.value for s in self.signals if s.source == SignalSource.TECHNICAL]
        explicit   = [s.value for s in self.signals if s.source == SignalSource.EXPLICIT]

        # Explicit feedback overrides behaviorals se presente
        if explicit:
            self.reward_behavioral = sum(explicit) / len(explicit)
        elif behavioral:
            self.reward_behavioral = sum(behavioral) / len(behavioral)
        else:
            self.reward_behavioral = 0.0

        self.reward_technical = sum(technical) / len(technical) if technical else 0.0

        self.reward_total = (
            W_BEHAVIORAL * self.reward_behavioral
            + W_TECHNICAL * self.reward_technical
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        # Converter enums pra string
        for sig in d["signals"]:
            sig["source"] = sig["source"].value if isinstance(sig["source"], SignalSource) else sig["source"]
            sig["sign"]   = sig["sign"].value   if isinstance(sig["sign"],   RewardSign)   else sig["sign"]
        return d

    def close(self) -> None:
        """Fecha o evento, impedindo novos sinais comportamentais."""
        self.closed_at = time.time()
        log.debug(
            f"[reward] Event {self.decision_id[:8]} fechado | "
            f"R={self.reward_total:+.2f} "
            f"(behav={self.reward_behavioral:+.2f}, tech={self.reward_technical:+.2f})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# COLLECTOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class RewardCollector:
    """
    Coleta e agrega sinais de reward para aprendizado do bot.

    Uso:
        collector = RewardCollector()

        # Quando o bot toma uma decisão de roteamento:
        event = collector.open_event(
            decision_id="abc123",
            action_taken="deliberate",
            context="query: 'como configuro o redis?'",
            state_snapshot=state_encoder.encode(state),
        )

        # Quando recebe resultado técnico:
        collector.record_technical(
            decision_id="abc123",
            success=True,
            cost_usd=0.003,
            latency_ms=420,
            fallbacks=0,
        )

        # Quando Victor responde:
        collector.observe_user_message(
            decision_id="abc123",
            message="valeu, funcionou!",
            response_delay_seconds=25,
        )

        # Depois de BEHAVIORAL_WINDOW_SECONDS sem resposta:
        collector.close_event("abc123")

        # Para treinar:
        dataset = collector.export_dataset(days=30)
    """

    def __init__(self, db_path: str = REWARD_DB_PATH):
        self.db_path = db_path
        self._open_events: dict[str, RewardEvent] = {}
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        log.info(f"[reward] RewardCollector inicializado — db: {db_path}")

    # ── Gestão de eventos ─────────────────────────────────────────────

    def open_event(
        self,
        decision_id: str,
        action_taken: str,
        context: str = "",
        state_snapshot: dict | None = None,
    ) -> RewardEvent:
        """Abre um evento de aprendizado para uma decisão."""
        event = RewardEvent(
            decision_id=decision_id,
            action_taken=action_taken,
            context=context,
            state_snapshot=state_snapshot or {},
        )
        self._open_events[decision_id] = event
        log.debug(f"[reward] Evento aberto: {decision_id[:8]} action={action_taken}")
        return event

    def close_event(self, decision_id: str) -> Optional[RewardEvent]:
        """Fecha evento, persiste em disco e remove do cache."""
        event = self._open_events.pop(decision_id, None)
        if not event:
            return None
        event.close()
        self._persist(event)
        return event

    def close_stale_events(self) -> int:
        """Fecha eventos mais velhos que BEHAVIORAL_WINDOW_SECONDS. Retorna contagem."""
        stale = [
            eid for eid, e in self._open_events.items()
            if e.age_seconds > BEHAVIORAL_WINDOW_SECONDS
        ]
        for eid in stale:
            self.close_event(eid)
        if stale:
            log.info(f"[reward] {len(stale)} eventos stale fechados")
        return len(stale)

    # ── Sinais técnicos ───────────────────────────────────────────────

    def record_technical(
        self,
        decision_id: str,
        success: bool,
        cost_usd: float = 0.0,
        latency_ms: float = 0.0,
        fallbacks: int = 0,
        timed_out: bool = False,
    ) -> None:
        """
        Registra resultado técnico de um call LLM.
        Pode ser chamado mesmo para eventos já fechados (persiste diretamente).
        """
        event = self._open_events.get(decision_id)
        if not event:
            return

        signals = []

        # Sucesso/Falha
        signals.append(RewardSignal(
            source=SignalSource.TECHNICAL,
            sign=RewardSign.POSITIVE if success else RewardSign.NEGATIVE,
            value=1.0 if success else -1.0,
            reason=f"LLM call {'succeeded' if success else 'failed'}",
        ))

        # Custo (penalidade proporcional — $0.01 = -0.5)
        if cost_usd > 0:
            cost_penalty = min(1.0, cost_usd * 50)
            signals.append(RewardSignal(
                source=SignalSource.TECHNICAL,
                sign=RewardSign.NEGATIVE,
                value=-cost_penalty,
                reason=f"cost ${cost_usd:.4f}",
            ))

        # Latência (penalidade leve — 1000ms = -0.1)
        if latency_ms > 0:
            latency_penalty = min(0.5, latency_ms * 0.0001)
            signals.append(RewardSignal(
                source=SignalSource.TECHNICAL,
                sign=RewardSign.NEGATIVE,
                value=-latency_penalty,
                reason=f"latency {latency_ms:.0f}ms",
            ))

        # Fallbacks acionados
        if fallbacks > 0:
            signals.append(RewardSignal(
                source=SignalSource.TECHNICAL,
                sign=RewardSign.NEGATIVE,
                value=min(1.0, -0.3 * fallbacks),
                reason=f"{fallbacks} fallback(s) triggered",
            ))

        # Timeout
        if timed_out:
            signals.append(RewardSignal(
                source=SignalSource.TECHNICAL,
                sign=RewardSign.NEGATIVE,
                value=-1.0,
                reason="timeout",
            ))

        for sig in signals:
            event.add_signal(sig)

        log.debug(
            f"[reward] Técnico {decision_id[:8]}: "
            f"ok={success} cost=${cost_usd:.4f} lat={latency_ms:.0f}ms "
            f"fb={fallbacks} R_tech={event.reward_technical:+.2f}"
        )

    # ── Sinais comportamentais ─────────────────────────────────────────

    def observe_user_message(
        self,
        decision_id: str,
        message: str,
        response_delay_seconds: float = 0.0,
    ) -> None:
        """
        Analisa mensagem do Victor para extrair sinal comportamental.

        Chamado sempre que Victor responde após o bot ter dado output.
        """
        event = self._open_events.get(decision_id)
        if not event:
            return

        signals = []

        # ── Delay de resposta ──────────────────────────────────────────
        if response_delay_seconds > 0:
            if response_delay_seconds < 30:
                signals.append(RewardSignal(
                    source=SignalSource.BEHAVIORAL,
                    sign=RewardSign.POSITIVE,
                    value=+0.4,
                    reason=f"resposta rápida ({response_delay_seconds:.0f}s)",
                ))
            elif response_delay_seconds > 600:
                signals.append(RewardSignal(
                    source=SignalSource.BEHAVIORAL,
                    sign=RewardSign.NEGATIVE,
                    value=-0.3,
                    reason=f"resposta lenta ({response_delay_seconds:.0f}s) — provavelmente ignorou",
                ))

        # ── Conteúdo da mensagem ───────────────────────────────────────
        text = message.strip()

        # Emojis positivos
        emojis_found = set(text) & POSITIVE_EMOJIS
        if emojis_found:
            signals.append(RewardSignal(
                source=SignalSource.BEHAVIORAL,
                sign=RewardSign.POSITIVE,
                value=+0.7,
                reason=f"emoji positivo: {' '.join(emojis_found)}",
            ))

        # Emojis negativos
        emojis_found = set(text) & NEGATIVE_EMOJIS
        if emojis_found:
            signals.append(RewardSignal(
                source=SignalSource.BEHAVIORAL,
                sign=RewardSign.NEGATIVE,
                value=-0.7,
                reason=f"emoji negativo: {' '.join(emojis_found)}",
            ))

        # Palavras positivas
        if POSITIVE_PATTERNS.search(text):
            match = POSITIVE_PATTERNS.search(text).group()
            signals.append(RewardSignal(
                source=SignalSource.BEHAVIORAL,
                sign=RewardSign.POSITIVE,
                value=+0.6,
                reason=f"feedback positivo: '{match}'",
            ))

        # Palavras negativas
        if NEGATIVE_PATTERNS.search(text):
            match = NEGATIVE_PATTERNS.search(text).group()
            signals.append(RewardSignal(
                source=SignalSource.BEHAVIORAL,
                sign=RewardSign.NEGATIVE,
                value=-0.8,
                reason=f"feedback negativo: '{match}'",
            ))

        for sig in signals:
            event.add_signal(sig)

        if signals:
            log.info(
                f"[reward] Comportamental {decision_id[:8]}: "
                f"{len(signals)} sinal(is) | R_behav={event.reward_behavioral:+.2f}"
            )

    def record_explicit_feedback(
        self,
        decision_id: str,
        value: float,
        reason: str = "feedback explícito",
    ) -> None:
        """Feedback explícito via botão Telegram ou /feedback command."""
        event = self._open_events.get(decision_id)
        if not event:
            return
        event.add_signal(RewardSignal(
            source=SignalSource.EXPLICIT,
            sign=RewardSign.POSITIVE if value > 0 else RewardSign.NEGATIVE,
            value=value,
            reason=reason,
        ))
        log.info(f"[reward] Explícito {decision_id[:8]}: value={value:+.2f} ({reason})")

    # ── Persistência & Export ─────────────────────────────────────────

    def _persist(self, event: RewardEvent) -> None:
        """Salva evento em JSONL (append-only log)."""
        try:
            with open(self.db_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            log.error(f"[reward] Falha ao persistir evento {event.decision_id[:8]}: {e}")

    def export_dataset(self, days: int = 30) -> list[dict]:
        """
        Exporta dataset de treinamento para os últimos N dias.

        Returns:
            Lista de dicts com campos:
              state_snapshot, action_taken, reward_total, reward_behavioral,
              reward_technical, signals_count, context, timestamp
        """
        cutoff = time.time() - (days * 86400)
        dataset = []

        if not os.path.exists(self.db_path):
            log.warning(f"[reward] Dataset não encontrado: {self.db_path}")
            return dataset

        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("created_at", 0) >= cutoff:
                            dataset.append(record)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.error(f"[reward] Falha ao exportar dataset: {e}")

        log.info(f"[reward] Dataset exportado: {len(dataset)} eventos dos últimos {days} dias")
        return dataset

    def get_stats(self) -> dict:
        """Estatísticas rápidas do reward collector."""
        dataset = self.export_dataset(days=30)
        if not dataset:
            return {"total_events": 0, "open_events": len(self._open_events)}

        rewards = [r["reward_total"] for r in dataset]
        actions = {}
        for r in dataset:
            a = r["action_taken"]
            if a not in actions:
                actions[a] = {"count": 0, "reward_sum": 0.0}
            actions[a]["count"] += 1
            actions[a]["reward_sum"] += r["reward_total"]

        return {
            "total_events": len(dataset),
            "open_events": len(self._open_events),
            "avg_reward": sum(rewards) / len(rewards),
            "min_reward": min(rewards),
            "max_reward": max(rewards),
            "by_action": {
                a: {
                    "count": v["count"],
                    "avg_reward": v["reward_sum"] / v["count"],
                }
                for a, v in actions.items()
            },
        }
