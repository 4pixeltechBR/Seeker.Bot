"""
Seeker.Bot — Bug Analyzer Integration Tests
tests/test_bug_analyzer_integration.py

Testes de integração para o sistema de análise de bugs.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from src.skills.bug_analyzer import (
    BugAnalyzer,
    BugAnalyzerTelegramInterface,
    ContextCollector,
    BugReport,
    ChatMessage,
    TerminalLine,
)
from src.skills.bug_analyzer.models import AnalysisPhase


class MockCascadeAdapter:
    """Mock do cascade adapter para testes"""

    async def call(self, messages, model_role=None, temperature=0.3, max_tokens=2048):
        """Retorna análise mock"""
        return {
            "content": """{
                "root_cause": "Bot timeout devido ao watchdog heartbeat",
                "summary": "Scheduler não atualiza heartbeat regularmente",
                "findings": [
                    {
                        "category": "timeout_issue",
                        "severity": "critical",
                        "description": "watchdog matando bot por inatividade",
                        "affected_file": "src/core/goals/scheduler.py",
                        "confidence": 0.9
                    }
                ],
                "suggestions": [
                    {
                        "file_path": "src/core/goals/scheduler.py",
                        "current_code": "# Missing heartbeat update",
                        "suggested_code": "self._write_heartbeat()",
                        "explanation": "Atualizar heartbeat para watchdog detectar",
                        "risk_level": "low"
                    }
                ]
            }""",
            "model_id": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        }


class MockModelRouter:
    """Mock do model router"""

    def get(self, role):
        return MagicMock(display_name="Mock Model")


@pytest.mark.asyncio
async def test_context_collection():
    """Testa coleta de contexto"""
    collector = ContextCollector()

    chat_history = [
        {"timestamp": "10:00:00", "text": "Bot travou", "is_user": True},
        {"timestamp": "10:01:00", "text": "Reintentando...", "is_user": False},
    ]

    report = await collector.collect_context(
        "Bot não está reiniciando",
        chat_history,
        user_id="test_user",
    )

    assert isinstance(report, BugReport)
    assert report.bug_description == "Bot não está reiniciando"
    assert report.user_id == "test_user"
    assert len(report.chat_history) <= 5


@pytest.mark.asyncio
async def test_bug_analysis():
    """Testa análise de bug com mock"""
    cascade = MockCascadeAdapter()
    router = MockModelRouter()
    analyzer = BugAnalyzer(cascade, router)

    chat_history = [
        {"timestamp": "10:00:00", "text": "Bug: bot trava", "is_user": True},
    ]

    analysis = await analyzer.analyze_bug(
        "Bot não reinicia quando há crash",
        chat_history,
        user_id="test_user",
    )

    assert analysis is not None
    assert analysis.phase == AnalysisPhase.COMPLETE
    assert len(analysis.findings) > 0
    assert len(analysis.suggestions) > 0
    assert analysis.root_cause != ""


@pytest.mark.asyncio
async def test_bug_analyzer_telegram_interface():
    """Testa interface Telegram do bug analyzer"""
    cascade = MockCascadeAdapter()
    router = MockModelRouter()
    analyzer = BugAnalyzer(cascade, router)
    ui = BugAnalyzerTelegramInterface(analyzer)

    # Testa cmd_bug
    msg = await ui.cmd_bug(12345, "user_123")
    assert "Descreva o bug" in msg
    assert ui.is_in_wizard(12345)

    # Testa process_bug_input
    response, is_complete = await ui.process_bug_input(
        12345,
        "Bot não reinicia após crash",
        [],
    )
    assert "Coletando contexto" in response

    # Testa cmd_bug_cancel
    msg = await ui.cmd_bug_cancel(12345)
    assert "cancelada" in msg
    assert not ui.is_in_wizard(12345)


@pytest.mark.asyncio
async def test_wizard_state_transitions():
    """Testa transições de estado do wizard"""
    cascade = MockCascadeAdapter()
    router = MockModelRouter()
    analyzer = BugAnalyzer(cascade, router)
    ui = BugAnalyzerTelegramInterface(analyzer)

    chat_id = 54321

    # Inicia
    from src.skills.bug_analyzer.telegram_interface import BugWizardState

    await ui.cmd_bug(chat_id, "user_456")
    assert ui.get_session_state(chat_id) == BugWizardState.ASKING_DESCRIPTION

    # Fornece descrição
    response, _ = await ui.process_bug_input(
        chat_id, "Problema X acontece quando...", []
    )
    assert ui.get_session_state(chat_id) == BugWizardState.COLLECTING_CONTEXT

    # Continua com input vazio (simula análise)
    response, is_complete = await ui.process_bug_input(
        chat_id, "", []
    )
    assert is_complete


def test_chat_message_creation():
    """Testa criação de ChatMessage"""
    msg = ChatMessage(
        timestamp="2026-04-16T10:30:00",
        user_id="user_123",
        text="Test message",
        is_user=True,
    )

    assert msg.timestamp == "2026-04-16T10:30:00"
    assert msg.user_id == "user_123"
    assert msg.is_user is True


def test_terminal_line_error_detection():
    """Testa detecção de erro em TerminalLine"""
    error_line = TerminalLine(
        timestamp="10:30:00",
        line="ERROR: Database connection failed",
        is_error=True,
    )

    assert error_line.is_error is True
    assert error_line.is_warning is False
    assert "ERROR" in error_line.line


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
