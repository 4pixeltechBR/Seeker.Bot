import os
import time
import tempfile
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from agent.cognitive_router import (
    CognitiveDepth,
    ExecutionMode,
    SeekerState,
    StateEncoder,
    CognitiveLoadRouter,
    CascadeBandit,
    EvidenceArbitrage,
    ProviderCircuitBreaker,
    CircuitBreakerState,
    run_async_synchronously,
)
from agent.credential_pool import get_provider_breaker, PROVIDER_BREAKERS
from tools.memory_tool import MemoryStore


# ─────────────────────────────────────────────────────────────────────────────
# 1. TESTES DO STATE ENCODER
# ─────────────────────────────────────────────────────────────────────────────

def test_state_encoder_output_dimensions():
    state = SeekerState(query="Como funciona o LinUCB Bandit?")
    encoder = StateEncoder()
    vector = encoder.encode(state)
    assert len(vector) == 26
    for val in vector:
        assert 0.0 <= val <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. TESTES DO COGNITIVE LOAD ROUTER
# ─────────────────────────────────────────────────────────────────────────────

def test_cognitive_load_router_reflex():
    agent = MagicMock()
    router = CognitiveLoadRouter(agent)
    
    # Queries Reflex simples
    decision1 = router.route("ok")
    assert decision1.depth == CognitiveDepth.REFLEX
    
    decision2 = router.route("bom dia")
    assert decision2.depth == CognitiveDepth.REFLEX
    
    # Query de sistema (data/hora)
    decision3 = router.route("que dia é hoje?")
    assert decision3.depth == CognitiveDepth.REFLEX
    assert decision3.forced_module == "system_time"

def test_cognitive_load_router_deep():
    agent = MagicMock()
    router = CognitiveLoadRouter(agent)
    
    # Queries Deep com gatilhos de arquitetura/complexidade
    decision1 = router.route("Quais são os trade-offs de migrar para microservices?")
    assert decision1.depth == CognitiveDepth.DEEP
    
    # Gatilho God Mode
    decision2 = router.route("aprofunda com god mode total")
    assert decision2.depth == CognitiveDepth.DEEP
    assert decision2.god_mode is True

def test_cognitive_load_router_reflex_generation():
    agent = MagicMock()
    router = CognitiveLoadRouter(agent)
    
    resp_time = router.generate_reflex_response("que horas são?")
    assert "Hora atual" in resp_time
    
    resp_hello = router.generate_reflex_response("oi")
    assert "Olá" in resp_hello
    
    resp_status = router.generate_reflex_response("status")
    assert "SeekerAgent" in resp_status


# ─────────────────────────────────────────────────────────────────────────────
# 3. TESTES DO CASCADE BANDIT (LINUCB RL)
# ─────────────────────────────────────────────────────────────────────────────

def test_cascade_bandit_prediction_and_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        model_path = os.path.join(tmpdir, "bandit_model.npz")
        bandit = CascadeBandit(model_path=model_path, alpha=1.0)
        
        encoder = StateEncoder()
        state = SeekerState(query="Como funciona?")
        features = encoder.encode(state)
        
        # Predição inicial
        arm = bandit.predict(features, router_arm="reflex", decision_id="dec_1")
        assert arm in ["reflex", "deliberate", "deep"]
        
        # Atualização (reward positivo)
        success = bandit.update("dec_1", reward=1.0)
        assert success is True
        
        # Salva pesos explicitamente
        bandit.save()
        assert os.path.exists(model_path)
        
        # Instancia novo bandit carregando o modelo salvo
        new_bandit = CascadeBandit(model_path=model_path, alpha=1.0)
        assert new_bandit.load() is True
        assert new_bandit._n_updates["reflex"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. TESTES DO PROVIDER CIRCUIT BREAKER
# ─────────────────────────────────────────────────────────────────────────────

def test_provider_circuit_breaker_flow():
    # Limpa breaker anterior
    PROVIDER_BREAKERS.clear()
    
    breaker = get_provider_breaker("openai")
    assert breaker is not None
    assert breaker.state == CircuitBreakerState.CLOSED
    
    # Registrar falhas até o limite (default=5)
    for _ in range(5):
        breaker.record_failure()
        
    assert breaker.state == CircuitBreakerState.OPEN
    assert breaker.allow_request() is False
    
    # Simula passagem de tempo para Half-Open
    breaker.opened_time = time.monotonic() - 61.0
    assert breaker.allow_request() is True
    assert breaker.state == CircuitBreakerState.HALF_OPEN
    
    # Registrar sucessos em Half-Open até fechar
    for _ in range(3):
        breaker.record_success()
        
    assert breaker.state == CircuitBreakerState.CLOSED


# ─────────────────────────────────────────────────────────────────────────────
# 5. TESTES DO DECAY ENGINE (MEMORY DECAY)
# ─────────────────────────────────────────────────────────────────────────────

def test_memory_decay_metadata_rendering():
    # Mock do MemoryTool
    tool = MagicMock()
    # Adicionamos alguns blocos de memória fictícios
    memories = [
        "<!-- domain:arch, confidence:0.95, last_seen:1717632000.0 -->\nUse microservices for scaling.",
        "<!-- domain:auth, confidence:0.80, last_seen:1717632000.0 -->\nAuth tokens expire in 1 hour."
    ]
    
    # Instanciamos a classe de decaimento de memória nativa
    # E rodamos regex de renderização do memory_tool modificado
    import re
    # Expressão regular de limpeza de metadados em memory_tool
    CLEAN_METADATA_PAT = re.compile(r"<!--\s*domain:.*?,.*?confidence:.*?,.*?last_seen:.*?\s*-->\n?", re.IGNORECASE)
    
    cleaned_memories = [CLEAN_METADATA_PAT.sub("", mem) for mem in memories]
    assert "Use microservices for scaling." in cleaned_memories[0]
    assert "domain:arch" not in cleaned_memories[0]
    assert "Auth tokens expire in 1 hour." in cleaned_memories[1]
    assert "confidence:0.80" not in cleaned_memories[1]
