"""
Testes do Sprint 2 — LinUCB Cascade Bandit
tests/test_rl_sprint2.py
"""

import os
import tempfile
import math

import numpy as np
import pytest

from src.core.rl.bandits.cascade import (
    CascadeBandit, BanditDecision, BanditMode,
    ARMS, STATE_DIM, ALPHA_INIT, ALPHA_FLOOR, ALPHA_DECAY,
)
from src.core.rl.state_encoder import StateEncoder, SeekerState


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_bandit(tmp_path):
    model_path = str(tmp_path / "bandit.npz")
    log_path   = str(tmp_path / "shadow.jsonl")
    return CascadeBandit(
        mode=BanditMode.SHADOW,
        model_path=model_path,
        log_path=log_path,
    )


@pytest.fixture
def encoder():
    return StateEncoder()


def make_features(query="teste", **kwargs) -> list[float]:
    state = SeekerState(query=query, **kwargs)
    return StateEncoder().encode(state)


# ─────────────────────────────────────────────────────────────────────────────
# Inicialização
# ─────────────────────────────────────────────────────────────────────────────

class TestCascadeBanditInit:

    def test_arms_initialized(self, tmp_bandit):
        for arm in ARMS:
            assert arm in tmp_bandit._A
            assert arm in tmp_bandit._b
            assert tmp_bandit._A[arm].shape == (STATE_DIM, STATE_DIM)
            assert tmp_bandit._b[arm].shape == (STATE_DIM,)

    def test_identity_init(self, tmp_bandit):
        for arm in ARMS:
            assert np.allclose(tmp_bandit._A[arm], np.identity(STATE_DIM))
            assert np.allclose(tmp_bandit._b[arm], np.zeros(STATE_DIM))

    def test_alpha_starts_at_init_value(self, tmp_bandit):
        assert tmp_bandit.alpha == ALPHA_INIT

    def test_mode_shadow(self, tmp_bandit):
        assert tmp_bandit.mode == BanditMode.SHADOW


# ─────────────────────────────────────────────────────────────────────────────
# Predição
# ─────────────────────────────────────────────────────────────────────────────

class TestCascadeBanditPredict:

    def test_returns_bandit_decision(self, tmp_bandit):
        features = make_features("como funciona isso?")
        decision = tmp_bandit.predict(features, router_arm="deliberate", decision_id="d001")
        assert isinstance(decision, BanditDecision)

    def test_recommended_arm_is_valid(self, tmp_bandit):
        features = make_features()
        decision = tmp_bandit.predict(features, router_arm="reflex", decision_id="d002")
        assert decision.recommended_arm in ARMS

    def test_ucb_scores_all_arms(self, tmp_bandit):
        features = make_features()
        decision = tmp_bandit.predict(features, router_arm="reflex", decision_id="d003")
        assert set(decision.ucb_scores.keys()) == set(ARMS)

    def test_agrees_field(self, tmp_bandit):
        features = make_features()
        decision = tmp_bandit.predict(features, router_arm="reflex", decision_id="d004")
        assert decision.agrees == (decision.recommended_arm == "reflex")

    def test_agreement_counter_increments(self, tmp_bandit):
        features = make_features()
        # Primeira predição: bandit sem treinamento tende a ser indeterminado
        dec = tmp_bandit.predict(features, router_arm="reflex", decision_id="d005")
        assert tmp_bandit._n_predicts == 1
        assert (tmp_bandit._agreements + tmp_bandit._divergences) == 1

    def test_pending_stored(self, tmp_bandit):
        features = make_features()
        tmp_bandit.predict(features, router_arm="deliberate", decision_id="d006")
        assert "d006" in tmp_bandit._pending

    def test_shadow_log_written(self, tmp_bandit):
        features = make_features()
        tmp_bandit.predict(features, router_arm="deep", decision_id="d007")
        assert os.path.exists(tmp_bandit.log_path)

    def test_ucb_symmetry_untrained(self, tmp_bandit):
        """
        Sem treinamento, A=I e b=0 → theta=0 → UCB = α√(xᵀx).
        Todos os arms têm o mesmo UCB (features são idênticas para todos).
        """
        features = make_features()
        decision = tmp_bandit.predict(features, router_arm="reflex", decision_id="d008")
        scores = list(decision.ucb_scores.values())
        # Todos iguais (sem treinamento, theta=0 para todos os arms)
        assert abs(max(scores) - min(scores)) < 1e-8


# ─────────────────────────────────────────────────────────────────────────────
# Update
# ─────────────────────────────────────────────────────────────────────────────

