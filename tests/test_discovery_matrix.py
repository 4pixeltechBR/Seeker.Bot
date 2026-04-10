"""
Testes unitários para Discovery Matrix (Scout C1)
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.skills.scout_hunter.discovery_matrix import (
    DiscoveryMatrix,
    DiscoveryMatrixResult
)


class TestDiscoveryMatrix:
    """Testes de Discovery Matrix"""

    @pytest.fixture
    def cascade_adapter_mock(self):
        """Mock do cascade adapter"""
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def discovery_matrix(self, cascade_adapter_mock):
        """Instância de DiscoveryMatrix para testes"""
        return DiscoveryMatrix(cascade_adapter_mock)

    @pytest.fixture
    def sample_lead(self):
        """Lead de exemplo para testes"""
        return {
            "lead_id": 1,
            "name": "João Silva",
            "company": "Tech Startup XYZ",
            "role": "CEO",
            "industry": "SaaS",
            "location": "São Paulo",
            "bio_summary": "Building event management platform",
            "source_url": "https://example.com",
            "email_address": "joao@techxyz.com",
            "website": "https://techxyz.com"
        }

    @pytest.mark.asyncio
    async def test_evaluate_lead_success(self, discovery_matrix, cascade_adapter_mock, sample_lead):
        """Testa avaliação bem-sucedida de um lead"""

        # Mock resposta do cascade adapter
        cascade_adapter_mock.call.return_value = {
            "content": json.dumps({
                "fit_score": 78,
                "fit_score_reasoning": "Tech SaaS company, perfect fit",
                "intent_signals_level": 4,
                "intent_signals_evidence": ["hiring_active", "recent_funding"],
                "budget_indicator": "50k-100k"
            })
        }

        result = await discovery_matrix.evaluate_lead(
            sample_lead,
            niche="eventos",
            region="sao_paulo"
        )

        assert result.fit_score == 78
        assert result.intent_signals_level == 4
        assert result.budget_indicator == "50k-100k"
        assert result.passed_minimum_threshold == True  # fit >= 60

    @pytest.mark.asyncio
    async def test_evaluate_lead_below_threshold(self, discovery_matrix, cascade_adapter_mock, sample_lead):
        """Testa avaliação com fit_score < 60 (deve ser filtrado)"""

        cascade_adapter_mock.call.return_value = {
            "content": json.dumps({
                "fit_score": 45,
                "fit_score_reasoning": "Not a great fit",
                "intent_signals_level": 1,
                "intent_signals_evidence": [],
                "budget_indicator": "10k-50k"
            })
        }

        result = await discovery_matrix.evaluate_lead(sample_lead, "eventos", "goiania")

        assert result.fit_score == 45
        assert result.passed_minimum_threshold == False  # fit < 60

    @pytest.mark.asyncio
    async def test_evaluate_lead_llm_error(self, discovery_matrix, cascade_adapter_mock, sample_lead):
        """Testa fallback quando LLM falha"""

        cascade_adapter_mock.call.side_effect = Exception("LLM timeout")

        result = await discovery_matrix.evaluate_lead(sample_lead, "eventos", "goiania")

        # Deve retornar resultado padrão conservador
        assert result.fit_score == 50
        assert result.intent_signals_level == 2

    def test_parse_llm_response_valid_json(self, discovery_matrix):
        """Testa parsing de resposta JSON válida"""

        response = """{
            "fit_score": 82,
            "fit_score_reasoning": "Good fit",
            "intent_signals_level": 3,
            "intent_signals_evidence": ["hiring"],
            "budget_indicator": "100k-500k"
        }"""

        result = discovery_matrix._parse_llm_response(response)

        assert result.fit_score == 82
        assert result.intent_signals_level == 3

    def test_parse_llm_response_invalid_json(self, discovery_matrix):
        """Testa parsing com JSON inválido (deve retornar padrão)"""

        response = "Some text that's not JSON at all"

        result = discovery_matrix._parse_llm_response(response)

        # Deve retornar resultado padrão
        assert result.fit_score == 50

    def test_fit_score_clamping(self, discovery_matrix):
        """Testa que fit_score é clamped 0-100"""

        # Score > 100
        response = '{"fit_score": 150, "intent_signals_level": 3, "budget_indicator": "50k-100k"}'
        result = discovery_matrix._parse_llm_response(response)
        assert result.fit_score == 100

        # Score < 0
        response = '{"fit_score": -50, "intent_signals_level": 3, "budget_indicator": "50k-100k"}'
        result = discovery_matrix._parse_llm_response(response)
        assert result.fit_score == 0

    def test_intent_signals_clamping(self, discovery_matrix):
        """Testa que intent_signals é clamped 0-5"""

        # Signals > 5
        response = '{"fit_score": 70, "intent_signals_level": 10, "budget_indicator": "50k-100k"}'
        result = discovery_matrix._parse_llm_response(response)
        assert result.intent_signals_level == 5

        # Signals < 0
        response = '{"fit_score": 70, "intent_signals_level": -1, "budget_indicator": "50k-100k"}'
        result = discovery_matrix._parse_llm_response(response)
        assert result.intent_signals_level == 0

    @pytest.mark.asyncio
    async def test_evaluate_batch(self, discovery_matrix, cascade_adapter_mock):
        """Testa batch evaluation de múltiplos leads"""

        # Mock resposta
        cascade_adapter_mock.call.return_value = {
            "content": json.dumps({
                "fit_score": 70,
                "fit_score_reasoning": "Good",
                "intent_signals_level": 3,
                "intent_signals_evidence": [],
                "budget_indicator": "50k-100k"
            })
        }

        leads = [
            {"lead_id": 1, "name": "Lead1", "company": "Company1"},
            {"lead_id": 2, "name": "Lead2", "company": "Company2"},
            {"lead_id": 3, "name": "Lead3", "company": "Company3"},
        ]

        results = await discovery_matrix.evaluate_batch(leads, "eventos", "goiania", batch_size=2)

        assert len(results) == 3
        assert all(lead_id in results for lead_id in [1, 2, 3])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# Import json para os testes
import json
