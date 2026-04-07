"""
Seeker.Bot — Testes de Confidence Decay
tests/test_decay.py

Cobre as 3 funções puras do decay engine:
  detect_domain, time_decay_factor, effective_confidence
"""

import math
import time
import pytest

from src.core.evidence.decay import (
    Domain,
    DOMAIN_HALF_LIFE,
    detect_domain,
    time_decay_factor,
    verification_multiplier,
    effective_confidence,
)


# ── detect_domain ─────────────────────────────────────────────────────

def test_detect_domain_crypto():
    assert detect_domain("bitcoin subiu hoje") == Domain.CRYPTO
    assert detect_domain("cotação do ethereum em reais") == Domain.CRYPTO


def test_detect_domain_news():
    assert detect_domain("notícia de ontem sobre eleição") == Domain.NEWS


def test_detect_domain_tech_api():
    assert detect_domain("Groq free tier tem rate limit de 30 RPM") == Domain.TECH_API
    assert detect_domain("nova versão da API do Gemini") == Domain.TECH_API


def test_detect_domain_tech_arch():
    assert detect_domain("arquitetura de microserviços") == Domain.TECH_ARCH


def test_detect_domain_science():
    assert detect_domain("paper publicado no arxiv sobre LLMs") == Domain.SCIENCE


def test_detect_domain_business():
    assert detect_domain("startup levantou funding série A") == Domain.BUSINESS


def test_detect_domain_history():
    assert detect_domain("Python foi criado em 1991 por Guido") == Domain.HISTORY


def test_detect_domain_geral_sem_keywords():
    assert detect_domain("resposta aleatória sem contexto") == Domain.GENERAL


def test_detect_domain_prioriza_mais_keywords():
    """Texto com mais keywords de crypto do que news → crypto."""
    text = "bitcoin ethereum crypto token cotação breaking news"
    result = detect_domain(text)
    assert result == Domain.CRYPTO


def test_detect_domain_case_insensitive():
    assert detect_domain("BITCOIN subiu") == Domain.CRYPTO
    assert detect_domain("Paper ARXIV 2026") == Domain.SCIENCE


# ── time_decay_factor ─────────────────────────────────────────────────

def test_time_decay_fator_1_para_agora():
    now = time.time()
    factor = time_decay_factor(now, Domain.GENERAL)
    assert factor == pytest.approx(1.0, abs=0.01)


def test_time_decay_fator_reduz_com_tempo():
    now = time.time()
    old = now - (30 * 86400)  # 30 dias atrás
    fator_novo = time_decay_factor(now, Domain.GENERAL)
    fator_antigo = time_decay_factor(old, Domain.GENERAL)
    assert fator_antigo < fator_novo


def test_time_decay_half_life_correto():
    """Após exatamente 1 half-life, o fator deve ser ~0.5."""
    half_life_dias = DOMAIN_HALF_LIFE[Domain.TECH_API]  # 30 dias
    ts = time.time() - (half_life_dias * 86400)
    factor = time_decay_factor(ts, Domain.TECH_API)
    assert factor == pytest.approx(0.5, abs=0.02)


def test_time_decay_crypto_decai_rapido():
    """Crypto com 7 dias deve ter fator menor que tech_arch com 7 dias."""
    ts = time.time() - (7 * 86400)
    fator_crypto = time_decay_factor(ts, Domain.CRYPTO)
    fator_arch = time_decay_factor(ts, Domain.TECH_ARCH)
    assert fator_crypto < fator_arch


def test_time_decay_historia_decai_lento():
    """História com 100 dias ainda deve ter fator alto (>0.9)."""
    ts = time.time() - (100 * 86400)
    factor = time_decay_factor(ts, Domain.HISTORY)
    assert factor > 0.9


def test_time_decay_aceita_domain_como_string():
    now = time.time()
    factor_str = time_decay_factor(now, "crypto")
    factor_enum = time_decay_factor(now, Domain.CRYPTO)
    assert factor_str == pytest.approx(factor_enum, abs=0.001)


def test_time_decay_string_invalida_usa_general():
    now = time.time()
    factor_invalido = time_decay_factor(now, "nao_existe")
    factor_general = time_decay_factor(now, Domain.GENERAL)
    assert factor_invalido == pytest.approx(factor_general, abs=0.001)


def test_time_decay_timestamp_futuro_retorna_1():
    futuro = time.time() + 86400
    factor = time_decay_factor(futuro, Domain.GENERAL)
    assert factor == 1.0


# ── verification_multiplier ───────────────────────────────────────────

def test_verification_multiplier_depth_0():
    assert verification_multiplier(0) == pytest.approx(0.70)


def test_verification_multiplier_depth_1():
    assert verification_multiplier(1) == pytest.approx(0.85)


def test_verification_multiplier_depth_2():
    assert verification_multiplier(2) == pytest.approx(0.93)


def test_verification_multiplier_depth_3():
    assert verification_multiplier(3) == pytest.approx(1.00)


def test_verification_multiplier_depth_invalido():
    """Depth desconhecido usa fallback 0.4."""
    assert verification_multiplier(99) == pytest.approx(0.4)


# ── effective_confidence ──────────────────────────────────────────────

def test_effective_confidence_basico():
    now = time.time()
    conf = effective_confidence(0.8, now, verification_depth=3, domain=Domain.HISTORY)
    assert conf == pytest.approx(0.8, abs=0.02)


def test_effective_confidence_minimo_0_05():
    """Mesmo com fato muito antigo e não verificado, mínimo é 0.05."""
    muito_antigo = time.time() - (99999 * 86400)
    conf = effective_confidence(0.1, muito_antigo, verification_depth=0, domain=Domain.CRYPTO)
    assert conf >= 0.05


def test_effective_confidence_maximo_0_95():
    """Máximo é 0.95 mesmo com base 1.0, recente e verificado."""
    now = time.time()
    conf = effective_confidence(1.0, now, verification_depth=3, domain=Domain.HISTORY)
    assert conf <= 0.95


def test_effective_confidence_penalty_verificacao():
    """Fato não verificado (depth=0) deve ter confiança menor."""
    now = time.time()
    conf_v0 = effective_confidence(0.8, now, verification_depth=0)
    conf_v3 = effective_confidence(0.8, now, verification_depth=3)
    assert conf_v0 < conf_v3


def test_effective_confidence_decai_com_tempo():
    now = time.time()
    antigo = now - (90 * 86400)  # 90 dias
    conf_novo = effective_confidence(0.8, now, verification_depth=2, domain=Domain.TECH_API)
    conf_antigo = effective_confidence(0.8, antigo, verification_depth=2, domain=Domain.TECH_API)
    assert conf_antigo < conf_novo