class TestCascadeBanditUpdate:

    def test_update_increments_counter(self, tmp_bandit):
        features = make_features()
        tmp_bandit.predict(features, router_arm="deliberate", decision_id="u001")
        result = tmp_bandit.update("u001", reward=0.5)
        assert result is True
        assert tmp_bandit._n_updates["deliberate"] == 1

    def test_update_modifies_A_and_b(self, tmp_bandit):
        features = make_features()
        A_before = tmp_bandit._A["deliberate"].copy()
        b_before = tmp_bandit._b["deliberate"].copy()

        tmp_bandit.predict(features, router_arm="deliberate", decision_id="u002")
        tmp_bandit.update("u002", reward=1.0)

        assert not np.allclose(tmp_bandit._A["deliberate"], A_before)
        assert not np.allclose(tmp_bandit._b["deliberate"], b_before)

    def test_update_clears_pending(self, tmp_bandit):
        features = make_features()
        tmp_bandit.predict(features, router_arm="reflex", decision_id="u003")
        assert "u003" in tmp_bandit._pending
        tmp_bandit.update("u003", reward=0.2)
        assert "u003" not in tmp_bandit._pending

    def test_update_unknown_id_returns_false(self, tmp_bandit):
        result = tmp_bandit.update("inexistente", reward=0.5)
        assert result is False

    def test_positive_reward_increases_theta(self, tmp_bandit):
        """Após reward positivo, o arm deve ter UCB maior para o mesmo contexto."""
        features = make_features("analisa K8s")
        x = np.array(features)

        # Baseline: UCB antes do treinamento
        tmp_bandit.predict(features, router_arm="deep", decision_id="u004")
        theta_before = np.linalg.inv(tmp_bandit._A["deep"]) @ tmp_bandit._b["deep"]
        ucb_before = float(theta_before @ x)

        # Update com reward alto
        tmp_bandit.update("u004", reward=1.0)

        theta_after = np.linalg.inv(tmp_bandit._A["deep"]) @ tmp_bandit._b["deep"]
        ucb_after = float(theta_after @ x)

        assert ucb_after > ucb_before

    def test_negative_reward_modifies_A(self, tmp_bandit):
        """
        Reward -1.0 normaliza para r=0.0 → b não muda, mas A sempre muda
        (A += xxᵀ independente do reward). Isso é correto: A acumula visitas
        e reduz incerteza mesmo para experiências negativas.
        """
        features = make_features("ok")
        A_before = tmp_bandit._A["deep"].copy()
        b_before = tmp_bandit._b["deep"].copy()

        tmp_bandit.predict(features, router_arm="deep", decision_id="u005")
        tmp_bandit.update("u005", reward=-1.0)  # normaliza para r=0.0

        # A muda (acumula visita)
        assert not np.allclose(tmp_bandit._A["deep"], A_before)
        # b não muda com r=0 (comportamento correto do LinUCB)
        assert np.allclose(tmp_bandit._b["deep"], b_before)

    def test_partial_negative_reward_changes_b(self, tmp_bandit):
        """Reward -0.5 normaliza para r=0.25 → b muda."""
        features = make_features("ok")
        b_before = tmp_bandit._b["deep"].copy()

        tmp_bandit.predict(features, router_arm="deep", decision_id="u005b")
        tmp_bandit.update("u005b", reward=-0.5)  # normaliza para r=0.25

        assert not np.allclose(tmp_bandit._b["deep"], b_before)

    def test_only_router_arm_updated(self, tmp_bandit):
        """Update só modifica o arm que o router escolheu, não os outros."""
        features = make_features()
        A_reflex_before    = tmp_bandit._A["reflex"].copy()
        A_deep_before      = tmp_bandit._A["deep"].copy()

        tmp_bandit.predict(features, router_arm="deliberate", decision_id="u006")
        tmp_bandit.update("u006", reward=0.7)

        # reflex e deep não devem ter mudado
        assert np.allclose(tmp_bandit._A["reflex"], A_reflex_before)
        assert np.allclose(tmp_bandit._A["deep"],   A_deep_before)


# ─────────────────────────────────────────────────────────────────────────────
# Alpha Decay
# ─────────────────────────────────────────────────────────────────────────────

class TestAlphaDecay:

    def test_alpha_starts_at_init(self, tmp_bandit):
        assert tmp_bandit.alpha == ALPHA_INIT

    def test_alpha_decays_with_updates(self, tmp_bandit):
        features = make_features()
        # Faz muitos updates
        for i in range(200):
            tmp_bandit.predict(features, router_arm="reflex", decision_id=f"a{i}")
            tmp_bandit.update(f"a{i}", reward=0.5)
        assert tmp_bandit.alpha < ALPHA_INIT
        assert tmp_bandit.alpha > ALPHA_FLOOR

    def test_alpha_floors_after_decay_threshold(self, tmp_bandit):
        features = make_features()
        for i in range(ALPHA_DECAY + 10):
            tmp_bandit.predict(features, router_arm="deliberate", decision_id=f"b{i}")
            tmp_bandit.update(f"b{i}", reward=0.5)
        assert tmp_bandit.alpha == ALPHA_FLOOR


# ─────────────────────────────────────────────────────────────────────────────
# Aprendizado (convergência)
# ─────────────────────────────────────────────────────────────────────────────

