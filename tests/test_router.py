"""
Seeker.Bot — Testes do Cognitive Load Router
tests/test_router.py

Roda SEM api keys — o router é 100% regex + heurística.
Execute: pytest tests/test_router.py -v
"""

import pytest
from src.core.router.cognitive_load import (
    CognitiveLoadRouter,
    CognitiveDepth,
)


@pytest.fixture
def router():
    return CognitiveLoadRouter()


# ── REFLEX ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto,descricao", [
    ("ok", "confirmação simples"),
    ("sim", "confirmação sim"),
    ("bom dia", "saudação"),
    ("blz", "gíria de confirmação"),
    ("valeu!", "agradecimento"),
    ("status", "comando curto"),
    ("next", "navegação"),
    ("entendi", "acknowledgement"),
    ("que horas são?", "pergunta de hora"),
    ("que dia é hoje?", "pergunta de data"),
])
def test_reflex(router, texto, descricao):
    decision = router.route(texto)
    assert decision.depth == CognitiveDepth.REFLEX, (
        f"'{texto}' ({descricao}): esperado REFLEX, obtido {decision.depth.value}"
    )


# ── DELIBERATE ────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto,descricao", [
    ("como configuro o nginx?", "pergunta técnica simples"),
    ("me explica o que é RAG", "pergunta educacional"),
    ("corrige esse bug no meu código", "debug request"),
    ("qual a diferença entre MongoDB e PostgreSQL?", "comparação simples"),
    ("como funciona o asyncio?", "pergunta de como funciona"),
    ("explique JWT pra mim", "explicação técnica"),
])
def test_deliberate(router, texto, descricao):
    decision = router.route(texto)
    assert decision.depth == CognitiveDepth.DELIBERATE, (
        f"'{texto}' ({descricao}): esperado DELIBERATE, obtido {decision.depth.value}"
    )


# ── DEEP ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto,descricao", [
    ("ative o godmode", "god mode explícito"),
    ("god mode", "god mode em inglês"),
    ("potência máxima", "god mode alternativo"),
    ("vale a pena migrar de MongoDB pra PostgreSQL?", "decisão com trade-off"),
    ("analisa com tudo se devo usar K8s", "trigger de análise completa"),
    ("qual o risco de depender do free tier do Groq?", "análise de risco"),
    (
        "compara DeepSeek V3.2 vs GPT-5 pra uso agêntico considerando "
        "custo, latência e tool use. Quero trade-offs reais.",
        "comparação estratégica",
    ),
    ("red team: quais os pontos fracos da nossa arquitetura?", "red team"),
    ("quais são as consequências de mudar pra arquitetura event-driven?", "análise de consequências"),
    ("como funciona realmente o MCP da Anthropic?", "investigação profunda"),
    ("seeker investiga o Evidence Arbitrage", "seeker trigger"),
])
def test_deep(router, texto, descricao):
    decision = router.route(texto)
    assert decision.depth == CognitiveDepth.DEEP, (
        f"'{texto}' ({descricao}): esperado DEEP, obtido {decision.depth.value}"
    )


# ── GOD MODE ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "ative o godmode",
    "god mode ativado",
    "potência máxima",
    "análise completa disso",
])
def test_god_mode_ativa_deep_e_flag(router, texto):
    decision = router.route(texto)
    assert decision.god_mode is True, f"'{texto}': esperado god_mode=True"
    assert decision.depth == CognitiveDepth.DEEP


# ── WEB SEARCH ───────────────────────────────────────────────────────

@pytest.mark.parametrize("texto,esperado_web,descricao", [
    ("ok", False, "reflex não precisa de web"),
    ("como funciona recursão?", False, "conceito atemporal"),
    ("quem é o CEO da OpenAI atualmente?", True, "cargo atual"),
    ("qual o preço do Bitcoin hoje?", True, "cotação atual"),
    ("qual a última versão do LangGraph?", True, "versão/release"),
    ("o DeepSeek V3.2 já saiu?", True, "existência de produto"),
    ("quem ganhou as eleições?", True, "evento recente"),
    ("notícias sobre IA hoje", True, "notícias"),
    ("explica o que é attention mechanism", False, "conceito estabelecido"),
    ("o Manus ainda existe em 2026?", True, "existência + ano"),
])
def test_web_detection(router, texto, esperado_web, descricao):
    decision = router.route(texto)
    assert decision.needs_web == esperado_web, (
        f"'{texto}' ({descricao}): esperado needs_web={esperado_web}, "
        f"obtido {decision.needs_web}. Razão: {decision.reason}"
    )


# ── MÓDULOS FORÇADOS ─────────────────────────────────────────────────

def test_modulo_email(router):
    decision = router.route("me mostra meus emails não lidos")
    assert decision.forced_module == "email"


def test_modulo_vision(router):
    decision = router.route("tira um screenshot da tela")
    assert decision.forced_module == "vision"


# ── PROPRIEDADES DA DECISÃO ──────────────────────────────────────────

def test_decisao_sempre_tem_reason(router):
    for texto in ["ok", "como funciona?", "vale a pena migrar?"]:
        decision = router.route(texto)
        assert decision.reason, f"'{texto}': reason não pode ser vazio"


def test_router_conservador_na_duvida(router):
    """Inputs ambíguos devem subir de profundidade, nunca descer."""
    decision = router.route("analisa isso pra mim com cuidado")
    assert decision.depth in (CognitiveDepth.DELIBERATE, CognitiveDepth.DEEP)


def test_inputs_muito_curtos_sao_reflex(router):
    for texto in ["ok", "s", "!"]:
        decision = router.route(texto)
        assert decision.depth == CognitiveDepth.REFLEX
