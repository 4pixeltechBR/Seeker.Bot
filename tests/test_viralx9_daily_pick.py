"""Testes do ViralX9 Daily Pick: viral_score + rota _run_daily_pick.

Cobre:
  1. viral_score prefere trending+outlier sobre strong+neutro
  2. viral_score sem trend_lift degrade graciosamente (lift=1.0)
  3. _run_daily_pick elege UMA única notificação (winner) a partir do pool
  4. _run_daily_pick pula candidatos já aprovados/rejeitados
  5. _run_daily_pick com pool vazio → sem notificação (não falha)
  6. _run_daily_pick marca last_run["09:00"] mesmo sem vencedor (evita re-tentar)
"""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

    DAILY_PICK_AT,
    SCORE_FRESHNESS_WINDOW_H,
    SCORE_TREND_WEIGHT,
    viral_score,
)


def _mk_cand(**overrides):
    base = {
        "id": "abc12345",
        "tema": "Tema exemplo",
        "tema_original": "Sample theme",
        "nicho": "microbiologia_ia",
        "justificativa": "🇺🇸 US · 🔥 3.0x a mediana · 800 views/h · 1d no ar",
        "video_id": "vid_xyz",
        "video_url": "https://www.youtube.com/watch?v=vid_xyz",
        "canal": "@TestChannel",
        "regiao": "us",
        "outlier": 3.0,
        "velocity": 800.0,
        "created_at": datetime.now().isoformat(),
        "status": "pending",
    }
    base.update(overrides)
    return base


# ── 1. viral_score prefere trending outlier ────────────────────────────
def test_viral_score_prefers_trending_outlier_over_strong_neutral():
    trending = _mk_cand(outlier=3.0, trend_lift=2.5, velocity=800.0)
    neutral = _mk_cand(outlier=6.0, trend_lift=1.0, velocity=1500.0)

    assert viral_score(trending) > viral_score(neutral), (
        f"trending ({viral_score(trending)}) devia bater strong-neutral ({viral_score(neutral)})"
    )


# ── 2. viral_score sem trend_lift (default 1.0) ainda funciona ───────────
def test_viral_score_without_trend_lift_defaults_to_neutral():
    cand = _mk_cand(outlier=3.0)
    score = viral_score(cand)
    assert score > 0
    # V2-F: outlier^1.0 * trend^1.5 * fresh * vel * thumb * filter
    # 3.0^1 * 1.0^1.5 * 1.0 * 1.12 * 0.85 * 1.0 = ~2.856
    assert 2.5 <= score <= 3.5


# ── 3. _run_daily_pick elege UM vencedor ────────────────────────────────
@pytest.mark.asyncio
async def test_run_daily_pick_elects_single_winner(monkeypatch):

    pipeline = MagicMock()

    state = {
        "candidatos": {
            "low_score": {
                "id": "low_score",
                "tema": "Tema fraco",
                "tema_original": "Weak topic",
                "nicho": "microbiologia_ia",
                "justificativa": "🇺🇸 US · 🔥 2.0x · 100 views/h",
                "video_id": "vid_weak",
                "video_url": "https://youtube.com/watch?v=vid_weak",
                "outlier": 2.0,
                "velocity": 100.0,
                "created_at": datetime.now().isoformat(),
                "status": "pending",
            },
            "high_score": {
                "id": "high_score",
                "tema": "Tema viral com trend",
                "tema_original": "Viral trending topic",
                "nicho": "forensic_tech",
                "justificativa": "🇺🇸 US · 🔥 4.0x · 2000 views/h",
                "video_id": "vid_strong",
                "video_url": "https://youtube.com/watch?v=vid_strong",
                "outlier": 4.0,
                "velocity": 2000.0,
                "created_at": datetime.now().isoformat(),
                "status": "pending",
            },
        },
        "vistos": [],
        "last_run": {},
        "canais_sugeridos": {},
        "medians": {},
        "daily_picks": {},
    }

    async def fake_fetch_trend_signals(cand, _pipeline):
        # high_score tem trend lift maior
        lift = 2.5 if cand["id"] == "high_score" else 1.0
        return {"trend_lift": lift, "trend_x_mentions": 10, "trend_web_score": 3, "trend_snippets": ["eco1"], "trend_cost": 0.001, "trend_sources": {}, "trend_verdict": "strong", "trend_evidence": []}

    monkeypatch.setattr(
        "src.skills.custom_extension.goal.fetch_trend_signals", fake_fetch_trend_signals
    )

    goal = ViralX9Goal(pipeline)
    result = await goal._run_daily_pick(state)

    assert result.success is True
    assert result.notification is not None
    assert "ViralX9" in result.notification and "Pick do Dia" in result.notification
    assert "Tema viral com trend" in result.notification
    assert result.data is not None
    buttons = result.data.get("buttons", [])
    assert len(buttons) == 1
    row = buttons[0]
    # Callbacks apontam para winner
    assert any("vx9_pick_ok:high_score" in (btn.get("callback_data", "")) for btn in row)
    assert any("vx9_pick_no:high_score" in (btn.get("callback_data", "")) for btn in row)
    # Persistiu histórico
    assert "high_score" in state.get("daily_picks", {})
    # Marcou janela como rodada
    assert state["last_run"].get(DAILY_PICK_AT) is not None


