"""
Testes para BatchOperationsManager — Sprint 11.3
Consolidação de commits em batch
"""

import pytest
import asyncio
from datetime import datetime

from src.core.batch_operations import (
    BatchOperationsManager,
    PendingOperation,
    BatchResult,
)


class TestBatchOperationsManager:
    """Testes de BatchOperationsManager"""

    @pytest.fixture
    def batch_manager(self):
        """Instância de gerenciador para testes"""
        return BatchOperationsManager(max_pending=10)

    @pytest.fixture
    async def mock_operation(self):
        """Operação mock"""
        async def operation():
            await asyncio.sleep(0.01)
            return "success"
        return operation

    def test_initialization(self, batch_manager):
        """Testa inicialização do gerenciador"""
        assert batch_manager.max_pending == 10
        assert batch_manager.get_pending_count() == 0
        assert batch_manager._is_committing is False

    def test_queue_single_operation(self, batch_manager, mock_operation):
        """Testa enfileir­amento de uma operação"""
        batch_manager.queue_operation(
            "test_operation",
            mock_operation,
        )

        assert batch_manager.get_pending_count() == 1

    def test_queue_multiple_operations(self, batch_manager, mock_operation):
        """Testa enfileiramento de múltiplas operações"""
        for i in range(5):
            batch_manager.queue_operation(
                f"operation_{i}",
                mock_operation,
            )

        assert batch_manager.get_pending_count() == 5

    @pytest.mark.asyncio
    async def test_commit_single_operation(self, batch_manager, mock_operation):
        """Testa commit de uma operação"""
        batch_manager.queue_operation("op1", mock_operation)

        result = await batch_manager.commit_all()

        assert result.total_operations == 1
        assert result.successful_operations == 1
        assert result.failed_operations == 0
        assert result.success_rate == 100.0
        assert batch_manager.get_pending_count() == 0

    @pytest.mark.asyncio
    async def test_commit_multiple_operations(self, batch_manager, mock_operation):
        """Testa commit de múltiplas operações"""
        for i in range(5):
            batch_manager.queue_operation(f"op_{i}", mock_operation)

        result = await batch_manager.commit_all()

        assert result.total_operations == 5
        assert result.successful_operations == 5
        assert result.failed_operations == 0
        assert batch_manager.get_pending_count() == 0

    @pytest.mark.asyncio
    async def test_commit_with_failures(self, batch_manager):
        """Testa commit com operações que falham"""
        async def failing_operation():
            raise RuntimeError("Operação falhou")

        async def successful_operation():
            return "ok"

        batch_manager.queue_operation("fail1", failing_operation)
        batch_manager.queue_operation("success1", successful_operation)
        batch_manager.queue_operation("fail2", failing_operation)

        result = await batch_manager.commit_all()

        assert result.total_operations == 3
        assert result.successful_operations == 1
        assert result.failed_operations == 2
        assert result.success_rate < 50

    @pytest.mark.asyncio
    async def test_commit_empty_queue(self, batch_manager):
        """Testa commit sem operações pendentes"""
        result = await batch_manager.commit_all()

        assert result.total_operations == 0
        assert result.successful_operations == 0
        assert result.failed_operations == 0

    @pytest.mark.asyncio
    async def test_concurrent_commit_protection(self, batch_manager, mock_operation):
        """Testa proteção contra commits concorrentes"""
        batch_manager.queue_operation("op1", mock_operation)
        batch_manager._is_committing = True

        # Tentar commit enquanto já está commitando
        result = await batch_manager.commit_all()

        assert result.total_operations == 0
        assert batch_manager.get_pending_count() == 1

    @pytest.mark.asyncio
    async def test_auto_commit_on_max_pending(self, batch_manager, mock_operation):
        """Testa que queue avisa quando max_pending é atingido"""
        # Preencher até max_pending
        for i in range(10):
            batch_manager.queue_operation(f"op_{i}", mock_operation)

        assert batch_manager.get_pending_count() == 10

    def test_clear_pending(self, batch_manager, mock_operation):
        """Testa limpeza de operações pendentes"""
        for i in range(5):
            batch_manager.queue_operation(f"op_{i}", mock_operation)

        assert batch_manager.get_pending_count() == 5

        cleared = batch_manager.clear_pending()

        assert cleared == 5
        assert batch_manager.get_pending_count() == 0

    @pytest.mark.asyncio
    async def test_batch_stats_tracking(self, batch_manager, mock_operation):
        """Testa rastreamento de estatísticas"""
        # Primeiro batch
        for i in range(3):
            batch_manager.queue_operation(f"op_{i}", mock_operation)

        result1 = await batch_manager.commit_all()

        assert batch_manager.stats["total_batches"] == 1
        assert batch_manager.stats["total_operations"] == 3

        # Segundo batch
        for i in range(2):
            batch_manager.queue_operation(f"op_{i}", mock_operation)

        result2 = await batch_manager.commit_all()

        assert batch_manager.stats["total_batches"] == 2
        assert batch_manager.stats["total_operations"] == 5

    def test_get_stats(self, batch_manager):
        """Testa retorno de estatísticas"""
        stats = batch_manager.get_stats()

        assert "total_batches" in stats
        assert "total_operations" in stats
        assert "success_rate_percent" in stats
        assert "avg_batch_latency_ms" in stats

    def test_health_status_healthy(self, batch_manager, mock_operation):
        """Testa status de saúde com carga baixa"""
        for i in range(2):
            batch_manager.queue_operation(f"op_{i}", mock_operation)

        status = batch_manager.get_health_status()

        assert status["health"] == "HEALTHY"
        assert status["pending_operations"] == 2
        assert status["utilization_percent"] == "20.0%"

    def test_health_status_warning(self, batch_manager, mock_operation):
        """Testa status de saúde com carga média"""
        for i in range(7):
            batch_manager.queue_operation(f"op_{i}", mock_operation)

        status = batch_manager.get_health_status()

        assert status["health"] == "WARNING"
        assert status["utilization_percent"] == "70.0%"

    def test_health_status_critical(self, batch_manager, mock_operation):
        """Testa status de saúde com carga alta"""
        for i in range(9):
            batch_manager.queue_operation(f"op_{i}", mock_operation)

        status = batch_manager.get_health_status()

        assert status["health"] == "CRITICAL"
        assert status["utilization_percent"] == "90.0%"

    @pytest.mark.asyncio
    async def test_operation_latency(self, batch_manager):
        """Testa medição de latência"""
        async def slow_operation():
            await asyncio.sleep(0.05)

        batch_manager.queue_operation("slow", slow_operation)

        result = await batch_manager.commit_all()

        # Deve ter levado pelo menos 50ms
        assert result.total_latency_ms >= 50

    @pytest.mark.asyncio
    async def test_commit_transaction(self, batch_manager, mock_operation):
        """Testa commit com nome de transação"""
        batch_manager.queue_operation("op1", mock_operation)

        result = await batch_manager.commit_transaction("test_transaction")

        assert result.successful_operations == 1
        assert batch_manager.stats["total_batches"] == 1

    @pytest.mark.asyncio
    async def test_operation_order_preserved(self, batch_manager):
        """Testa que operações são executadas em ordem"""
        execution_order = []

        async def track_operation(name):
            execution_order.append(name)

        batch_manager.queue_operation("first", track_operation, "first")
        batch_manager.queue_operation("second", track_operation, "second")
        batch_manager.queue_operation("third", track_operation, "third")

        await batch_manager.commit_all()

        assert execution_order == ["first", "second", "third"]


