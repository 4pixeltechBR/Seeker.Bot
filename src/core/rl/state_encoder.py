"""
Seeker.Bot — State Encoder
src/core/rl/state_encoder.py

Transforma o estado interno do bot em um vetor de features normalizadas
[0, 1] para uso pelos algoritmos de RL.

O StateEncoder é o "olho" do RL — tudo que o agente precisa saber sobre
o mundo antes de tomar uma decisão está representado aqui.

Features (26 dimensões):
  === QUERY (6) ===
    [0]  query_length_norm       — palavras / 100 (clamp 0-1)
    [1]  has_question_mark       — 0/1
    [2]  has_code_block          — 0/1 (```, def, class)
    [3]  has_url                 — 0/1
    [4]  is_command              — 0/1 (começa com /)
    [5]  sentiment_positive      — 0/1 (padrões positivos detectados)

  === TEMPO (4) ===
    [6]  hour_sin                — sin(2π * hour/24)
    [7]  hour_cos                — cos(2π * hour/24)
    [8]  weekday_sin             — sin(2π * weekday/7)
    [9]  weekday_cos             — cos(2π * weekday/7)

  === BUDGET (4) ===
    [10] budget_daily_used_pct   — gasto_hoje / limite_diário
    [11] budget_monthly_used_pct — gasto_mensal / limite_mensal
    [12] recent_cost_ma          — média móvel custo últimas 5 calls
    [13] budget_pressure         — 1 se acima de 80% do limite diário

  === PROVIDERS (4) ===
    [14] provider_tier1_health   — 0/1 (tier1 healthy)
    [15] provider_tier2_health   — 0/1
    [16] recent_failures_norm    — falhas últimas 10 calls / 10
    [17] avg_latency_norm        — latência média / 2000ms (clamp 0-1)

  === SESSÃO (4) ===
    [18] session_length_norm     — turns / 20
    [19] recent_deep_ratio       — % de chamadas DEEP nas últimas 5
    [20] last_reward_norm        — último reward (0.5 + reward/2 para [0,1])
    [21] time_since_last_call    — min(1.0, segundos / 3600)

  === INTENÇÃO (4) ===
    [22] intent_is_information   — 0/1
    [23] intent_is_analysis      — 0/1
    [24] intent_is_action        — 0/1
    [25] intent_risk_level       — risk.value / 3.0
"""

import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.intent_card import IntentCard

log = logging.getLogger("seeker.rl.state")

# ─────────────────────────────────────────────────────────────────────────────
# DIMENSÕES DO VETOR DE ESTADO
# ─────────────────────────────────────────────────────────────────────────────

STATE_DIM = 26

