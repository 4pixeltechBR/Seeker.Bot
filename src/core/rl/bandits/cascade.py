"""
Seeker.Bot — LinUCB Cascade Bandit
src/core/rl/bandits/cascade.py

Sprint 2 — Aprendizado adaptativo de profundidade cognitiva.

Algoritmo: LinUCB Disjoint (Li et al., 2010)
  "A Contextual-Bandit Approach to Personalized News Article Recommendation"

O bandit aprende QUAL profundidade cognitiva usar em cada contexto:
  REFLEX     → 0 LLM calls (~$0.000 / ~10ms)
  DELIBERATE → 1-2 calls   (~$0.004 / ~500ms)
  DEEP       → 3+ calls    (~$0.015 / ~3000ms)

O CognitiveLoadRouter atual usa regex estáticas. O bandit vai aprender
que Victor às 09h pede análises profundas, às 22h prefere REFLEX,
que queries com "?" raramente precisam de DEEP, etc.

Modos de operação:
  SHADOW  — prediz mas não interfere. Loga divergências com o router.
            (ativo agora — coletando dados)
  ACTIVE  — substitui o router para 50% das queries (A/B test)
  FULL    — substitui completamente o router
            (só após validação estatística)

LinUCB Disjoint:
  Para cada arm k ∈ {reflex, deliberate, deep}:
    Aₖ ← d×d identity matrix (d=26, features do StateEncoder)
    bₖ ← d-vector de zeros

  Predição:
    θₖ = Aₖ⁻¹ bₖ
    UCB_k = θₖᵀ x + α √(xᵀ Aₖ⁻¹ x)
    arm* = argmax UCB_k

  Update (quando reward observado):
    Aₖ ← Aₖ + xxᵀ
    bₖ ← bₖ + reward * x

Parâmetro α controla exploration vs exploitation:
  α alto → explora mais (mais variação)
  α baixo → explora menos (aproveita o que sabe)
  Recomendado inicial: α=1.0, decai para α=0.3 após 500 samples.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("seeker.rl.bandit.cascade")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

STATE_DIM   = 26        # dimensão do StateEncoder
ALPHA_INIT  = 1.0       # exploração inicial (alta)
ALPHA_FLOOR = 0.3       # exploração mínima após muitos samples
ALPHA_DECAY = 500       # samples até atingir ALPHA_FLOOR
MODEL_PATH  = os.path.join(os.getcwd(), "data", "rl_bandit_cascade.npz")
LOG_PATH    = os.path.join(os.getcwd(), "data", "rl_bandit_shadow.jsonl")

# Arms disponíveis — mapeados para CognitiveDepth.value
ARMS = ["reflex", "deliberate", "deep"]

# Custo estimado por arm (usado para reward no modo shadow)
ARM_COST_ESTIMATE = {
    "reflex":     0.000,
    "deliberate": 0.004,
    "deep":       0.015,
}


# ─────────────────────────────────────────────────────────────────────────────
# TIPOS
# ─────────────────────────────────────────────────────────────────────────────

class BanditMode(str, Enum):
    SHADOW = "shadow"   # prediz, não age — coleta dados
    ACTIVE = "active"   # A/B test: age em 50% das queries
    FULL   = "full"     # substitui router completamente


@dataclass
class BanditDecision:
    """Resultado de uma predição do bandit."""
    recommended_arm: str        # arm recomendado pelo bandit
    router_arm: str             # arm escolhido pelo router atual
    agrees: bool                # bandit == router?
    ucb_scores: dict[str, float]
    alpha: float
    decision_id: str
    timestamp: float = field(default_factory=time.time)

    # Preenchidos após receber reward
    reward: Optional[float] = None
    actual_arm: str = ""        # arm que foi realmente executado
    closed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# LinUCB DISJOINT
# ─────────────────────────────────────────────────────────────────────────────

class CascadeBandit:
    """
    LinUCB Disjoint Bandit para seleção de profundidade cognitiva.

    Uso:
        bandit = CascadeBandit(mode=BanditMode.SHADOW)
        bandit.load()  # carrega modelo do disco se existir

        # A cada decisão:
        features = state_encoder.encode(state)   # lista[float] de 26 dims
        decision = bandit.predict(features, router_arm="deliberate", decision_id="abc")

        # Em shadow mode: decision.recommended_arm é apenas log
        # Em active/full: use decision.recommended_arm para rotear

        # Quando reward disponível (RewardCollector fecha o evento):
        bandit.update(decision_id="abc", features=features, reward=0.42)

        # Periodicamente:
        bandit.save()
    """

    def __init__(
        self,
        mode: BanditMode = BanditMode.SHADOW,
        alpha: float = ALPHA_INIT,
        model_path: str = MODEL_PATH,
        log_path: str = LOG_PATH,
    ):
        self.mode       = mode
        self._alpha     = alpha
        self.model_path = model_path
        self.log_path   = log_path

        # Uma matriz A e vetor b por arm (LinUCB Disjoint)
        self._A: dict[str, np.ndarray] = {
            arm: np.identity(STATE_DIM) for arm in ARMS
        }
        self._b: dict[str, np.ndarray] = {
            arm: np.zeros(STATE_DIM) for arm in ARMS
        }

        # Contadores
        self._n_updates: dict[str, int]   = {arm: 0 for arm in ARMS}
        self._n_predicts: int             = 0
        self._agreements: int             = 0  # vezes que concordou com router
        self._divergences: int            = 0  # vezes que discordou

        # Pendentes: decision_id → (features, arm escolhido)
        self._pending: dict[str, dict] = {}

        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        os.makedirs(os.path.dirname(log_path),   exist_ok=True)

        log.info(
            f"[bandit] CascadeBandit inicializado | mode={mode.value} α={alpha}"
        )

    # ── Propriedades ──────────────────────────────────────────────────

    @property
    def alpha(self) -> float:
        """Alpha decai com número total de updates."""
        total = sum(self._n_updates.values())
        if total >= ALPHA_DECAY:
            return ALPHA_FLOOR
        # Decai linearmente de ALPHA_INIT até ALPHA_FLOOR
        progress = total / ALPHA_DECAY
        return ALPHA_INIT - (ALPHA_INIT - ALPHA_FLOOR) * progress

    @property
    def total_updates(self) -> int:
        return sum(self._n_updates.values())

    @property
    def agreement_rate(self) -> float:
        total = self._agreements + self._divergences
        return self._agreements / total if total > 0 else 1.0

    # ── Predição ──────────────────────────────────────────────────────

    def predict(
        self,
        features: list[float],
        router_arm: str,
        decision_id: str,
    ) -> BanditDecision:
        """
        Prediz o melhor arm para o contexto dado.

        Args:
            features:    vetor de 26 features do StateEncoder
            router_arm:  arm escolhido pelo CognitiveLoadRouter atual
            decision_id: ID do evento RL (para correlação)

        Returns:
            BanditDecision com recommended_arm e ucb_scores
        """
        x = np.array(features, dtype=float)
        alpha = self.alpha

        ucb_scores = {}
        for arm in ARMS:
            A_inv = np.linalg.inv(self._A[arm])
            theta = A_inv @ self._b[arm]
            ucb = float(theta @ x + alpha * np.sqrt(x @ A_inv @ x))
            ucb_scores[arm] = ucb

        best_arm = max(ucb_scores, key=ucb_scores.__getitem__)
        agrees   = (best_arm == router_arm)

        self._n_predicts += 1
        if agrees:
            self._agreements += 1
        else:
            self._divergences += 1

        # Guarda features para update posterior
        self._pending[decision_id] = {
            "features": features,
            "recommended_arm": best_arm,
            "router_arm": router_arm,
        }

        decision = BanditDecision(
            recommended_arm=best_arm,
            router_arm=router_arm,
            agrees=agrees,
            ucb_scores=ucb_scores,
            alpha=alpha,
            decision_id=decision_id,
        )

        # Log divergências para análise
        if not agrees:
            log.debug(
                f"[bandit] SHADOW diverge: router={router_arm} "
                f"bandit={best_arm} | "
                f"UCB reflex={ucb_scores['reflex']:.3f} "
                f"delib={ucb_scores['deliberate']:.3f} "
                f"deep={ucb_scores['deep']:.3f}"
            )

        self._persist_decision(decision)
        return decision

    # ── Update ────────────────────────────────────────────────────────

    def update(self, decision_id: str, reward: float) -> bool:
        """
        Atualiza o modelo com o reward observado.

        Em shadow mode, o arm atualizado é o que o router escolheu
        (porque é o que foi realmente executado).

        Args:
            decision_id: ID da decisão (mesmo do predict)
            reward:      reward do RewardCollector ([-1, +1] → normalizado)

        Returns:
            True se update bem-sucedido
        """
        pending = self._pending.pop(decision_id, None)
        if pending is None:
            return False

        x   = np.array(pending["features"], dtype=float)
        arm = pending["router_arm"]  # atualiza o arm que foi executado

        # Normaliza reward para [0, 1] para estabilidade numérica do LinUCB
        # LinUCB assume rewards não-negativos
        r = (reward + 1.0) / 2.0

        self._A[arm] += np.outer(x, x)
        self._b[arm] += r * x
        self._n_updates[arm] += 1

        log.debug(
            f"[bandit] Update arm={arm} reward={reward:+.3f} "
            f"(norm={r:.3f}) | n={self._n_updates[arm]}"
        )

        # Auto-save a cada 50 updates totais
        if self.total_updates % 50 == 0:
            self.save()

        return True

    def update_from_collector(self, decision_id: str, collector) -> bool:
        """
        Atalho: busca reward do RewardCollector e atualiza.

        Args:
            decision_id: ID da decisão
            collector:   instância do RewardCollector
        """
        # Tenta encontrar o evento no histórico recente
        dataset = collector.export_dataset(days=1)
        for ev in dataset:
            if ev["decision_id"] == decision_id:
                return self.update(decision_id, ev["reward_total"])
        return False

    # ── Persistência ─────────────────────────────────────────────────

    def save(self) -> None:
        """Salva matrizes A, b e contadores em .npz."""
        try:
            arrays = {}
            for arm in ARMS:
                arrays[f"A_{arm}"] = self._A[arm]
                arrays[f"b_{arm}"] = self._b[arm]
            # Salva contadores como array de 1 elemento
            for arm in ARMS:
                arrays[f"n_{arm}"] = np.array([self._n_updates[arm]])
            arrays["meta"] = np.array([
                self._n_predicts, self._agreements, self._divergences
            ])
            np.savez(self.model_path, **arrays)
            log.debug(
                f"[bandit] Modelo salvo: {self.model_path} "
                f"(total_updates={self.total_updates})"
            )
        except Exception as e:
            log.error(f"[bandit] Falha ao salvar modelo: {e}")

    def load(self) -> bool:
        """Carrega matrizes do disco. Retorna True se bem-sucedido."""
        path = self.model_path + ".npz" if not self.model_path.endswith(".npz") else self.model_path
        if not os.path.exists(path):
            log.info(f"[bandit] Nenhum modelo encontrado em {path} — iniciando do zero")
            return False

        try:
            data = np.load(path)
            for arm in ARMS:
                if f"A_{arm}" in data:
                    self._A[arm] = data[f"A_{arm}"]
                    self._b[arm] = data[f"b_{arm}"]
                    self._n_updates[arm] = int(data[f"n_{arm}"][0])
            if "meta" in data:
                meta = data["meta"]
                self._n_predicts   = int(meta[0])
                self._agreements   = int(meta[1])
                self._divergences  = int(meta[2])
            log.info(
                f"[bandit] Modelo carregado: total_updates={self.total_updates} "
                f"α={self.alpha:.3f} agreement={self.agreement_rate:.0%}"
            )
            return True
        except Exception as e:
            log.error(f"[bandit] Falha ao carregar modelo: {e}")
            return False

    def _persist_decision(self, decision: BanditDecision) -> None:
        """Salva decisão em shadow log para análise offline."""
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(decision.to_dict(), ensure_ascii=False) + "\n")
        except Exception:
            pass  # nunca quebra o fluxo

    # ── Stats & Relatórios ────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Retorna métricas do bandit — para /perf ou dashboard."""
        return {
            "mode": self.mode.value,
            "total_predicts": self._n_predicts,
            "total_updates": self.total_updates,
            "alpha": round(self.alpha, 4),
            "agreement_rate": round(self.agreement_rate, 3),
            "divergences": self._divergences,
            "updates_per_arm": dict(self._n_updates),
            "ready_for_active": self.total_updates >= 100,
        }

    def format_stats(self) -> str:
        """Formata stats para exibição no Telegram."""
        s = self.get_stats()
        arm_lines = "\n".join(
            f"  {arm}: {n} updates"
            for arm, n in s["updates_per_arm"].items()
        )
        status = "PRONTO para A/B test" if s["ready_for_active"] else f"coletando ({s['total_updates']}/100 updates)"
        return (
            f"<b>LinUCB Bandit</b> [{s['mode'].upper()}]\n"
            f"Predicoes: {s['total_predicts']} | Concorda: {s['agreement_rate']:.0%}\n"
            f"Alpha: {s['alpha']:.3f} | Divergencias: {s['divergences']}\n"
            f"Updates por arm:\n{arm_lines}\n"
            f"Status: {status}"
        )

    def top_features_by_arm(self) -> dict[str, list[tuple[str, float]]]:
        """
        Retorna as features mais influentes por arm (θ = A⁻¹b).
        Útil para interpretar o que o bandit aprendeu.
        """
        from src.core.rl.state_encoder import StateEncoder
        names = StateEncoder().feature_names()

        result = {}
        for arm in ARMS:
            theta = np.linalg.inv(self._A[arm]) @ self._b[arm]
            # Ordena por valor absoluto (importância)
            ranked = sorted(
                zip(names, theta.tolist()),
                key=lambda t: abs(t[1]),
                reverse=True,
            )
            result[arm] = ranked[:5]  # top 5 por arm
        return result
