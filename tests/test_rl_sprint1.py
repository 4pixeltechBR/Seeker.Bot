"""
Testes do Sprint 1 — RL Infrastructure
tests/test_rl_sprint1.py

Cobre: StateEncoder, RewardCollector, LogBackfill
"""

import json
import os
import tempfile
import time
import math

import pytest

from src.core.rl.state_encoder import StateEncoder, SeekerState, STATE_DIM
from src.core.rl.reward_collector import (
    RewardCollector, RewardEvent, RewardSignal,
    SignalSource, RewardSign, W_BEHAVIORAL, W_TECHNICAL,
)
from src.core.rl.backfill import LogBackfill


# ─────────────────────────────────────────────────────────────────────────────
# StateEncoder
# ─────────────────────────────────────────────────────────────────────────────

class TestStateEncoder:

    def setup_method(self):
        self.encoder = StateEncoder()

    def test_output_dimension(self):
        state = SeekerState(query="teste")
        features = self.encoder.encode(state)
        assert len(features) == STATE_DIM == 26

    def test_all_values_in_range(self):
        state = SeekerState(
            query="analisa migração K8s com custo",
            budget_daily_used_usd=7.0,
            budget_daily_limit_usd=10.0,
            budget_monthly_used_usd=150.0,
            budget_monthly_limit_usd=200.0,
            provider_tier1_healthy=False,
            recent_failures=8,
            avg_latency_ms=1800,
            session_turns=25,
            recent_depths=["deep"] * 5,
            last_reward=-0.9,
        )
        features = self.encoder.encode(state)
        for i, v in enumerate(features):
            assert 0.0 <= v <= 1.0, f"Feature[{i}] fora do range [0,1]: {v}"

    def test_empty_state_no_crash(self):
        state = SeekerState()
        features = self.encoder.encode(state)
        assert len(features) == STATE_DIM

    def test_query_features(self):
        # Sem query: sem features de query
        state_empty = SeekerState(query="")
        f_empty = self.encoder.encode(state_empty)
        assert f_empty[0] == 0.0  # query_length

        # Com query curta
        state_short = SeekerState(query="ok")
        f_short = self.encoder.encode(state_short)
        assert 0 < f_short[0] < 0.1  # 1 palavra / 100

        # Pergunta com ?
        state_q = SeekerState(query="isso funciona?")
        assert self.encoder.encode(state_q)[1] == 1.0  # has_question_mark

        # Comando /
        state_cmd = SeekerState(query="/status")
        assert self.encoder.encode(state_cmd)[4] == 1.0  # is_command

    def test_time_encoding_cyclic(self):
        # Valores cíclicos de hora devem usar sin/cos — nunca fora de [0,1]
        for hour in range(24):
            ts = time.mktime(time.struct_time((2026, 4, 17, hour, 0, 0, 3, 107, 0)))
            state = SeekerState(timestamp=ts)
            f = self.encoder.encode(state)
            assert 0.0 <= f[6] <= 1.0, f"hour_sin fora do range, hora={hour}"
            assert 0.0 <= f[7] <= 1.0, f"hour_cos fora do range, hora={hour}"

    def test_budget_pressure(self):
        # Abaixo de 80%: sem pressão
        state_low = SeekerState(budget_daily_used_usd=5.0, budget_daily_limit_usd=10.0)
        assert self.encoder.encode(state_low)[13] == 0.0

        # Acima de 80%: com pressão
        state_high = SeekerState(budget_daily_used_usd=9.0, budget_daily_limit_usd=10.0)
        assert self.encoder.encode(state_high)[13] == 1.0

    def test_last_reward_encoding(self):
        # -1 → 0.0, 0 → 0.5, +1 → 1.0
        state_neg = SeekerState(last_reward=-1.0)
        assert self.encoder.encode(state_neg)[20] == pytest.approx(0.0, abs=0.01)

        state_zer = SeekerState(last_reward=0.0)
        assert self.encoder.encode(state_zer)[20] == pytest.approx(0.5, abs=0.01)

        state_pos = SeekerState(last_reward=1.0)
        assert self.encoder.encode(state_pos)[20] == pytest.approx(1.0, abs=0.01)

    def test_feature_names_match_dim(self):
        names = self.encoder.feature_names()
        assert len(names) == STATE_DIM

    def test_describe_returns_dict(self):
        state = SeekerState(query="hello")
        desc = self.encoder.describe(state)
        assert isinstance(desc, dict)
        assert len(desc) == STATE_DIM
        assert "query_length_norm" in desc


