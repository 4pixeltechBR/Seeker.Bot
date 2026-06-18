"""
Testes mínimos para month_enricher.
Cobre: normalize_event_name, normalize_city, match_against_event_pool,
cluster_infer, heuristic_pattern, enrich_tier0.

NÃO testa enrich_via_search (requer pipeline LLM real).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.skills.seeker_sales.month_enricher import (
    normalize_event_name,
    normalize_city,
    match_against_event_pool,
    cluster_infer,
    heuristic_pattern,
    enrich_tier0,
)


# ── normalize_event_name ─────────────────────────────────────


class TestNormalizeEventName:
    def test_strips_accents_and_lowercases(self):
        assert normalize_event_name("Aniversário de Goiás") == "aniversario goias"

    def test_strips_year(self):
        out = normalize_event_name("Festival 2026")
        assert "2026" not in out
        assert "festival" in out

    def test_converts_roman_numerals(self):
        out = normalize_event_name("XX Festa do Peão")
        assert "20" in out
        assert "peao" in out

    def test_strips_ordinals(self):
        out = normalize_event_name("3ª Edição da ExpoAcreúna")
        assert "3" not in out  # ordinal removido
        assert "expoacreuna" in out  # nome próprio preservado

    def test_handles_empty(self):
        assert normalize_event_name("") == ""
        assert normalize_event_name(None) == ""

    def test_does_not_match_single_i_or_l(self):
        """L-3: "L" e "I" sozinhos NÃO devem virar números."""
        out = normalize_event_name("Banda L em Goiás")
        assert "50" not in out
        # E deveria preservar "l" como letra (ou nada relevante)
        assert "banda" in out

    def test_market_equivalences(self):
        assert "exposicao agropecuaria" in normalize_event_name("ExpoAgro 2026")
        assert "aniversario" in normalize_event_name("Niver da Cidade")


class TestNormalizeCity:
    def test_strips_go_suffix(self):
        assert normalize_city("Goiânia - GO") == "goiania"
        assert normalize_city("Caldas Novas GO") == "caldas novas"

    def test_strips_estado_prefix(self):
        assert normalize_city("Cidade de Goiás") == "goias"
        assert normalize_city("Goiás (Estado)") == "goias"


# ── match_against_event_pool ─────────────────────────────────


class TestMatchAgainstEventPool:
    def test_exact_match(self):
        pool = [{"nome": "Festa do Peão de Caldas Novas",
                 "cidade": "Caldas Novas",
                 "mes": 7,
                 "data_estimada": "Julho de 2026"}]
        lead = {"nome_evento": "Festa do Peão de Caldas Novas",
                "cidade": "Caldas Novas - GO"}
        result = match_against_event_pool(lead, pool, threshold=0.80)
        assert result is not None
        assert result["mes"] == 7
        assert result["source"] == "radar"  # default
        assert result["confidence"] >= 0.95

    def test_source_parameter_propagates(self):
        """C-2: source param deve aparecer no resultado."""
        pool = [{"nome": "Aniversário de Trindade", "cidade": "Trindade", "mes": 10}]
        lead = {"nome_evento": "Aniversário de Trindade", "cidade": "Trindade"}
        result = match_against_event_pool(lead, pool, source="mining")
        assert result is not None
        assert result["source"] == "mining"

    def test_below_threshold_returns_none(self):
        pool = [{"nome": "Carnaval de Goiânia", "cidade": "Goiânia", "mes": 2}]
        lead = {"nome_evento": "Aniversário de Goiânia", "cidade": "Goiânia"}
        result = match_against_event_pool(lead, pool, threshold=0.80)
        assert result is None

    def test_different_city_no_match(self):
        pool = [{"nome": "Festival X", "cidade": "São Paulo", "mes": 8}]
        lead = {"nome_evento": "Festival X", "cidade": "Caldas Novas"}
        result = match_against_event_pool(lead, pool)
        assert result is None

    def test_empty_pool(self):
        assert match_against_event_pool({"nome_evento": "X", "cidade": "Y"}, []) is None


# ── cluster_infer ────────────────────────────────────────────


class TestClusterInfer:
    def test_modal_inference(self):
        """Cidade com 3 rodeios em julho → infere julho."""
        pool = [
            {"nome": "Rodeio A", "cidade": "Acreúna", "mes": 7},
            {"nome": "Rodeio B", "cidade": "Acreúna", "mes": 7},
            {"nome": "Rodeio C", "cidade": "Acreúna", "mes": 8},
        ]
        lead = {"nome_evento": "Novo Rodeio em Acreúna", "cidade": "Acreúna"}
        result = cluster_infer(lead, pool, min_evidence=2)
        assert result is not None
        assert result["mes"] == 7
        # H-1: confidence reflete ratio modal/total (2/3 ≈ 0.67)
        assert 0.65 <= result["confidence"] <= 0.80

    def test_high_ratio_high_confidence(self):
        """100% modal → confidence próxima de 0.85."""
        pool = [
            {"nome": "Rodeio 1", "cidade": "X", "mes": 6},
            {"nome": "Rodeio 2", "cidade": "X", "mes": 6},
            {"nome": "Rodeio 3", "cidade": "X", "mes": 6},
        ]
        lead = {"nome_evento": "Outro Rodeio", "cidade": "X"}
        result = cluster_infer(lead, pool)
        assert result["confidence"] >= 0.80

    def test_insufficient_evidence(self):
        pool = [{"nome": "Rodeio", "cidade": "X", "mes": 6}]  # só 1
        lead = {"nome_evento": "Outro Rodeio", "cidade": "X"}
        assert cluster_infer(lead, pool, min_evidence=2) is None

    def test_outro_type_returns_none(self):
        lead = {"nome_evento": "Reunião Genérica", "cidade": "X"}
        pool = [{"nome": "Outro", "cidade": "X", "mes": 5}]
        assert cluster_infer(lead, pool) is None


# ── heuristic_pattern ────────────────────────────────────────


class TestHeuristicPattern:
    @pytest.mark.parametrize("nome,expected_mes", [
        ("Festa Junina Municipal", 6),
        ("Festa de São João", 6),
        ("Carnaval de Goiânia", 2),
        ("Réveillon na Praia", 12),
        ("Festa de N.S. Aparecida", 10),
        ("7 de Setembro Cívico", 9),
        ("Dia das Mães Especial", 5),
        ("Festa de Finados", 11),
    ])
    def test_recognizes_pattern(self, nome, expected_mes):
        result = heuristic_pattern(nome)
        assert result is not None, f"Should match: {nome}"
        assert result["mes"] == expected_mes

    def test_unknown_pattern_returns_none(self):
        assert heuristic_pattern("Reunião do Conselho") is None

    def test_movable_feast_has_lower_confidence(self):
        """M-1: Carnaval (móvel) confidence < 7 de Setembro (fixa)."""
        carn = heuristic_pattern("Carnaval 2026")
        sete_set = heuristic_pattern("Independência - 7 de Setembro")
        assert carn["confidence"] < sete_set["confidence"]


# ── enrich_tier0 cascata ────────────────────────────────────


class TestEnrichTier0:
    def test_radar_wins_over_heuristic(self):
        """Se o pool tem match exato, usa radar (não heurística)."""
        pool = [{"nome": "Festa Junina de Goiás",
                 "cidade": "Goiás",
                 "mes": 7,  # propositalmente diferente da heurística (6)
                 "data_estimada": "Julho de 2026"}]
        lead = {"nome_evento": "Festa Junina de Goiás", "cidade": "Goiás"}
        result = enrich_tier0(lead, pool)
        assert result["source"] == "radar"
        assert result["mes"] == 7  # do radar, não da heurística

    def test_fallback_to_heuristic(self):
        """Sem match no pool → cai na heurística."""
        lead = {"nome_evento": "Festa Junina Municipal", "cidade": "Cidade Sem Pool"}
        result = enrich_tier0(lead, [])
        assert result is not None
        assert result["source"] == "heuristic"
        assert result["mes"] == 6

    def test_pool_source_propagates(self):
        """C-2: pool_source rotula corretamente."""
        pool = [{"nome": "X", "cidade": "Y", "mes": 5, "data_estimada": "Maio 2026"}]
        lead = {"nome_evento": "X", "cidade": "Y"}
        result = enrich_tier0(lead, pool, pool_source="mining")
        assert result["source"] == "mining"
