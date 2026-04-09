"""
Testes para CascadeAdapter — Sprint 11.1
Validação de fallback inteligente com 6 tiers
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from src.providers.cascade_advanced import (
    CascadeAdapter,
    CascadeTier,
    CascadeMetrics,
    CascadeResult,
)


class MockProvider:
    """Mock de um provider para testes"""

    def __init__(self, name: str, cost: float, latency_ms: int, fail_count: int = 0):
        self.name = name
        self.cost = cost
        self.latency_ms = latency_ms
        self.fail_count = fail_count
        self.call_count = 0

    async def call(self, prompt: str, timeout: int = 30) -> dict:
        """Simula uma chamada LLM"""
        self.call_count += 1

        if self.fail_count > 0:
            self.fail_count -= 1
            raise RuntimeError(f"{self.name} failed (simulated)")

        await asyncio.sleep(self.latency_ms / 1000)

        return {
            "response": f"Response from {self.name}: {prompt[:30]}...",
            "cost": self.cost,
        }


class TestCascadeAdapter:
    """Testes de CascadeAdapter"""

    @pytest.fixture
    def mock_providers(self):
        """Providers mock para testes"""
        return {
            "nvidia": MockProvider("NVIDIA", cost=0.01, latency_ms=100),
            "groq": MockProvider("Groq", cost=0.005, latency_ms=150),
            "gemini": MockProvider("Gemini", cost=0.003, latency_ms=200),
            "deepseek": MockProvider("DeepSeek", cost=0.001, latency_ms=250),
            "ollama": MockProvider("Ollama", cost=0.0, latency_ms=500),
        }

    @pytest.fixture
    def cascade(self, mock_providers):
        """Instância de CascadeAdapter para testes"""
        return CascadeAdapter(
            providers_dict=mock_providers,
            api_keys={"test": "key"},
        )

    @pytest.mark.asyncio
    async def test_cascade_successful_on_first_tier(self, cascade, mock_providers):
        """Testa sucesso na primeira tentativa"""
        result = await cascade.call_with_cascade(
            prompt="Test prompt",
            role="DEEP",
        )

        assert result.success
        assert result.tier_used == CascadeTier.TIER1_NIM
        assert "NVIDIA" in result.response
        assert result.cost_usd == 0.01
        assert result.fallbacks_triggered == 0
        assert mock_providers["nvidia"].call_count == 1

    @pytest.mark.asyncio
    async def test_cascade_fallback_on_failure(self, cascade, mock_providers):
        """Testa fallback quando primeiro tier falha"""
        # NVIDIA falha 1 vez, Groq sucede
        mock_providers["nvidia"].fail_count = 1

        result = await cascade.call_with_cascade(
            prompt="Test prompt",
            role="DEEP",
        )

        assert result.success
        assert result.tier_used == CascadeTier.TIER2_GROQ
        assert result.fallbacks_triggered == 1
        assert "Groq" in result.response

    @pytest.mark.asyncio
    async def test_cascade_multiple_fallbacks(self, cascade, mock_providers):
        """Testa múltiplos fallbacks em cascata"""
        # NVIDIA e Groq falham, Gemini sucede
        mock_providers["nvidia"].fail_count = 1
        mock_providers["groq"].fail_count = 1

        result = await cascade.call_with_cascade(
            prompt="Test prompt",
            role="DEEP",
        )

        assert result.success
        assert result.tier_used == CascadeTier.TIER3_GEMINI
        assert result.fallbacks_triggered == 2
        assert "Gemini" in result.response

    @pytest.mark.asyncio
    async def test_cascade_degraded_mode_fallback(self, cascade, mock_providers):
        """Testa fallback para modo degradado quando todos falham"""
        # Todos os providers falham
        for provider in mock_providers.values():
            provider.fail_count = 999  # Sempre falha

        result = await cascade.call_with_cascade(
            prompt="Test prompt",
            role="DEEP",
        )

        assert result.tier_used == CascadeTier.TIER6_DEGRADED
        assert "MODO DEGRADADO" in result.response
        assert result.cost_usd == 0.0
        assert result.fallbacks_triggered == 5  # Todos os 5 tiers anteriores falharam

    def test_cascade_metrics_tracking(self, cascade, mock_providers):
        """Testa rastreamento de métricas"""
        metrics = cascade.metrics[CascadeTier.TIER1_NIM]

        assert metrics.total_calls == 0
        assert metrics.success_rate == 0.0

        # Simular sucesso
        metrics.successful_calls = 5
        metrics.total_calls = 5

        assert metrics.success_rate == 100.0
        assert metrics.is_healthy

        # Simular falhas
        metrics.failed_calls = 3
        metrics.total_calls = 8

        assert metrics.success_rate == 62.5
        assert not metrics.is_healthy

    def test_cascade_health_status(self, cascade):
        """Testa status de saúde do cascade"""
        # Inicialmente todos saudáveis
        status = cascade.get_health_status()

        assert status["overall_health"] == "GOOD"
        assert "tiers" in status
        assert len(status["tiers"]) == 6

        # Simular falhas múltiplas (setando os valores base)
        cascade.metrics[CascadeTier.TIER1_NIM].successful_calls = 1
        cascade.metrics[CascadeTier.TIER1_NIM].total_calls = 20

        cascade.metrics[CascadeTier.TIER2_GROQ].successful_calls = 1
        cascade.metrics[CascadeTier.TIER2_GROQ].total_calls = 20

        cascade.metrics[CascadeTier.TIER3_GEMINI].successful_calls = 1
        cascade.metrics[CascadeTier.TIER3_GEMINI].total_calls = 20

        status = cascade.get_health_status()
        assert status["overall_health"] == "CRITICAL"

    def test_cascade_cost_analysis(self, cascade, mock_providers):
        """Testa análise de custos e economia"""
        # Simular histórico de chamadas
        cascade.metrics[CascadeTier.TIER1_NIM].total_calls = 10
        cascade.metrics[CascadeTier.TIER1_NIM].avg_cost_usd = 0.01

        cascade.metrics[CascadeTier.TIER2_GROQ].total_calls = 20
        cascade.metrics[CascadeTier.TIER2_GROQ].avg_cost_usd = 0.005

        analysis = cascade.get_cost_analysis()

        assert "total_cost_usd" in analysis
        assert "estimated_savings_vs_nim" in analysis
        assert analysis["total_calls"] == 30

    @pytest.mark.asyncio
    async def test_cascade_role_determines_start_tier(self, cascade, mock_providers):
        """Testa que role determina o tier de início"""
        # FAST deve começar em Groq (Tier 2)
        result = await cascade.call_with_cascade(
            prompt="Test prompt",
            role="FAST",
        )
        assert result.tier_used == CascadeTier.TIER2_GROQ

        # BALANCED deve começar em Gemini (Tier 3)
        cascade.call_history.clear()
        result = await cascade.call_with_cascade(
            prompt="Test prompt",
            role="BALANCED",
        )
        assert result.tier_used == CascadeTier.TIER3_GEMINI

        # DEEP deve começar em NIM (Tier 1)
        cascade.call_history.clear()
        result = await cascade.call_with_cascade(
            prompt="Test prompt",
            role="DEEP",
        )
        assert result.tier_used == CascadeTier.TIER1_NIM

    @pytest.mark.asyncio
    async def test_cascade_call_history(self, cascade, mock_providers):
        """Testa que histórico de chamadas é registrado"""
        assert len(cascade.call_history) == 0

        await cascade.call_with_cascade(prompt="Test 1", role="DEEP")
        assert len(cascade.call_history) == 1

        await cascade.call_with_cascade(prompt="Test 2", role="DEEP")
        assert len(cascade.call_history) == 2

        # History tem maxlen=100
        first_call = cascade.call_history[0]
        assert isinstance(first_call, CascadeResult)

    def test_cascade_timeout_per_tier(self, cascade):
        """Testa que cada tier tem timeout configurado"""
        timeouts = cascade.tier_timeouts

        assert timeouts[CascadeTier.TIER1_NIM] == 15
        assert timeouts[CascadeTier.TIER2_GROQ] == 20
        assert timeouts[CascadeTier.TIER3_GEMINI] == 25
        assert timeouts[CascadeTier.TIER4_DEEPSEEK] == 30
        assert timeouts[CascadeTier.TIER5_OLLAMA] == 60
        assert timeouts[CascadeTier.TIER6_DEGRADED] == 0

    @pytest.mark.asyncio
    async def test_cascade_latency_measurement(self, cascade, mock_providers):
        """Testa medição de latência"""
        result = await cascade.call_with_cascade(
            prompt="Test prompt",
            role="DEEP",
        )

        assert result.latency_ms > 0
        assert result.latency_ms >= mock_providers["nvidia"].latency_ms


class TestCascadeMetrics:
    """Testes de CascadeMetrics"""

    def test_metrics_success_rate(self):
        """Testa cálculo de taxa de sucesso"""
        metrics = CascadeMetrics(tier=CascadeTier.TIER1_NIM)

        assert metrics.success_rate == 0.0

        metrics.successful_calls = 8
        metrics.total_calls = 10

        assert metrics.success_rate == 80.0

    def test_metrics_is_healthy(self):
        """Testa avaliação de saúde"""
        metrics = CascadeMetrics(tier=CascadeTier.TIER1_NIM)

        # Menos de 3 calls = saudável por padrão
        assert metrics.is_healthy

        # 95% de sucesso = saudável
        metrics.successful_calls = 19
        metrics.total_calls = 20
        assert metrics.is_healthy

        # 85% de sucesso = NÃO saudável
        metrics.successful_calls = 17
        metrics.total_calls = 20
        assert not metrics.is_healthy

        # Com erro recente = NÃO saudável
        metrics.successful_calls = 19
        metrics.total_calls = 20
        metrics.last_error_time = datetime.utcnow()
        assert not metrics.is_healthy

        # Com erro antigo (> 30s) = saudável novamente
        metrics.last_error_time = datetime.utcnow() - timedelta(seconds=31)
        assert metrics.is_healthy


class TestCascadeResult:
    """Testes de CascadeResult"""

    def test_cascade_result_creation(self):
        """Testa criação de resultado"""
        result = CascadeResult(
            response="Test response",
            tier_used=CascadeTier.TIER2_GROQ,
            latency_ms=150.5,
            cost_usd=0.005,
            success=True,
            fallbacks_triggered=1,
        )

        assert result.response == "Test response"
        assert result.tier_used == CascadeTier.TIER2_GROQ
        assert result.latency_ms == 150.5
        assert result.cost_usd == 0.005
        assert result.success
        assert result.fallbacks_triggered == 1


# Run tests with: pytest tests/test_cascade_adapter.py -v
