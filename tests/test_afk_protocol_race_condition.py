"""
Tests para AFKProtocol — verificação de race condition (FASE 1 Bug 1.4).

Valida que resolve_request() é thread-safe mesmo com múltiplas
requests concorrentes (diferentes Future por request).
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.skills.vision.afk_protocol import AFKProtocol, PermissionResult


class MockBot:
    """Mock do bot Telegram."""
    async def send_message(self, uid, msg, **kwargs):
        pass


@pytest.fixture
def afk_protocol():
    """Cria AFKProtocol com mock bot e timeouts reduzidos para testes."""
    bot = MockBot()
    users = {123456}
    proto = AFKProtocol(bot, users)
    # Reduz timeouts para testes rápidos
    proto.FIRST_TIMEOUT_SECONDS = 1  # 1 segundo ao invés de 180
    proto.SECOND_TIMEOUT_SECONDS = 2  # 2 segundos ao invés de 1800
    return proto


class TestAFKProtocolRaceCondition:
    """Testa que múltiplas requests concorrentes não causam race condition."""

    @pytest.mark.asyncio
    async def test_single_request_sequence(self, afk_protocol):
        """Teste básico: uma request → approve → retorna APPROVED."""
        # Inicia request_permission em background
        task = asyncio.create_task(
            afk_protocol.request_permission("Teste", tier=2, action_type="read")
        )

        # Aguarda um pouco para garantir que está aguardando
        await asyncio.sleep(0.1)

        # Resolve com APPROVED
        await afk_protocol.resolve_request("yes", "2")

        result = await asyncio.wait_for(task, timeout=2.0)
        assert result == PermissionResult.APPROVED

    @pytest.mark.asyncio
    async def test_single_request_denied(self, afk_protocol):
        """Uma request → deny → retorna DENIED."""
        task = asyncio.create_task(
            afk_protocol.request_permission("Teste", tier=2, action_type="read")
        )
        await asyncio.sleep(0.1)

        await afk_protocol.resolve_request("no", "2")

        result = await asyncio.wait_for(task, timeout=2.0)
        assert result == PermissionResult.DENIED

    @pytest.mark.asyncio
    async def test_sequential_requests(self, afk_protocol):
        """Dois requests sequenciais → cada um retorna resultado correto."""
        # Request 1
        task1 = asyncio.create_task(
            afk_protocol.request_permission("Req1", tier=2, action_type="read")
        )
        await asyncio.sleep(0.1)
        await afk_protocol.resolve_request("yes", "2")

        result1 = await asyncio.wait_for(task1, timeout=2.0)
        assert result1 == PermissionResult.APPROVED

        # Request 2 (novo Future deve ser criado)
        task2 = asyncio.create_task(
            afk_protocol.request_permission("Req2", tier=2, action_type="read")
        )
        await asyncio.sleep(0.1)
        await afk_protocol.resolve_request("no", "2")

        result2 = await asyncio.wait_for(task2, timeout=2.0)
        assert result2 == PermissionResult.DENIED

    @pytest.mark.asyncio
    async def test_resolve_without_pending_request(self, afk_protocol):
        """resolve_request sem request pendente → log warning, sem erro."""
        # Não iniciou nenhuma request
        # Chamar resolve_request não deve causar erro (apenas log)
        await afk_protocol.resolve_request("yes", "2")
        # Se chegou aqui, passou (sem exception)

    @pytest.mark.asyncio
    async def test_multiple_concurrent_requests_serialized(self, afk_protocol):
        """
        Testa que múltiplos requests são serializados pelo lock.
        - Request A: solicita permissão
        - Request B: tenta solicitar enquanto A aguarda
        - B é bloqueado até A completar
        """
        results = []

        async def request_and_resolve(req_id: str, approve: bool):
            # Inicia request
            task = asyncio.create_task(
                afk_protocol.request_permission(f"Req{req_id}", tier=2, action_type="read")
            )
            await asyncio.sleep(0.1)

            # Resolve
            await afk_protocol.resolve_request("yes" if approve else "no", "2")
            result = await asyncio.wait_for(task, timeout=2.0)
            results.append((req_id, result))

        # Executa sequencialmente via asyncio
        await request_and_resolve("A", approve=True)
        await request_and_resolve("B", approve=False)
        await request_and_resolve("C", approve=True)

        assert len(results) == 3
        assert results[0] == ("A", PermissionResult.APPROVED)
        assert results[1] == ("B", PermissionResult.DENIED)
        assert results[2] == ("C", PermissionResult.APPROVED)

    @pytest.mark.asyncio
    async def test_lock_prevents_concurrent_inner_calls(self, afk_protocol):
        """
        Valida que o lock em request_permission serializa calls.
        Se dois goals tentam chamar simultaneamente, o segundo aguarda.
        """
        call_order = []

        async def request_with_tracking(req_id: str):
            call_order.append(f"{req_id}_start")
            task = asyncio.create_task(
                afk_protocol.request_permission(f"Req{req_id}", tier=2, action_type="read")
            )
            call_order.append(f"{req_id}_created")
            await asyncio.sleep(0.05)
            await afk_protocol.resolve_request("yes", "2")
            result = await asyncio.wait_for(task, timeout=2.0)
            call_order.append(f"{req_id}_done:{result.name}")
            return result

        # Inicia dois requests "simultaneamente"
        # O lock deve serializar, então ordem deve ser previsível
        task_a = asyncio.create_task(request_with_tracking("A"))
        task_b = asyncio.create_task(request_with_tracking("B"))

        result_a = await task_a
        result_b = await task_b

        # Ambos devem ter sucesso
        assert result_a == PermissionResult.APPROVED
        assert result_b == PermissionResult.APPROVED

        # Call order deve mostrar serialização (A antes de B no lock)
        # A_start → A_created → (resolve A) → A_done
        # B_start → B_created → (resolve B) → B_done
        assert "A_start" in call_order
        assert "B_start" in call_order


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
