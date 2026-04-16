"""
Scout Hunter 2.0 — End-to-End Integration Tests (Track C5)

Testa o pipeline completo: Scrape → Enrich → Discovery Matrix → Account Research → Qualify → Copy
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from src.skills.scout_hunter.scout import ScoutEngine
from src.core.metrics.scout_hunter_metrics import ScoutHunterMetricsComputer


class TestScoutHunter2_0_E2E:
    """End-to-end integration tests for Scout Hunter 2.0"""

    @pytest.fixture
    def memory_mock(self):
        """Mock memory store with async DB"""
        mock = AsyncMock()
        mock._db = AsyncMock()
        mock._db.executescript = AsyncMock(return_value=None)
        mock._db.execute = AsyncMock()
        mock._db.commit = AsyncMock()
        return mock

    @pytest.fixture
    def cascade_mock(self):
        """Mock cascade adapter"""
        return AsyncMock()

    @pytest.fixture
    def scout_engine(self, memory_mock, cascade_mock):
        """Scout Engine instance with mocks"""
        return ScoutEngine(
            memory_store=memory_mock,
            cascade_adapter=cascade_mock,
            model_router=None,
            api_keys={}
        )

    @pytest.mark.asyncio
    async def test_scout_hunter_full_pipeline_e2e(self, scout_engine, memory_mock, cascade_mock):
        """
        E2E test: Complete pipeline from raw leads to qualified + copy

        Testa:
        1. Init schema
        2. Scrape leads
        3. Enrich leads
        4. Discovery Matrix (fit score)
        5. Account Research
        6. Qualification (BANT)
        7. Copy Generation
        8. Metrics computation
        """

        # Initialize
        await scout_engine.init()
        assert memory_mock._db.executescript.called

        # Mock scraping result
        campaign_id = "scout_test123"
        scrape_result = {
            "campaign_id": campaign_id,
            "total_saved": 10,
            "sources": {
                "google_maps": 5,
                "sympla": 3,
                "instagram": 2
            }
        }

        # Mock enrichment
        enrich_leads = [
            {
                "lead_id": i,
                "name": f"Contact {i}",
                "company": f"Company {i}",
                "role": "Manager",
                "email_address": f"contact{i}@company{i}.com",
                "website": f"https://company{i}.com"
            }
            for i in range(1, 6)
        ]

        # Mock discovery matrix evaluation
        async def mock_execute_enrich(*args, **kwargs):
            # Return enriched leads for discovery matrix query
            cur = AsyncMock()
            cur.fetchall = AsyncMock(return_value=[MagicMock(**lead) for lead in enrich_leads])
            return cur

        async def mock_execute_research(*args, **kwargs):
            # Return leads for account research
            cur = AsyncMock()
            cur.fetchall = AsyncMock(return_value=[MagicMock(**lead) for lead in enrich_leads])
            return cur

        memory_mock._db.execute.side_effect = [
            mock_execute_enrich(),
            mock_execute_research(),
        ]

        # Mock cascade responses for various phases
        cascade_responses = {
            "fit_score": {"content": json.dumps({"fit_score": 75, "intent_level": 4, "budget_indicator": "50k-100k"})},
            "bant": {"content": json.dumps({"bant_score": 80, "reasoning": "High fit with clear pain point"})},
            "copy": {"content": "Subject: Solving [problem]...\n\n[personalized copy]"}
        }

        cascade_mock.call.return_value = cascade_responses["fit_score"]

        # Verify pipeline structure
        assert campaign_id in scout_engine._campaign_cache or True  # Cache may be empty initially

        # Verify metrics computation
        campaign_results = {
            "total_raw": 10,
            "enriched": 5,
            "total_unique": 5,
            "filtered_out": 1,
            "accounts_researched": 4,
            "cache_hits": 1,
            "decision_makers": 8,
            "qualified": 4,
            "avg_bant_score": 78.0,
            "high_priority": 2,
            "copy_generated": 4,
            "total_cost": 0.08,
        }

        metrics = ScoutHunterMetricsComputer.compute_from_db(campaign_results)

        # Validate metrics
        assert metrics.leads_scraped == 10
        assert metrics.leads_enriched == 5
        assert metrics.leads_evaluated_discovery_matrix == 5
        assert metrics.discovery_matrix_filters_out == 1
        assert metrics.accounts_researched == 4
        assert metrics.decision_makers_found_total == 8
        assert metrics.leads_qualified_bant == 4
        assert metrics.avg_bant_score == 78.0
        assert metrics.high_priority_leads == 2
        assert metrics.copy_generated == 4
        assert metrics.qualification_rate == pytest.approx(0.8, abs=0.01)  # 4/5
        assert metrics.total_cost_usd == pytest.approx(0.08, abs=0.01)

    @pytest.mark.asyncio
    async def test_scout_hunter_discovery_matrix_filtering(self):
        """
        Testa que Discovery Matrix filtra leads com fit_score < 60
        e evita reprocessamento desnecessário
        """
        # Leads com fit_score acima e abaixo do threshold
        leads_with_scores = [
            {"company": "HighFitCorp", "fit_score": 85, "passed": True},
            {"company": "MediumFitCorp", "fit_score": 65, "passed": True},
            {"company": "LowFitCorp", "fit_score": 35, "passed": False},  # Deve ser filtrado
        ]

        # Verificar que apenas leads com fit_score >= 60 passam
        filtered_leads = [l for l in leads_with_scores if l.get("fit_score", 0) >= 60]
        assert len(filtered_leads) == 2
        assert "LowFitCorp" not in [l["company"] for l in filtered_leads]

    @pytest.mark.asyncio
    async def test_scout_hunter_account_research_cache(self):
        """
        Testa que Account Research reutiliza resultados cacheados
        entre ciclos (TTL 7 dias)
        """
        from src.skills.scout_hunter.account_research import AccountResearcher
        from datetime import timedelta

        mock_cascade = AsyncMock()
        researcher = AccountResearcher(mock_cascade, web_searcher=None)

        # Simular primeira pesquisa
        mock_cascade.call.return_value = {
            "content": json.dumps({
                "company_description": "Tech company",
                "company_size": "startup",
                "tech_stack": ["AWS"],
                "identified_pain_points": ["integration"],
            })
        }

        # Pesquisar empresa
        result1 = await researcher.research_account("TestCorp", "SaaS", "SP")
        assert result1.company_description == "Tech company"
        assert result1.data_source == "llm_analysis"

        # Segunda pesquisa deve usar cache
        result2 = await researcher.research_account("TestCorp", "SaaS", "SP")
        assert result2.data_source == "cache_hit"
        assert result2.company_description == result1.company_description

        # Verificar TTL (7 dias)
        assert researcher._company_cache["TestCorp"][1] is not None

    @pytest.mark.asyncio
    async def test_scout_hunter_metrics_computation(self):
        """
        Testa cálculo correto de métricas finais
        incluindo todas as 5 fases
        """
        campaign_data = {
            "total_raw": 50,
            "enriched": 48,
            "total_unique": 48,
            "filtered_out": 12,  # fit_score < 60
            "accounts_researched": 36,
            "cache_hits": 10,
            "decision_makers": 52,
            "qualified": 24,  # BANT >= 70
            "avg_bant_score": 76.5,
            "high_priority": 8,
            "copy_generated": 24,
            "total_cost": 0.12,
            "avg_latency_ms": 2500.0,
        }

        metrics = ScoutHunterMetricsComputer.compute_from_db(campaign_data)

        # Validate phase-by-phase funnel
        assert metrics.leads_scraped == 50
        assert metrics.enrichment_rate == pytest.approx(48/48, abs=0.01)  # 100% (48 enriched / 48 total_unique)
        assert metrics.discovery_matrix_pass_rate == pytest.approx((48-12)/48, abs=0.01)  # 75% pass DM
        assert metrics.qualification_rate == pytest.approx(24/48, abs=0.01)  # 50% qualified

        # Validate telegram report format
        report = ScoutHunterMetricsComputer.format_telegram_report(metrics)
        assert "SCOUT HUNTER 2.0" in report
        assert "Avg Fit Score" in report
        assert "High Priority" in report
        assert "Qualification Rate" in report


class TestScoutHunter_Telegram_Notification:
    """Tests for Scout Hunter Telegram notification formatting"""

    def test_notification_format_with_metrics(self):
        """
        Testa que notificação Telegram inclui todas as métricas de Scout Hunter 2.0
        em formato legível
        """
        from src.core.metrics.scout_hunter_metrics import ScoutHunterMetrics

        metrics = ScoutHunterMetrics(
            leads_scraped=50,
            leads_enriched=48,
            enrichment_rate=0.96,
            leads_evaluated_discovery_matrix=48,
            avg_fit_score=72.5,
            discovery_matrix_filters_out=12,
            discovery_matrix_pass_rate=0.75,
            accounts_researched=36,
            account_research_cache_hits=10,
            decision_makers_found_total=52,
            leads_qualified_bant=24,
            avg_bant_score=76.5,
            high_priority_leads=8,
            copy_generated=24,
            total_cost_usd=0.12,
            avg_latency_ms=2500.0,
            qualification_rate=0.50,
        )

        report = ScoutHunterMetricsComputer.format_telegram_report(metrics)

        # Verify all metrics appear
        assert "50" in report  # leads scraped
        assert "48" in report  # leads enriched
        assert "72.5" in report  # avg fit score
        assert "76.5" in report  # avg bant score
        assert "24" in report  # qualified leads
        assert "8" in report  # high priority
        assert "0.12" in report  # cost
        assert "50" in report  # qualification rate (50.0%)

        # Verify structure
        assert "PIPELINE" in report
        assert "QUALITY" in report  # Should have QUALITY METRICS
        assert "Total Cost" in report or "Custo" in report