# ── 4. _run_daily_pick pula já aprovados/rejeitados ─────────────────────
@pytest.mark.asyncio
async def test_run_daily_pick_skips_non_pending(monkeypatch):

    pipeline = MagicMock()
    state = {
        "candidatos": {
            "approved_cand": {
                "id": "approved_cand",
                "tema": "Já aprovado",
                "nicho": "microbiologia_ia",
                "outlier": 10.0,
                "velocity": 5000.0,
                "created_at": datetime.now().isoformat(),
                "status": "approved",  # não elegível
                "video_id": "vid_a",
                "video_url": "https://youtube.com/watch?v=vid_a",
                "justificativa": "",
            },
            "pending_cand": {
                "id": "pending_cand",
                "tema": "Pendente elegível",
                "nicho": "microbiologia_ia",
                "outlier": 2.5,
                "velocity": 500.0,
                "created_at": datetime.now().isoformat(),
                "status": "pending",
                "video_id": "vid_b",
                "video_url": "https://youtube.com/watch?v=vid_b",
                "justificativa": "",
            },
        },
        "daily_picks": {},
        "last_run": {},
    }

    async def fake_fetch_trend_signals(cand, _p):
        return {"trend_lift": 1.0, "trend_x_mentions": 0, "trend_web_score": 0, "trend_snippets": [], "trend_cost": 0.0, "trend_sources": {}, "trend_verdict": "none", "trend_evidence": []}

    monkeypatch.setattr("src.skills.custom_extension.goal.fetch_trend_signals", fake_fetch_trend_signals)

    goal = ViralX9Goal(pipeline)
    result = await goal._run_daily_pick(state)

    assert result.success
    assert "Pendente elegível" in result.notification
    assert "Já aprovado" not in result.notification


# ── 5. pool vazio → sem notificação, não falha ───────────────────────────
@pytest.mark.asyncio
async def test_run_daily_pick_empty_pool_returns_silent(monkeypatch):

    pipeline = MagicMock()
    state = {"candidatos": {}, "vistos": [], "last_run": {}, "medians": {}, "canais_sugeridos": {}, "daily_picks": {}}

    goal = ViralX9Goal(pipeline)
    result = await goal._run_daily_pick(state)

    assert result.success
    assert result.notification is None
    # Marcou a janela para não re-tentar a cada 30 min
    assert state["last_run"].get(DAILY_PICK_AT) is not None


# ── 6. _run_daily_pick respeita cutoff de 24h ────────────────────────────
@pytest.mark.asyncio
async def test_run_daily_pick_respects_24h_cutoff(monkeypatch):

    pipeline = MagicMock()
    old = (datetime.now() - timedelta(hours=48)).isoformat()
    fresh = (datetime.now() - timedelta(hours=2)).isoformat()

    state = {
        "candidatos": {
            "old_cand": {
                "id": "old_cand",
                "tema": "Antigo",
                "nicho": "microbiologia_ia",
                "outlier": 10.0,
                "velocity": 5000.0,
                "created_at": old,
                "status": "pending",
                "video_id": "vid_old",
                "justificativa": "",
                "video_url": "https://youtube.com/x",
            },
            "fresh_cand": {
                "id": "fresh_cand",
                "tema": "Fresco",
                "nicho": "microbiologia_ia",
                "outlier": 2.2,
                "velocity": 300.0,
                "created_at": fresh,
                "status": "pending",
                "video_id": "vid_fresh",
                "justificativa": "",
                "video_url": "https://youtube.com/y",
            },
        },
        "daily_picks": {},
        "last_run": {},
    }

    async def fake_fetch_trend_signals(cand, _p):
        return {"trend_lift": 1.0, "trend_x_mentions": 0, "trend_web_score": 0, "trend_snippets": [], "trend_cost": 0.0, "trend_sources": {}, "trend_verdict": "none", "trend_evidence": []}

    monkeypatch.setattr("src.skills.custom_extension.goal.fetch_trend_signals", fake_fetch_trend_signals)

    goal = ViralX9Goal(pipeline)
    result = await goal._run_daily_pick(state)

    assert result.success
    assert "Fresco" in result.notification
    assert "Antigo" not in result.notification


# ── 7. _run_daily_pick não re-elege já Pick'd hoje ───────────────────────
@pytest.mark.asyncio
async def test_run_daily_pick_does_not_re_elect_same_day(monkeypatch):

    pipeline = MagicMock()
    today = datetime.now().date().isoformat()
    state = {
        "candidatos": {
            "winner1": {
                "id": "winner1",
                "tema": "Pick de hoje",
                "nicho": "microbiologia_ia",
                "outlier": 5.0,
                "velocity": 1500.0,
                "created_at": datetime.now().isoformat(),
                "status": "pending",
                "video_id": "vid_w1",
                "justificativa": "",
                "video_url": "https://youtube.com/z",
            },
        },
        "daily_picks": {
            "winner1": {"cand_id": "winner1", "date": today, "score": 9.0, "nicho": "microbiologia_ia", "tema": "Pick de hoje"}
        },
        "last_run": {},
    }

    async def fake_fetch_trend_signals(cand, _p):
        return {"trend_lift": 2.0, "trend_x_mentions": 5, "trend_web_score": 2, "trend_snippets": [], "trend_cost": 0.0, "trend_sources": {}, "trend_verdict": "moderate", "trend_evidence": []}

    monkeypatch.setattr("src.skills.custom_extension.goal.fetch_trend_signals", fake_fetch_trend_signals)

    goal = ViralX9Goal(pipeline)
    result = await goal._run_daily_pick(state)

    assert result.success
    assert result.notification is None  # excluído por já ter sido Pick hoje
    assert state["last_run"].get(DAILY_PICK_AT) is not None
