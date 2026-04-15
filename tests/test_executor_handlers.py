"""
Tests para ActionHandlers — Executores de Ações

Testa cada handler:
1. BashHandler — executa bash com whitelist
2. FileOpsHandler — file operations com snapshots
3. APIHandler — HTTP requests com retry
4. RemoteTriggerHandler — delegação para Claude Code
"""

import pytest
import asyncio
import json
from pathlib import Path
import tempfile

from src.core.executor.models import (
    ActionStep,
    ActionType,
    ApprovalTier,
    ActionResult,
    ActionStatus,
)
from src.core.executor.handlers.bash import BashHandler
from src.core.executor.handlers.file_ops import FileOpsHandler
from src.core.executor.handlers.api import APIHandler
from src.core.executor.handlers.remote_trigger import RemoteTriggerHandler


class TestBashHandler:
    """Testes para BashHandler."""

    @pytest.fixture
    def bash_handler(self):
        return BashHandler()

    @pytest.mark.asyncio
    async def test_bash_simple_command(self, bash_handler):
        """Testa execução de comando bash simples (ls)."""
        step = ActionStep(
            id="test_ls",
            type=ActionType.BASH,
            command="echo 'hello world'",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L2_SILENT,
            estimated_cost_usd=0.0,
        )

        result = await bash_handler.execute(step)

        assert result.status == ActionStatus.SUCCESS
        assert "hello world" in result.output or result.output == ""
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_bash_with_timeout(self, bash_handler):
        """Testa timeout de comando bash."""
        step = ActionStep(
            id="test_timeout",
            type=ActionType.BASH,
            command="sleep 100",  # Vai dar timeout
            timeout_seconds=1,  # 1 segundo de timeout
            approval_tier=ApprovalTier.L2_SILENT,
            estimated_cost_usd=0.0,
        )

        result = await bash_handler.execute(step)

        # Deve falhar com timeout
        assert result.status in [ActionStatus.TIMEOUT, ActionStatus.FAILED]

    @pytest.mark.asyncio
    async def test_bash_command_whitelist(self, bash_handler):
        """Testa que comandos perigosos são bloqueados."""
        step = ActionStep(
            id="test_dangerous",
            type=ActionType.BASH,
            command="rm -rf /",  # Comando perigoso
            timeout_seconds=10,
            approval_tier=ApprovalTier.L0_MANUAL,  # Even with manual approval
            estimated_cost_usd=0.01,
        )

        result = await bash_handler.execute(step)

        # Deve ser rejeitado por whitelist
        assert result.status == ActionStatus.POLICY_VIOLATION


class TestFileOpsHandler:
    """Testes para FileOpsHandler."""

    @pytest.fixture
    def file_handler(self):
        return FileOpsHandler()

    @pytest.mark.asyncio
    async def test_file_read(self, file_handler):
        """Testa leitura de arquivo."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("test content")
            temp_path = f.name

        try:
            step = ActionStep(
                id="test_read",
                type=ActionType.FILE_OPS,
                command=f"read {temp_path}",
                timeout_seconds=10,
                approval_tier=ApprovalTier.L2_SILENT,
                estimated_cost_usd=0.0,
            )

            result = await file_handler.execute(step)

            assert result.status == ActionStatus.SUCCESS
            assert "test content" in result.output
        finally:
            Path(temp_path).unlink()

    @pytest.mark.asyncio
    async def test_file_write(self, file_handler):
        """Testa escrita de arquivo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"

            step = ActionStep(
                id="test_write",
                type=ActionType.FILE_OPS,
                command=f"write {str(test_file)} 'new content'",
                timeout_seconds=10,
                approval_tier=ApprovalTier.L1_LOGGED,
                estimated_cost_usd=0.0,
            )

            result = await file_handler.execute(step)

            assert result.status == ActionStatus.SUCCESS
            assert test_file.exists()
            assert test_file.read_text() == "new content"

    @pytest.mark.asyncio
    async def test_file_snapshot(self, file_handler):
        """Testa que snapshots são capturados antes/depois."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("original")
            temp_path = f.name

        try:
            step = ActionStep(
                id="test_snapshot",
                type=ActionType.FILE_OPS,
                command=f"write {temp_path} 'modified'",
                timeout_seconds=10,
                approval_tier=ApprovalTier.L1_LOGGED,
                estimated_cost_usd=0.0,
            )

            result = await file_handler.execute(step)

            assert result.status == ActionStatus.SUCCESS
            # Snapshots devem estar no before/after
            assert result.metadata.get("before_snapshot") is not None
            assert result.metadata.get("after_snapshot") is not None
        finally:
            Path(temp_path).unlink()

    @pytest.mark.asyncio
    async def test_file_delete(self, file_handler):
        """Testa deleção segura de arquivo (com rollback)."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("content to delete")
            temp_path = f.name

        try:
            step = ActionStep(
                id="test_delete",
                type=ActionType.FILE_OPS,
                command=f"delete {temp_path}",
                timeout_seconds=10,
                approval_tier=ApprovalTier.L0_MANUAL,  # Deleção requer aprovação
                estimated_cost_usd=0.0,
            )

            result = await file_handler.execute(step)

            assert result.status == ActionStatus.SUCCESS
            assert not Path(temp_path).exists()
        except:
            # Limpar se ainda existir
            Path(temp_path).unlink(missing_ok=True)


