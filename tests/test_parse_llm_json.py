"""
Seeker.Bot — Testes de parse_llm_json
tests/test_parse_llm_json.py

Cobre todos os formatos de resposta LLM que o utilitário precisa suportar.
"""

import pytest
from src.core.utils import parse_llm_json


# ── Casos de sucesso ───────────────────────────────────────────────────

def test_json_puro_objeto():
    assert parse_llm_json('{"a": 1}') == {"a": 1}


def test_json_puro_array():
    assert parse_llm_json('[1, 2, 3]') == [1, 2, 3]


def test_json_com_texto_antes_e_depois():
    result = parse_llm_json('Aqui está o resultado: {"b": 2} e pronto.')
    assert result == {"b": 2}


def test_json_com_fence_json():
    result = parse_llm_json('```json\n{"c": 3}\n```')
    assert result == {"c": 3}


def test_json_com_fence_generica():
    result = parse_llm_json('```\n{"d": 4}\n```')
    assert result == {"d": 4}


def test_array_com_texto_ao_redor():
    result = parse_llm_json('Resposta: [{"x": 1}, {"x": 2}]')
    assert result == [{"x": 1}, {"x": 2}]


def test_array_vem_antes_de_objeto():
    """Quando texto tem [ antes de {, deve preferir o array."""
    result = parse_llm_json('[1, 2] e {"extra": true}')
    assert result == [1, 2]


def test_objeto_vem_antes_de_array():
    """Quando { vem antes de [, deve preferir o objeto."""
    result = parse_llm_json('{"key": [1, 2]}')
    assert result == {"key": [1, 2]}


def test_json_aninhado():
    payload = '{"facts": [{"fact": "Python é rápido", "confidence": 0.9}]}'
    result = parse_llm_json(payload)
    assert result["facts"][0]["fact"] == "Python é rápido"


def test_whitespace_extenso():
    result = parse_llm_json('   \n\n  {"key": "valor"}  \n  ')
    assert result == {"key": "valor"}


def test_fence_sem_quebra_de_linha():
    result = parse_llm_json('```json{"inline": true}```')
    assert result == {"inline": True}


def test_json_com_unicode():
    result = parse_llm_json('{"nome": "Sexta-feira", "emoji": "🤖"}')
    assert result["nome"] == "Sexta-feira"


def test_objeto_vazio():
    assert parse_llm_json('{}') == {}


def test_array_vazio():
    assert parse_llm_json('[]') == []


# ── Casos de falha ─────────────────────────────────────────────────────

def test_texto_sem_json_levanta_valueerror():
    with pytest.raises(ValueError, match="Nenhum JSON"):
        parse_llm_json("sem json nenhum aqui")


def test_texto_vazio_levanta_valueerror():
    with pytest.raises(ValueError, match="vazio"):
        parse_llm_json("")


def test_apenas_espaco_levanta_valueerror():
    with pytest.raises(ValueError, match="vazio"):
        parse_llm_json("   ")


def test_json_malformado_levanta_valueerror():
    with pytest.raises(ValueError):
        parse_llm_json("{broken: json, no quotes}")


def test_chave_sem_fechar_levanta_valueerror():
    with pytest.raises(ValueError):
        parse_llm_json('{"chave": "valor"')


def test_apenas_abre_chave_levanta_valueerror():
    with pytest.raises(ValueError):
        parse_llm_json("{")


# ── Casos realistas de resposta LLM ────────────────────────────────────

def test_resposta_extractor_completa():
    """Simula resposta do FactExtractor."""
    raw = """
Aqui estão os fatos extraídos da conversa:

```json
{
  "facts": [
    {"fact": "Usuário prefere Python", "category": "user_pref", "confidence": 0.85}
  ],
  "response_summary": "Discussão sobre preferências de linguagem."
}
```
"""
    result = parse_llm_json(raw)
    assert len(result["facts"]) == 1
    assert result["facts"][0]["category"] == "user_pref"


def test_resposta_search_queries():
    """Simula resposta de geração de queries de busca."""
    raw = '{"queries": ["python async best practices", "asyncio tutorial 2026"]}'
    result = parse_llm_json(raw)
    assert len(result["queries"]) == 2


def test_resposta_l3_params():
    """Simula resposta de extração de parâmetros L3."""
    raw = '{"element": "botão salvar", "text_to_type": null, "hotkey": ["ctrl", "s"]}'
    result = parse_llm_json(raw)
    assert result["hotkey"] == ["ctrl", "s"]
    assert result["text_to_type"] is None