# ─────────────────────────────────────────────────────────────────────────────
# RewardCollector
# ─────────────────────────────────────────────────────────────────────────────

class TestRewardCollector:

    def setup_method(self):
        # Usa arquivo temporário para não poluir dados reais
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self.collector = RewardCollector(db_path=self.tmp)

    def teardown_method(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_open_close_event(self):
        event = self.collector.open_event("d001", "deliberate")
        assert "d001" in self.collector._open_events
        closed = self.collector.close_event("d001")
        assert closed is not None
        assert closed.closed_at is not None
        assert "d001" not in self.collector._open_events

    def test_technical_signal_success(self):
        self.collector.open_event("d002", "reflex")
        self.collector.record_technical("d002", success=True, cost_usd=0.002, latency_ms=200)
        event = self.collector._open_events["d002"]
        assert event.reward_technical > 0  # Sucesso > penalidades leves

    def test_technical_signal_failure(self):
        self.collector.open_event("d003", "deep")
        self.collector.record_technical("d003", success=False, timed_out=True)
        event = self.collector._open_events["d003"]
        assert event.reward_technical < 0

    def test_behavioral_positive_feedback(self):
        self.collector.open_event("d004", "deliberate")
        self.collector.observe_user_message("d004", "perfeito, valeu!", response_delay_seconds=15)
        event = self.collector._open_events["d004"]
        assert event.reward_behavioral > 0

    def test_behavioral_negative_feedback(self):
        self.collector.open_event("d005", "deep")
        self.collector.observe_user_message("d005", "simplifica isso", response_delay_seconds=500)
        event = self.collector._open_events["d005"]
        assert event.reward_behavioral < 0

    def test_behavioral_positive_emoji(self):
        self.collector.open_event("d006", "reflex")
        self.collector.observe_user_message("d006", "👍 show!")
        event = self.collector._open_events["d006"]
        assert event.reward_behavioral > 0

    def test_explicit_feedback_overrides_behavioral(self):
        self.collector.open_event("d007", "deliberate")
        self.collector.observe_user_message("d007", "simplifica")  # negativo
        self.collector.record_explicit_feedback("d007", value=1.0, reason="usuário votou positivo")
        event = self.collector._open_events["d007"]
        # Explicit tem precedência sobre behavioral
        assert event.reward_behavioral > 0

    def test_reward_total_uses_weights(self):
        self.collector.open_event("d008", "deep")
        self.collector.record_technical("d008", success=True, cost_usd=0.0, latency_ms=0)
        self.collector.observe_user_message("d008", "perfeito!")
        event = self.collector._open_events["d008"]
        expected = W_BEHAVIORAL * event.reward_behavioral + W_TECHNICAL * event.reward_technical
        assert event.reward_total == pytest.approx(expected, abs=0.001)

    def test_persist_and_export(self):
        event = self.collector.open_event("d009", "deliberate")
        self.collector.record_technical("d009", success=True, cost_usd=0.003, latency_ms=400)
        self.collector.close_event("d009")

        assert os.path.exists(self.tmp)
        dataset = self.collector.export_dataset(days=1)
        assert len(dataset) == 1
        assert dataset[0]["action_taken"] == "deliberate"

    def test_close_stale_events(self):
        event = self.collector.open_event("d010", "reflex")
        # Forca o evento a parecer velho
        event.created_at = time.time() - 1000
        count = self.collector.close_stale_events()
        assert count == 1
        assert "d010" not in self.collector._open_events

    def test_unknown_decision_id_is_noop(self):
        # Não deve cravar com ID desconhecido
        self.collector.record_technical("inexistente", success=True)
        self.collector.observe_user_message("inexistente", "ok")
        result = self.collector.close_event("inexistente")
        assert result is None

    def test_get_stats_empty(self):
        stats = self.collector.get_stats()
        assert stats["total_events"] == 0

    def test_get_stats_with_data(self):
        self.collector.open_event("d011", "deep")
        self.collector.record_technical("d011", success=True, cost_usd=0.01)
        self.collector.close_event("d011")
        stats = self.collector.get_stats()
        assert stats["total_events"] == 1
        assert "deep" in stats["by_action"]


# ─────────────────────────────────────────────────────────────────────────────
# LogBackfill
# ─────────────────────────────────────────────────────────────────────────────

class TestLogBackfill:

    def setup_method(self):
        self.log_tmp = tempfile.mktemp(suffix=".log")
        self.out_tmp = tempfile.mktemp(suffix=".jsonl")

    def teardown_method(self):
        for f in [self.log_tmp, self.out_tmp]:
            if os.path.exists(f):
                os.remove(f)

    def _write_log(self, lines: list[str]):
        with open(self.log_tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def test_empty_log(self):
        self._write_log([])
        backfill = LogBackfill(self.log_tmp, self.out_tmp)
        count = backfill.run(days=30)
        assert count == 0

    def test_routing_without_cascade_result(self):
        # Só routing sem resultado: sem evento gerado
        self._write_log([
            "10:00:00 [seeker.pipeline] INFO: [pipeline] deliberate | reason='test' | god=False | web=False",
        ])
        backfill = LogBackfill(self.log_tmp, self.out_tmp)
        count = backfill.run(days=30)
        assert count == 0

    def test_routing_with_cascade_success(self):
        self._write_log([
            "10:00:00 [seeker.pipeline] INFO: [pipeline] deliberate | reason='test' | god=False | web=False",
            "10:00:01 [seeker.cascade] INFO: [cascade] Tier 2 (groq) respondeu em 380ms",
        ])
        backfill = LogBackfill(self.log_tmp, self.out_tmp)
        count = backfill.run(days=30)
        assert count == 1

        # Verifica evento salvo
        with open(self.out_tmp) as f:
            ev = json.loads(f.readline())
        assert ev["action_taken"] == "deliberate"
        assert ev["reward_total"] > 0  # Sucesso tier2 deve ter reward positivo

    def test_routing_with_cascade_failure(self):
        self._write_log([
            "10:00:00 [seeker.pipeline] INFO: [pipeline] deep | reason='test' | god=False | web=True",
            "10:00:02 [seeker.cascade] WARNING: [cascade] Tier 1 excecao: timeout",
        ])
        backfill = LogBackfill(self.log_tmp, self.out_tmp)
        count = backfill.run(days=30)
        assert count == 1

        with open(self.out_tmp) as f:
            ev = json.loads(f.readline())
        assert ev["action_taken"] == "deep"
        assert ev["reward_total"] < 0  # Falha = reward negativo

    def test_dry_run_does_not_write(self):
        self._write_log([
            "10:00:00 [seeker.pipeline] INFO: [pipeline] reflex | reason='test' | god=False | web=False",
            "10:00:01 [seeker.cascade] INFO: [cascade] Tier 2 (groq) respondeu em 200ms",
        ])
        backfill = LogBackfill(self.log_tmp, self.out_tmp)
        count = backfill.run(days=30, dry_run=True)
        assert count == 1
        assert not os.path.exists(self.out_tmp)

    def test_nonexistent_log(self):
        backfill = LogBackfill("/nao/existe.log", self.out_tmp)
        count = backfill.run(days=30)
        assert count == 0

    def test_multiple_routing_cascade_pairs(self):
        self._write_log([
            "10:00:00 [seeker.pipeline] INFO: [pipeline] reflex | reason='r1' | god=False | web=False",
            "10:00:01 [seeker.cascade] INFO: [cascade] Tier 2 (groq) respondeu em 100ms",
            "10:01:00 [seeker.pipeline] INFO: [pipeline] deep | reason='r2' | god=False | web=True",
            "10:01:05 [seeker.cascade] INFO: [cascade] Tier 1 (deepseek) respondeu em 4200ms",
        ])
        backfill = LogBackfill(self.log_tmp, self.out_tmp)
        count = backfill.run(days=30)
        assert count == 2