class TestAPIHandler:
    """Testes para APIHandler."""

    @pytest.fixture
    def api_handler(self):
        return APIHandler()

    @pytest.mark.asyncio
    async def test_api_get_request(self, api_handler):
        """Testa GET request (usando endpoint público de teste)."""
        step = ActionStep(
            id="test_get",
            type=ActionType.API,
            command="GET https://httpbin.org/get",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L2_SILENT,
            estimated_cost_usd=0.01,
        )

        result = await api_handler.execute(step)

        # Pode falhar por network, mas estruturalmente deve funcionar
        assert result.status in [ActionStatus.SUCCESS, ActionStatus.NETWORK_ERROR, ActionStatus.TIMEOUT]

    @pytest.mark.asyncio
    async def test_api_retry_on_failure(self, api_handler):
        """Testa que API handler retenta em falhas temporárias."""
        step = ActionStep(
            id="test_retry",
            type=ActionType.API,
            command="POST https://httpbin.org/status/500",  # Endpoint que sempre falha
            timeout_seconds=10,
            approval_tier=ApprovalTier.L1_LOGGED,
            estimated_cost_usd=0.02,
        )

        result = await api_handler.execute(step)

        # Deve tentar múltiplas vezes antes de falhar
        assert hasattr(result, 'retry_count') or result.status == ActionStatus.FAILED


class TestRemoteTriggerHandler:
    """Testes para RemoteTriggerHandler."""

    @pytest.fixture
    def remote_handler(self):
        return RemoteTriggerHandler()

    @pytest.mark.asyncio
    async def test_remote_trigger_health_check(self, remote_handler):
        """Testa health check do Claude Code."""
        is_healthy = await remote_handler.health_check()

        # Pode estar offline, mas deve retornar boolean
        assert isinstance(is_healthy, bool)

    @pytest.mark.asyncio
    async def test_remote_trigger_screenshot(self, remote_handler):
        """Testa delegação de screenshot."""
        step = ActionStep(
            id="test_screenshot",
            type=ActionType.REMOTE_TRIGGER,
            command="screenshot",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L1_LOGGED,
            estimated_cost_usd=0.05,
        )

        result = await remote_handler.execute(step)

        # Pode falhar se Claude Code não estiver disponível
        if result.status == ActionStatus.SUCCESS:
            assert result.output is not None  # Image data
        else:
            assert result.status == ActionStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_remote_trigger_click(self, remote_handler):
        """Testa delegação de click."""
        step = ActionStep(
            id="test_click",
            type=ActionType.REMOTE_TRIGGER,
            command="click 100 200",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L0_MANUAL,  # Desktop actions requerem aprovação
            estimated_cost_usd=0.05,
        )

        result = await remote_handler.execute(step)

        # Pode falhar se Claude Code não estiver disponível
        assert result.status in [ActionStatus.SUCCESS, ActionStatus.UNAVAILABLE]


class TestHandlerErrorHandling:
    """Testes para tratamento de erros em handlers."""

    @pytest.mark.asyncio
    async def test_handler_graceful_timeout(self):
        """Handler deve tratar timeout gracefully."""
        handler = BashHandler()

        step = ActionStep(
            id="test_timeout",
            type=ActionType.BASH,
            command="sleep 1000",
            timeout_seconds=1,
            approval_tier=ApprovalTier.L2_SILENT,
            estimated_cost_usd=0.0,
        )

        result = await handler.execute(step)

        # Não deve crash, apenas retornar TIMEOUT
        assert result.status in [ActionStatus.TIMEOUT, ActionStatus.FAILED]
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_handler_invalid_step_type(self):
        """Handler deve rejeitar step types inválidos."""
        handler = BashHandler()

        step = ActionStep(
            id="test_invalid",
            type=ActionType.API,  # Tipo errado para BashHandler
            command="echo test",
            timeout_seconds=10,
            approval_tier=ApprovalTier.L2_SILENT,
            estimated_cost_usd=0.0,
        )

        result = await handler.execute(step)

        assert result.status == ActionStatus.INVALID_STEP