_RE_CODE   = re.compile(r"```|^\s*(def |class |import |from )", re.MULTILINE)
_RE_URL    = re.compile(r"https?://|www\.")
_RE_CMD    = re.compile(r"^/\w+")
_RE_POSIT  = re.compile(
    r"perfeito|ótimo|excelente|show|top|bora|blz|valeu|obrigado",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# ESTADO SEMÂNTICO (input rico, fácil de popular)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SeekerState:
    """
    Estado semântico do bot no momento de uma decisão.

    Preencha o que você tiver — campos ausentes são tratados como zero/default.
    O StateEncoder converte isso em feature vector.
    """

    # Query
    query: str = ""

    # Tempo
    timestamp: float = field(default_factory=time.time)

    # Budget
    budget_daily_used_usd: float = 0.0
    budget_daily_limit_usd: float = 10.0
    budget_monthly_used_usd: float = 0.0
    budget_monthly_limit_usd: float = 200.0
    recent_costs_usd: list[float] = field(default_factory=list)  # últimas 5 calls

    # Providers
    provider_tier1_healthy: bool = True
    provider_tier2_healthy: bool = True
    recent_failures: int = 0      # falhas nas últimas 10 calls
    avg_latency_ms: float = 500.0

    # Sessão
    session_turns: int = 0
    recent_depths: list[str] = field(default_factory=list)  # últimas 5: "reflex"|"deliberate"|"deep"
    last_reward: float = 0.0
    last_call_timestamp: Optional[float] = None

    # Intenção (IntentCard)
    intent_card: Optional["IntentCard"] = None

    def copy_with(self, **kwargs) -> "SeekerState":
        """Retorna cópia com campos sobrescritos."""
        import dataclasses
        d = dataclasses.asdict(self)
        d.pop("intent_card")  # não serializable
        d.update(kwargs)
        new = SeekerState(**{k: v for k, v in d.items() if k != "intent_card"})
        new.intent_card = kwargs.get("intent_card", self.intent_card)
        return new


# ─────────────────────────────────────────────────────────────────────────────
# ENCODER
# ─────────────────────────────────────────────────────────────────────────────

class StateEncoder:
    """
    Converte SeekerState → lista[float] de tamanho STATE_DIM (26).

    Todos os valores são normalizados em [0, 1].
    Valores faltantes (None, 0, vazio) → 0.0.

    Uso:
        encoder = StateEncoder()
        state = SeekerState(
            query="analisa se vale migrar pra K8s",
            budget_daily_used_usd=3.5,
            budget_daily_limit_usd=10.0,
            provider_tier1_healthy=True,
            session_turns=4,
        )
        features = encoder.encode(state)
        # → [0.36, 0.0, 0.0, 0.0, 0.0, 0.0, 0.49, 0.87, ...]
        assert len(features) == 26
    """

    def encode(self, state: SeekerState) -> list[float]:
        """
        Converte estado em feature vector normalizado.

        Returns:
            Lista de 26 floats em [0, 1].
        """
        v = [0.0] * STATE_DIM

        # ── [0-5] Query ───────────────────────────────────────────────
        if state.query:
            words = len(state.query.split())
            v[0] = min(1.0, words / 100.0)
            v[1] = 1.0 if "?" in state.query else 0.0
            v[2] = 1.0 if _RE_CODE.search(state.query) else 0.0
            v[3] = 1.0 if _RE_URL.search(state.query) else 0.0
            v[4] = 1.0 if _RE_CMD.match(state.query.strip()) else 0.0
            v[5] = 1.0 if _RE_POSIT.search(state.query) else 0.0

        # ── [6-9] Tempo (codificação cíclica) ─────────────────────────
        dt = time.localtime(state.timestamp)
        hour    = dt.tm_hour
        weekday = dt.tm_wday  # 0=Monday

        v[6] = (math.sin(2 * math.pi * hour / 24) + 1) / 2
        v[7] = (math.cos(2 * math.pi * hour / 24) + 1) / 2
        v[8] = (math.sin(2 * math.pi * weekday / 7) + 1) / 2
        v[9] = (math.cos(2 * math.pi * weekday / 7) + 1) / 2

        # ── [10-13] Budget ─────────────────────────────────────────────
        if state.budget_daily_limit_usd > 0:
            v[10] = min(1.0, state.budget_daily_used_usd / state.budget_daily_limit_usd)
        if state.budget_monthly_limit_usd > 0:
            v[11] = min(1.0, state.budget_monthly_used_usd / state.budget_monthly_limit_usd)

        if state.recent_costs_usd:
            avg_cost = sum(state.recent_costs_usd) / len(state.recent_costs_usd)
            v[12] = min(1.0, avg_cost / 0.05)  # normalizado por $0.05 por call

        v[13] = 1.0 if v[10] >= 0.8 else 0.0  # pressão de budget

        # ── [14-17] Providers ─────────────────────────────────────────
        v[14] = 1.0 if state.provider_tier1_healthy else 0.0
        v[15] = 1.0 if state.provider_tier2_healthy else 0.0
        v[16] = min(1.0, state.recent_failures / 10.0)
        v[17] = min(1.0, state.avg_latency_ms / 2000.0)

        # ── [18-21] Sessão ─────────────────────────────────────────────
        v[18] = min(1.0, state.session_turns / 20.0)

        if state.recent_depths:
            deep_count = sum(1 for d in state.recent_depths if d == "deep")
            v[19] = deep_count / len(state.recent_depths)

        # last_reward de [-1, +1] → [0, 1]
        v[20] = (state.last_reward + 1.0) / 2.0

        if state.last_call_timestamp is not None:
            elapsed = time.time() - state.last_call_timestamp
            v[21] = min(1.0, elapsed / 3600.0)
        else:
            v[21] = 1.0  # nunca chamou antes → máximo intervalo

        # ── [22-25] Intenção ──────────────────────────────────────────
        if state.intent_card is not None:
            from src.core.intent_card import IntentType
            ic = state.intent_card
            v[22] = 1.0 if ic.intent_type == IntentType.INFORMATION else 0.0
            v[23] = 1.0 if ic.intent_type == IntentType.ANALYSIS    else 0.0
            v[24] = 1.0 if ic.intent_type == IntentType.ACTION      else 0.0
            v[25] = ic.risk_level.value / 3.0

        # Validação: todos em [0, 1]
        v = [max(0.0, min(1.0, x)) for x in v]

        return v

    def feature_names(self) -> list[str]:
        """Nomes legíveis das 26 features — útil para debug e interpretabilidade."""
        return [
            # Query (0-5)
            "query_length_norm",
            "has_question_mark",
            "has_code_block",
            "has_url",
            "is_command",
            "sentiment_positive",
            # Tempo (6-9)
            "hour_sin",
            "hour_cos",
            "weekday_sin",
            "weekday_cos",
            # Budget (10-13)
            "budget_daily_used_pct",
            "budget_monthly_used_pct",
            "recent_cost_ma",
            "budget_pressure",
            # Providers (14-17)
            "provider_tier1_health",
            "provider_tier2_health",
            "recent_failures_norm",
            "avg_latency_norm",
            # Sessão (18-21)
            "session_length_norm",
            "recent_deep_ratio",
            "last_reward_norm",
            "time_since_last_call",
            # Intenção (22-25)
            "intent_is_information",
            "intent_is_analysis",
            "intent_is_action",
            "intent_risk_level",
        ]

    def describe(self, state: SeekerState) -> dict[str, float]:
        """Retorna dict {feature_name: value} para debug/logging."""
        return dict(zip(self.feature_names(), self.encode(state)))

    def __repr__(self) -> str:
        return f"StateEncoder(dim={STATE_DIM})"
