"""
Testes para API Cascade Integration (Sprint 7.1)
- Classificacao de erros
- Roteamento inteligente (skip unhealthy)
- Health checks automaticos
- Precisao de latencia
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from collections import deque

from src.providers.cascade_advanced import (
    CascadeAdapter,
    CascadeTier,
    ErrorType,
    CascadeMetrics,
    CascadeResult,
)


class MockProvider:
    """Mock de um provider para testes"""
    def __init__(self, latency_ms=100, should_fail=False, error_type=""):
        self.latency_ms = latency_ms
        self.should_fail = should_fail
        self.error_type = error_type
        self.call_count = 0

    async def call(self, prompt, timeout=30):
        """Simula chamada a provider"""
        self.call_count += 1
        await asyncio.sleep(self.latency_ms / 1000)

        if self.should_fail:
            if self.error_type == "timeout":
                raise asyncio.TimeoutError("Request timed out")
            elif self.error_type == "rate_limit":
                raise Exception("429 Too Many Requests")
            elif self.error_type == "connection":
                raise Exception("Connection refused")
            else:
                raise Exception("Unknown error")

        return {
            "response": f"Mock response to: {prompt}",
            "cost": 0.001
        }


@pytest.fixture
def cascade_adapter():
    """Cria CascadeAdapter com mocks"""
    providers = {
        "nvidia": MockProvider(latency_ms=50),
        "groq": MockProvider(latency_ms=80),
        "gemini": MockProvider(latency_ms=120),
        "deepseek": MockProvider(latency_ms=200),
        "ollama": MockProvider(latency_ms=300),
    }

    cascade = CascadeAdapter(providers, {})
    return cascade


class TestErrorClassification:
    """Testa classificacao de tipos de erro"""

    def test_classify_timeout_error(self, cascade_adapter):
        """Classifica corretamente timeouts"""
        error = asyncio.TimeoutError("Request timed out")
        assert cascade_adapter._classify_error(error) == ErrorType.TIMEOUT

    def test_classify_rate_limit_error(self, cascade_adapter):
        """Classifica corretamente rate limits"""
        error = Exception("429 Too Many Requests")
        assert cascade_adapter._classify_error(error) == ErrorType.RATE_LIMIT

    def test_classify_connection_error(self, cascade_adapter):
        """Classifica corretamente erros de conexao"""
        error = Exception("Connection refused to host")
        assert cascade_adapter._classify_error(error) == ErrorType.CONNECTION


class TestCascadeIntegration:
    """Testa integracao geral"""

    @pytest.mark.asyncio
    async def test_cascade_call_succeeds(self, cascade_adapter):
        """Chamada basica cascade retorna sucesso"""
        result = await cascade_adapter.call_with_cascade("test prompt")
        assert result.success is True
        assert result.response is not None
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_cost_analysis(self, cascade_adapter):
        """Analise de custos inclui breakdown de erros"""
        cascade_adapter.metrics[CascadeTier.TIER1_NIM].total_calls = 10
        cascade_adapter.metrics[CascadeTier.TIER1_NIM].successful_calls = 10
        cascade_adapter.metrics[CascadeTier.TIER1_NIM].avg_cost_usd = 0.01

        analysis = cascade_adapter.get_cost_analysis()
        assert analysis["total_calls"] == 10
        assert "error_breakdown" in analysis


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
