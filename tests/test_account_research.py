"""
Testes unitários para Account Research (Scout C2)
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta

from src.skills.scout_hunter.account_research import (
    AccountResearcher,
    AccountResearchResult,
    DecisionMaker
)


class TestAccountResearch:
    """Testes de Account Research"""

    @pytest.fixture
    def cascade_adapter_mock(self):
        """Mock do cascade adapter"""
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def web_searcher_mock(self):
        """Mock do web searcher (opcional)"""
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def account_researcher(self, cascade_adapter_mock, web_searcher_mock):
        """Instância de AccountResearcher"""
        return AccountResearcher(cascade_adapter_mock, web_searcher_mock)

    @pytest.mark.asyncio
    async def test_research_account_success(self, account_researcher, cascade_adapter_mock):
        """Testa pesquisa bem-sucedida de conta"""

        cascade_adapter_mock.call.return_value = {
            "content": json.dumps({
                "company_description": "SaaS platform for event management",
                "company_size": "scaleup",
                "company_revenue_range": "1M-5M",
                "tech_stack": ["AWS", "Salesforce", "Stripe"],
                "identified_pain_points": ["integration_complexity", "cost_optimization"],
                "current_solution": "Manual processes + spreadsheets",
                "competitive_landscape": [
                    {"name": "Competitor A", "position": "market_leader"},
                    {"name": "Competitor B", "position": "niche_player"}
                ]
            })
        }

        result = await account_researcher.research_account(
            "TechCompany XYZ",
            industry="SaaS",
            region="sao_paulo"
        )

        assert result.company_description == "SaaS platform for event management"
        assert result.company_size == "scaleup"
        assert "AWS" in result.tech_stack
        assert "integration_complexity" in result.identified_pain_points
        assert result.data_source == "llm_analysis"

    @pytest.mark.asyncio
    async def test_research_account_cache_hit(self, account_researcher, cascade_adapter_mock, web_searcher_mock):
        """Testa que segunda pesquisa usa cache"""

        response = {
            "content": json.dumps({
                "company_description": "Test company",
                "company_size": "startup",
                "company_revenue_range": "0-1M",
                "tech_stack": ["AWS"],
                "identified_pain_points": ["growth"],
                "current_solution": "DIY",
                "competitive_landscape": []
            })
        }

        cascade_adapter_mock.call.return_value = response
        web_searcher_mock.search.return_value = []  # Mockar web search para evitar chamadas extras

        # Primeira pesquisa
        result1 = await account_researcher.research_account("TestCorp", "SaaS", "sao_paulo")
        assert result1.data_source == "llm_analysis"
        initial_call_count = cascade_adapter_mock.call.call_count

        # Segunda pesquisa (deve usar cache)
        result2 = await account_researcher.research_account("TestCorp", "SaaS", "sao_paulo")
        assert result2.data_source == "cache_hit"

        # LLM não deve ter sido chamado na segunda pesquisa (cache hit)
        assert cascade_adapter_mock.call.call_count == initial_call_count

    @pytest.mark.asyncio
    async def test_research_account_cache_expiry(self, account_researcher, cascade_adapter_mock, web_searcher_mock):
        """Testa que cache expira após TTL"""

        response = {
            "content": json.dumps({
                "company_description": "Test",
                "company_size": "startup",
                "company_revenue_range": "0-1M",
                "tech_stack": [],
                "identified_pain_points": [],
                "current_solution": "",
                "competitive_landscape": []
            })
        }

        cascade_adapter_mock.call.return_value = response
        web_searcher_mock.search.return_value = []  # Mockar web search

        # Primeira pesquisa
        await account_researcher.research_account("ExpiringCorp", "SaaS", "sao_paulo")

        # Manipular timestamp para simular expiração
        if "ExpiringCorp" in account_researcher._company_cache:
            result, _ = account_researcher._company_cache["ExpiringCorp"]
            # Forçar timestamp antigo (usar utcnow para consistência)
            old_time = datetime.utcnow() - timedelta(days=10)
            account_researcher._company_cache["ExpiringCorp"] = (result, old_time)

        initial_call_count = cascade_adapter_mock.call.call_count

        # Segunda pesquisa (deve refazer a pesquisa, não usar cache)
        result2 = await account_researcher.research_account("ExpiringCorp", "SaaS", "sao_paulo")
        assert result2.data_source == "llm_analysis"

        # LLM deve ter sido chamado novamente (cache expirou)
        assert cascade_adapter_mock.call.call_count > initial_call_count

    @pytest.mark.asyncio
    async def test_research_account_llm_error(self, account_researcher, cascade_adapter_mock):
        """Testa fallback quando LLM falha"""

        cascade_adapter_mock.call.side_effect = Exception("LLM timeout")

        result = await account_researcher.research_account("ErrorCorp", "SaaS", "sao_paulo")

        # Deve retornar resultado padrão
        assert result.company_description == "Company information not available"
        assert result.data_source == "fallback"

    def test_decision_maker_dataclass(self):
        """Testa DecisionMaker dataclass"""

        dm = DecisionMaker(
            name="João Silva",
            title="CTO",
            email="joao@company.com",
            linkedin_url="https://linkedin.com/in/joaosilva",
            influence_level="executive"
        )

        assert dm.name == "João Silva"
        assert dm.title == "CTO"
        assert dm.influence_level == "executive"

    def test_account_research_result_dataclass(self):
        """Testa AccountResearchResult dataclass"""

        result = AccountResearchResult(
            company_description="Tech company",
            company_size="scaleup",
            company_revenue_range="1M-5M",
            tech_stack=["AWS", "Salesforce"],
            identified_pain_points=["integration"],
            current_solution="Manual",
            competitive_landscape=[],
            decision_makers=[],
            data_source="llm_analysis",
            confidence_score=0.85
        )

        assert result.company_description == "Tech company"
        assert len(result.tech_stack) == 2
        assert result.confidence_score == 0.85

    def test_parse_analysis_response_valid(self, account_researcher):
        """Testa parsing de resposta de análise"""

        response = """{
            "company_description": "SaaS platform",
            "company_size": "enterprise",
            "company_revenue_range": "100M+",
            "tech_stack": ["Salesforce", "AWS", "Google Cloud"],
            "identified_pain_points": ["integration", "compliance", "cost"],
            "current_solution": "Manual + external tools",
            "competitive_landscape": [{"name": "CompA", "position": "leader"}]
        }"""

        result = account_researcher._parse_analysis_response("TestCorp", response)

        assert result.company_size == "enterprise"
        assert len(result.tech_stack) == 3
        assert len(result.identified_pain_points) == 3
        assert result.data_source == "llm_analysis"

    def test_parse_analysis_response_invalid_json(self, account_researcher):
        """Testa parsing com JSON inválido"""

        response = "This is not valid JSON at all"

        result = account_researcher._parse_analysis_response("BadCorp", response)

        # Deve retornar resultado padrão
        assert result.company_description == "Company information not available"
        assert result.data_source == "fallback"

    @pytest.mark.asyncio
    async def test_research_batch(self, account_researcher, cascade_adapter_mock):
        """Testa batch research de múltiplas empresas"""

        cascade_adapter_mock.call.return_value = {
            "content": json.dumps({
                "company_description": "Test company",
                "company_size": "startup",
                "company_revenue_range": "0-1M",
                "tech_stack": ["AWS"],
                "identified_pain_points": [],
                "current_solution": "",
                "competitive_landscape": []
            })
        }

        companies = [
            {"company_name": "Company A", "industry": "SaaS", "region": "SP"},
            {"company_name": "Company B", "industry": "Tech", "region": "RJ"},
            {"company_name": "Company C", "industry": "Finance", "region": "MG"},
        ]

        results = await account_researcher.research_batch(companies, max_concurrent=2)

        assert len(results) == 3
        assert all(name in results for name in ["Company A", "Company B", "Company C"])

    def test_cache_clear(self, account_researcher):
        """Testa limpeza de cache"""

        # Adicionar algo ao cache manualmente
        account_researcher._company_cache["test"] = (None, "time")

        assert len(account_researcher._company_cache) > 0

        account_researcher.clear_cache()

        assert len(account_researcher._company_cache) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