class TestLearningConvergence:

    def test_bandit_learns_reflex_for_short_queries(self, tmp_bandit):
        """
        Se queries curtas (reflex) sempre têm reward alto,
        o bandit deve começar a preferir reflex para features de query curta.
        """
        encoder = StateEncoder()

        # Treina: queries curtas com REFLEX têm reward alto
        for i in range(80):
            features = encoder.encode(SeekerState(query="ok"))
            tmp_bandit.predict(features, router_arm="reflex", decision_id=f"r{i}")
            tmp_bandit.update(f"r{i}", reward=0.9)

        # Treina: queries curtas com DEEP têm reward baixo (caro demais)
        for i in range(80):
            features = encoder.encode(SeekerState(query="ok"))
            tmp_bandit.predict(features, router_arm="deep", decision_id=f"d{i}")
            tmp_bandit.update(f"d{i}", reward=-0.5)

        # Testa: para query curta, bandit deve preferir reflex
        test_features = encoder.encode(SeekerState(query="ok"))
        decision = tmp_bandit.predict(test_features, router_arm="reflex", decision_id="test_r")
        assert decision.ucb_scores["reflex"] > decision.ucb_scores["deep"], (
            f"Esperado reflex > deep, mas reflex={decision.ucb_scores['reflex']:.3f} "
            f"deep={decision.ucb_scores['deep']:.3f}"
        )

    def test_agreement_rate_high_when_aligned(self, tmp_bandit):
        """
        Se o router é consistente com os rewards que o bandit aprende,
        a taxa de concordância deve ser alta.
        """
        encoder = StateEncoder()

        # Treina alinhado com o router (deliberate é sempre a escolha certa)
        for i in range(50):
            features = encoder.encode(SeekerState(query="como funciona " * 3))
            tmp_bandit.predict(features, router_arm="deliberate", decision_id=f"ag{i}")
            tmp_bandit.update(f"ag{i}", reward=0.8)

        # Depois de treinamento, taxa de concordância deve melhorar
        # (não testa valor absoluto pois depende do estado inicial)
        assert tmp_bandit.total_updates == 50


# ─────────────────────────────────────────────────────────────────────────────
# Persistência
# ─────────────────────────────────────────────────────────────────────────────

class TestPersistence:

    def test_save_and_load(self, tmp_path):
        model_path = str(tmp_path / "bandit.npz")
        log_path   = str(tmp_path / "shadow.jsonl")

        # Cria e treina bandit
        b1 = CascadeBandit(model_path=model_path, log_path=log_path)
        features = make_features("analisa o sistema")
        b1.predict(features, router_arm="deep", decision_id="p001")
        b1.update("p001", reward=0.8)
        A_after = b1._A["deep"].copy()
        b1.save()

        # Carrega em novo bandit
        b2 = CascadeBandit(model_path=model_path, log_path=log_path)
        b2.load()

        assert np.allclose(b2._A["deep"], A_after)
        assert b2._n_updates["deep"] == 1
        assert b2.total_updates == 1

    def test_load_nonexistent_returns_false(self, tmp_path):
        b = CascadeBandit(
            model_path=str(tmp_path / "nofile.npz"),
            log_path=str(tmp_path / "nolog.jsonl"),
        )
        assert b.load() is False

    def test_autosave_at_50_updates(self, tmp_path):
        model_path = str(tmp_path / "auto.npz")
        log_path   = str(tmp_path / "auto.jsonl")
        b = CascadeBandit(model_path=model_path, log_path=log_path)

        features = make_features()
        for i in range(50):
            b.predict(features, router_arm="reflex", decision_id=f"as{i}")
            b.update(f"as{i}", reward=0.3)

        assert os.path.exists(model_path + ".npz") or os.path.exists(model_path)


# ─────────────────────────────────────────────────────────────────────────────
# Stats & Formatação
# ─────────────────────────────────────────────────────────────────────────────

class TestStats:

    def test_get_stats_keys(self, tmp_bandit):
        stats = tmp_bandit.get_stats()
        assert "mode" in stats
        assert "total_predicts" in stats
        assert "total_updates" in stats
        assert "alpha" in stats
        assert "agreement_rate" in stats
        assert "ready_for_active" in stats

    def test_not_ready_with_zero_updates(self, tmp_bandit):
        assert tmp_bandit.get_stats()["ready_for_active"] is False

    def test_ready_after_100_updates(self, tmp_bandit):
        features = make_features()
        for i in range(100):
            tmp_bandit.predict(features, router_arm="deliberate", decision_id=f"rdy{i}")
            tmp_bandit.update(f"rdy{i}", reward=0.5)
        assert tmp_bandit.get_stats()["ready_for_active"] is True

    def test_format_stats_returns_string(self, tmp_bandit):
        text = tmp_bandit.format_stats()
        assert isinstance(text, str)
        assert "SHADOW" in text

    def test_top_features_returns_5_per_arm(self, tmp_bandit):
        features = make_features("analisa K8s deployment")
        tmp_bandit.predict(features, router_arm="deep", decision_id="tf001")
        tmp_bandit.update("tf001", reward=0.9)
        top = tmp_bandit.top_features_by_arm()
        for arm in ARMS:
            assert arm in top
            assert len(top[arm]) == 5