class TestPendingOperation:
    """Testes de PendingOperation"""

    @pytest.mark.asyncio
    async def test_pending_operation_execution(self):
        """Testa execução de operação pendente"""
        async def async_func(x, y):
            return x + y

        op = PendingOperation(
            operation_name="add",
            operation_func=async_func,
            args=(3, 4),
        )

        result = await op.execute()
        assert result == 7

    @pytest.mark.asyncio
    async def test_pending_operation_with_kwargs(self):
        """Testa operação com keyword arguments"""
        async def async_func(a, b=10):
            return a * b

        op = PendingOperation(
            operation_name="multiply",
            operation_func=async_func,
            args=(5,),
            kwargs={"b": 3},
        )

        result = await op.execute()
        assert result == 15


class TestBatchResult:
    """Testes de BatchResult"""

    def test_batch_result_success_rate(self):
        """Testa cálculo de taxa de sucesso"""
        result = BatchResult(
            total_operations=10,
            successful_operations=8,
            failed_operations=2,
            total_latency_ms=100.0,
        )

        assert result.success_rate == 80.0

    def test_batch_result_zero_operations(self):
        """Testa com zero operações"""
        result = BatchResult(
            total_operations=0,
            successful_operations=0,
            failed_operations=0,
            total_latency_ms=0.0,
        )

        assert result.success_rate == 0.0


# Run: pytest tests/test_batch_operations.py -v
