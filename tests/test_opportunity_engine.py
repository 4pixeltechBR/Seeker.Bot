"""
Testes para opportunity_engine.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.skills.seeker_sales.opportunity_engine import (
    round_anniversary_bonus,
    consolidated_edition_bonus,
    cluster_bonus,
    window_freshness_bonus,
    compute_daily_priority_score,
    genres_for,
    build_cluster_index,
)


class TestRoundAnniversaryBonus:
    @pytest.mark.parametrize("nome,expected_pts", [
        ("Aniversário de 50 anos da Cidade", 20),
        ("Aniversário de 100 anos", 20),
        ("Aniversário de 30 anos", 10),
        ("Aniversário de 17 anos", 0),  # não-redondo
        ("Aniversário da Cidade", 0),    # sem número
    ])
    def test_anniversary_bonus(self, nome, expected_pts):
        pts, motivo = round_anniversary_bonus(nome)
        assert pts == expected_pts


class TestConsolidatedEditionBonus:
    @pytest.mark.parametrize("nome,expected_min_pts", [
        ("27ª Edição do ExpoAcreúna", 12),
        ("15º Festival", 8),
        ("5ª Festa", 5),
        ("3ª Edição", 0),
        ("Festival Novo", 0),
    ])
    def test_edition_bonus(self, nome, expected_min_pts):
        pts, _ = consolidated_edition_bonus(nome)
        assert pts == expected_min_pts


class TestWindowFreshness:
    @pytest.mark.parametrize("months,expected_sign", [
        (-2, "negative"),  # já passou — penalidade
        (1, "positive"),   # URGENTE
        (5, "positive"),   # ideal
        (12, "neutral"),   # janela larga
    ])
    def test_window_signs(self, months, expected_sign):
        pts, _ = window_freshness_bonus(months)
        if expected_sign == "positive":
            assert pts > 0
        elif expected_sign == "negative":
            assert pts < 0
        else:
            assert pts == 0

    def test_none_returns_zero(self):
        assert window_freshness_bonus(None) == (0, None)


class TestClusterBonus:
    def test_three_events_same_month_same_city(self):
        leads = [
            {"cidade": "Acreúna", "data_evento_mes": 5},
            {"cidade": "Acreúna", "data_evento_mes": 5},
            {"cidade": "Acreúna", "data_evento_mes": 5},
        ]
        pts, _ = cluster_bonus("Acreúna", 5, leads)
        assert pts == 12

    def test_no_cluster(self):
        leads = [{"cidade": "X", "data_evento_mes": 6}]
        pts, _ = cluster_bonus("X", 6, leads)
        assert pts == 0


class TestComputeScore:
    def test_full_signal(self):
        """BANT alto + aniversário redondo + janela ideal = score alto."""
        lead = {
            "score": 80,
            "nome_evento": "Aniversário de 50 anos da Cidade",
            "cidade": "Caldas Novas",
            "data_evento_mes": 11,
            "data_evento_ano": 2026,
        }
        result = compute_daily_priority_score(lead, ref_date=date(2026, 5, 19))
        assert result["score"] > 50
        assert any("aniversário redondo" in m for m in result["motivos"])

    def test_past_event_penalized(self):
        """C-3: evento passado tem score reduzido."""
        lead = {
            "score": 80,
            "nome_evento": "Festival",
            "cidade": "X",
            "data_evento_mes": 1,
            "data_evento_ano": 2026,
        }
        result = compute_daily_priority_score(lead, ref_date=date(2026, 5, 19))
        assert result["months_ahead"] < 0
        assert any("passou" in m for m in result["motivos"])

    def test_no_mes_no_months_ahead(self):
        lead = {"score": 50, "nome_evento": "X", "cidade": "Y"}
        result = compute_daily_priority_score(lead)
        assert result["months_ahead"] is None


class TestGenresFor:
    def test_rodeio_returns_sertanejo(self):
        assert "sertanejo" in genres_for("AGRO", "Festa do Peão")

    def test_unknown_defaults_to_variado(self):
        assert "variado" in genres_for(None, None)
