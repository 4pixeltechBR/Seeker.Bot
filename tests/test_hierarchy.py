"""
Seeker.Bot — Testes de Memory Hierarchy
tests/test_hierarchy.py

Cobre: get_layer, score_fact, prioritize_facts, format_hierarchical_context
"""

import time
import pytest

from src.core.memory.hierarchy import (
    MemoryLayer,
    CATEGORY_TO_LAYER,
    get_layer,
    score_fact,
    prioritize_facts,
    format_hierarchical_context,
)


# ── get_layer ─────────────────────────────────────────────────────────

def test_get_layer_categorias_conhecidas():
    assert get_layer("general") == MemoryLayer.SYSTEM
    assert get_layer("tech_context") == MemoryLayer.SYSTEM
    assert get_layer("user_pref") == MemoryLayer.USER
    assert get_layer("decision") == MemoryLayer.USER
    assert get_layer("pattern") == MemoryLayer.USER
    assert get_layer("project") == MemoryLayer.PROJECT
    assert get_layer("session") == MemoryLayer.SESSION
    assert get_layer("override") == MemoryLayer.OVERRIDE


def test_get_layer_categoria_desconhecida_usa_system():
    assert get_layer("categoria_inexistente") == MemoryLayer.SYSTEM


def test_get_layer_aliases_extractor_estao_mapeados():
    """Garante que as categorias geradas pelo FactExtractor estão no mapa."""
    categorias_extractor = ["user_pref", "tech_context", "decision", "pattern", "project", "general"]
    for cat in categorias_extractor:
        layer = get_layer(cat)
        assert isinstance(layer, MemoryLayer), f"categoria '{cat}' não mapeada"


def test_get_layer_user_pref_eh_user_layer():
    assert get_layer("user_pref") == MemoryLayer.USER


def test_get_layer_decision_eh_user_layer():
    assert get_layer("decision") == MemoryLayer.USER


def test_get_layer_pattern_eh_user_layer():
    assert get_layer("pattern") == MemoryLayer.USER


# ── score_fact ────────────────────────────────────────────────────────

def _make_fact(category="general", confidence=0.5, age_days=0, fact="fato de teste") -> dict:
    return {
        "fact": fact,
        "category": category,
        "confidence": confidence,
        "last_seen": time.time() - (age_days * 86400),
    }


def test_score_fact_camada_mais_especifica_ganha():
    """Override sempre pontua mais do que SYSTEM, independente da confiança."""
    fato_override = _make_fact(category="override", confidence=0.1)
    fato_system = _make_fact(category="general", confidence=0.95)
    assert score_fact(fato_override) > score_fact(fato_system)


def test_score_fact_user_acima_de_system():
    fato_user = _make_fact(category="user_pref", confidence=0.5)
    fato_system = _make_fact(category="general", confidence=0.9)
    assert score_fact(fato_user) > score_fact(fato_system)


def test_score_fact_project_acima_de_domain():
    fato_project = _make_fact(category="project", confidence=0.5)
    fato_domain = _make_fact(category="domain", confidence=0.9)
    assert score_fact(fato_project) > score_fact(fato_domain)


def test_score_fact_mais_recente_pontua_mais():
    fato_novo = _make_fact(age_days=0)
    fato_antigo = _make_fact(age_days=30)
    assert score_fact(fato_novo) > score_fact(fato_antigo)


def test_score_fact_confianca_alta_pontua_mais():
    fato_alto = _make_fact(confidence=0.9)
    fato_baixo = _make_fact(confidence=0.1)
    assert score_fact(fato_alto) > score_fact(fato_baixo)


def test_score_fact_categoria_ausente_usa_system():
    fato = {"confidence": 0.5, "last_seen": time.time()}  # sem category
    score = score_fact(fato)
    assert score > 0


# ── prioritize_facts ──────────────────────────────────────────────────

def test_prioritize_facts_ordena_por_score():
    facts = [
        _make_fact(category="general", confidence=0.5),
        _make_fact(category="override", confidence=0.5),
        _make_fact(category="user_pref", confidence=0.5),
    ]
    result = prioritize_facts(facts)
    # override deve vir primeiro, user_pref segundo, general terceiro
    assert result[0]["category"] == "override"
    assert result[1]["category"] == "user_pref"
    assert result[2]["category"] == "general"


def test_prioritize_facts_respeita_limit():
    facts = [_make_fact() for _ in range(20)]
    result = prioritize_facts(facts, limit=5)
    assert len(result) == 5


def test_prioritize_facts_lista_vazia():
    assert prioritize_facts([]) == []


def test_prioritize_facts_limit_maior_que_lista():
    facts = [_make_fact(), _make_fact()]
    result = prioritize_facts(facts, limit=100)
    assert len(result) == 2


# ── format_hierarchical_context ───────────────────────────────────────

def test_format_hierarchical_context_vazio():
    assert format_hierarchical_context([]) == ""


def test_format_hierarchical_context_contem_header():
    facts = [_make_fact()]
    result = format_hierarchical_context(facts)
    assert "MEMÓRIA SEMÂNTICA" in result


def test_format_hierarchical_context_contem_layer_name():
    facts = [_make_fact(category="user_pref")]
    result = format_hierarchical_context(facts)
    assert "user" in result.lower()


def test_format_hierarchical_context_contem_confianca():
    facts = [{"category": "general", "confidence": 0.8, "fact": "teste", "last_seen": time.time()}]
    result = format_hierarchical_context(facts)
    assert "80%" in result


def test_format_hierarchical_context_agrupa_por_layer():
    facts = [
        {"category": "override", "confidence": 0.9, "fact": "override fact", "last_seen": time.time()},
        {"category": "general", "confidence": 0.5, "fact": "general fact", "last_seen": time.time()},
    ]
    result = format_hierarchical_context(facts)
    # override deve aparecer antes de system na saída (ordem reversa de prioridade)
    pos_override = result.find("override")
    pos_system = result.find("system")
    assert pos_override < pos_system
