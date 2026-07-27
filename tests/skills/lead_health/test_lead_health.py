"""Tests for lead_health skill (QW-3)."""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


from src.core.goals.protocol import GoalStatus
from src.skills.lead_health.goal import (
    GHOSTING_DAYS,
    STALE_DAYS_BY_STAGE,
    URGENT_WINDOW_MAX,
    URGENT_WINDOW_MIN,
    LeadHealthCheck,
)


class TestLeadHealthCheck(unittest.TestCase):
    def setUp(self):
        self.pipeline = MagicMock()
        self.pipeline.memory = MagicMock()
        self.pipeline.memory._db = AsyncMock()
        self.goal = LeadHealthCheck(self.pipeline)

    def test_init(self):
        self.assertEqual(self.goal.name, "lead_health")
        self.assertEqual(self.goal._status, GoalStatus.IDLE)
        self.assertEqual(self.goal._budget.max_per_cycle_usd, 0.0)

    def test_channels(self):
        from src.core.goals.protocol import NotificationChannel
        self.assertEqual(self.goal.channels, [NotificationChannel.TELEGRAM])

    def test_interval_seconds_returns_positive(self):
        secs = self.goal.interval_seconds
        self.assertGreater(secs, 0)
        self.assertLessEqual(secs, 86400)  # max 1 day

    def test_stale_days_by_stage(self):
        """Confere thresholds do playbook."""
        self.assertEqual(STALE_DAYS_BY_STAGE["NOVO"], 60)
        self.assertEqual(STALE_DAYS_BY_STAGE["CONTATADO"], 45)
        self.assertEqual(STALE_DAYS_BY_STAGE["PROPOSTA"], 90)

    def test_urgent_window(self):
        """Confere janela 1-6m."""
        self.assertEqual(URGENT_WINDOW_MIN, 3)
        self.assertEqual(URGENT_WINDOW_MAX, 6)

    def test_ghosting_threshold(self):
        """Confere threshold de 14 dias."""
        self.assertEqual(GHOSTING_DAYS, 14)


class TestLeadHealthReport(unittest.TestCase):
    """Test report building (sem dependência de DB)."""

    def setUp(self):
        self.pipeline = MagicMock()
        self.pipeline.memory = MagicMock()
        self.pipeline.memory._db = AsyncMock()
        self.goal = LeadHealthCheck(self.pipeline)

    def test_build_report_empty(self):
        report = self.goal._build_report([], [], [], [])
        self.assertIn("Tudo saudável", report)
        self.assertIn("✅", report)

    def test_build_report_with_gelados(self):
        gelados = [{
            "cidade": "Goiânia", "estado": "GO",
            "status_from": "NOVO", "days_idle": 75,
            "valor_estimado": 200000,
        }]
        report = self.goal._build_report(gelados, [], [], [])
        self.assertIn("GELADO", report)
        self.assertIn("Goiânia", report)
        self.assertIn("75d", report)

    def test_build_report_with_urgent(self):
        urgent = [{
            "cidade": "Petrolina", "estado": "PE",
            "nome_evento": "Festa do Padre Cícero",
            "data_evento_ano": 2026, "data_evento_mes": 10,
            "status": "NOVO",
        }]
        report = self.goal._build_report([], urgent, [], [])
        self.assertIn("URGENTES", report)
        self.assertIn("Petrolina", report)
        self.assertIn("Festa do Padre Cícero", report)

    def test_build_report_with_ghosting(self):
        ghosting = [{
            "cidade": "Trindade", "estado": "GO",
            "status": "PROPOSTA", "days_since_activity": 21,
        }]
        report = self.goal._build_report([], [], ghosting, [])
        self.assertIn("ghosting", report)
        self.assertIn("Trindade", report)

    def test_build_report_with_rediscovery(self):
        rediscovery = [{
            "cidade": "Trindade", "estado": "GO",
            "nome_evento": "Festa de Aniversário",
            "days_gelado": 100,
        }]
        report = self.goal._build_report([], [], [], rediscovery)
        self.assertIn("re-discovery", report)
        self.assertIn("Trindade", report)


if __name__ == "__main__":
    unittest.main()