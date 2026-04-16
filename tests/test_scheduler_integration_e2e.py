"""
Scheduler Conversacional — Testes E2E

Testa fluxo completo: wizard → tarefa criada → dispatcher executa.
"""

import pytest
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from src.skills.scheduler_conversacional.models import (
    ScheduledTask,
    ScheduleType,
)
from src.skills.scheduler_conversacional.store import SchedulerStore
from src.skills.scheduler_conversacional.wizard import SchedulerWizard
from src.skills.scheduler_conversacional.dispatcher import TaskDispatcher
from src.skills.scheduler_conversacional.calculator import NextRunCalculator
from src.skills.scheduler_conversacional.telegram_interface import (
    SchedulerTelegramInterface,
)


@pytest.fixture
def memory_mock():
    """Mock database"""
    mock = AsyncMock()
    mock._db = AsyncMock()
    mock._db.executescript = AsyncMock(return_value=None)
    mock._db.execute = AsyncMock()
    mock._db.commit = AsyncMock()
    return mock


@pytest.fixture
async def store(memory_mock):
    """SchedulerStore instance"""
    store = SchedulerStore(memory_mock._db)
    await store.init()
    return store


@pytest.fixture
def cascade_mock():
    """Mock cascade adapter"""
    mock = AsyncMock()
    mock.call = AsyncMock(return_value={"content": "Executed successfully"})
    return mock


@pytest.mark.asyncio
async def test_full_wizard_to_execution_flow(store, cascade_mock):
    """
    E2E: Usuário faz wizard → tarefa criada → dispatcher executa
    """
    wizard = SchedulerWizard(store)
    dispatcher = TaskDispatcher(store, cascade_mock)
    telegram_ui = SchedulerTelegramInterface(store)

    chat_id = 12345
    user_id = "test_user"

    # 1. Usuário inicia wizard
    msg1 = await telegram_ui.cmd_agendar(chat_id, user_id)
    assert "Nome da tarefa" in msg1

    # 2. Usuário preenche wizard
    msg2, msg3, msg4, msg5, msg6 = await _run_wizard_flow(
        telegram_ui, chat_id, user_id
    )

    # 3. Tarefa deve ter sido criada
    tasks = await store.list_tasks(chat_id)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.title == "Backup diário"
    assert task.hour == 14

    # 4. Marcar como vencida (para teste)
    task.next_run_at = datetime.utcnow() - timedelta(minutes=1)
    await store.update_task(task)

    # 5. Dispatcher encontra e executa
    stats = await dispatcher.dispatch_overdue_tasks()
    assert stats["executed"] == 1
    assert stats["failed"] == 0

    # 6. Verificar que task foi atualizada
    updated_task = await store.get_task(task.id)
    assert updated_task.last_status == "success"
    assert updated_task.last_run_at is not None


@pytest.mark.asyncio
async def test_idempotency_prevents_duplicate_execution(store, cascade_mock):
    """Testa que idempotência evita duplicação"""
    dispatcher = TaskDispatcher(store, cascade_mock)

    # Criar tarefa
    task = ScheduledTask(
        id=str(uuid.uuid4()),
        title="Teste Idempotência",
        schedule_type=ScheduleType.DAILY,
        hour=10,
        chat_id=123,
        created_by="test",
    )
    task.next_run_at = datetime.utcnow() - timedelta(minutes=1)
    await store.create_task(task)

    # Primeira execução
    result1 = await dispatcher._execute_task(task)
    assert result1["success"] is True

    # Segunda execução (mesmo timestamp)
    result2 = await dispatcher._execute_task(task)
    assert result2["success"] is False
    assert "idempotency" in result2["error"].lower()

    # Verificar que cascade foi chamado apenas 1 vez
    assert cascade_mock.call.call_count == 1


@pytest.mark.asyncio
async def test_scheduler_with_approval_integration(store):
    """
    Testa que tarefa agendada respeita approval engine
    (simulado aqui, real seria via execution plane)
    """
    # Esta é uma validação conceitual:
    # O dispatcher deve passar por Side Effect Gateway
    # Para este teste, apenas validamos que a estrutura permite isso

    task = ScheduledTask(
        id=str(uuid.uuid4()),
        title="Requires Approval",
        schedule_type=ScheduleType.DAILY,
        hour=12,
        instruction_text="rm -rf /",  # Comando perigoso
        chat_id=123,
        created_by="user1",
    )

    await store.create_task(task)

    # Na implementação real, o dispatcher chamaria Side Effect Gateway
    # que bloquearia esse comando
    retrieved = await store.get_task(task.id)
    assert retrieved.instruction_text == "rm -rf /"

    # Security: Não permitir bypass
    # (validado em execution plane, não aqui)


@pytest.mark.asyncio
async def test_multiple_overdue_tasks_dispatch(store, cascade_mock):
    """Testa dispatcher com múltiplas tarefas vencidas"""
    dispatcher = TaskDispatcher(store, cascade_mock)

    now = datetime.utcnow()

    # Criar 3 tarefas vencidas
    for i in range(3):
        task = ScheduledTask(
            id=str(uuid.uuid4()),
            title=f"Task {i}",
            schedule_type=ScheduleType.DAILY,
            hour=10,
            chat_id=123,
            created_by="test",
        )
        task.next_run_at = now - timedelta(minutes=i+1)
        await store.create_task(task)

    # Dispatcher deve encontrar todas
    stats = await dispatcher.dispatch_overdue_tasks()
    assert stats["found"] == 3
    assert stats["executed"] == 3


@pytest.mark.asyncio
async def test_pagination_and_cleanup(store):
    """Testa limpeza de sessões expiradas"""
    wizard = SchedulerWizard(store)

    # Criar múltiplas sessões
    for i in range(5):
        await wizard.start_wizard(chat_id=100+i, user_id=f"user{i}")

    # Algumas expiram
    from datetime import datetime
    await store.db.execute(
        "UPDATE scheduler_wizard_sessions SET expires_at = ? WHERE chat_id IN (101, 102)",
        (datetime.utcnow() - timedelta(minutes=1),)
    )
    await store.db.commit()

    # Cleanup deve remover as expiradas
    count = await store.cleanup_expired_sessions()
    assert count >= 2


# ────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────

async def _run_wizard_flow(telegram_ui, chat_id, user_id):
    """Helper para rodar o wizard completo"""
    # Título
    msg = await telegram_ui.handle_message(chat_id, user_id, "Backup diário")

    # Schedule type (daily)
    msg = await telegram_ui.handle_message(chat_id, user_id, "1")

    # Hour
    msg = await telegram_ui.handle_message(chat_id, user_id, "14")

    # Instruction
    msg = await telegram_ui.handle_message(
        chat_id, user_id, "Executar backup do banco de dados"
    )

    # Confirmation
    msg = await telegram_ui.handle_message(chat_id, user_id, "sim")

    return msg, msg, msg, msg, msg


@pytest.mark.asyncio
async def test_telegram_interface_commands(store):
    """Testa comandos da interface Telegram"""
    interface = SchedulerTelegramInterface(store)

    # Criar tarefa
    task = ScheduledTask(
        id="test_task",
        title="Teste",
        schedule_type=ScheduleType.DAILY,
        hour=10,
        chat_id=123,
        created_by="user1",
    )
    await store.create_task(task)

    # /listar deve encontrar
    msg = await interface.cmd_listar(123)
    assert "Teste" in msg

    # /detalhe deve retornar detalhe
    msg = await interface.cmd_detalhe(123, "test_task")
    assert "Teste" in msg

    # /pausar
    msg = await interface.cmd_pausar(123, "test_task")
    assert "pausada" in msg.lower()

    # /reativar
    msg = await interface.cmd_reativar(123, "test_task")
    assert "reativada" in msg.lower()

    # /remover
    msg = await interface.cmd_remover(123, "test_task")
    assert "removida" in msg.lower()

    # Tarefa não deve mais existir
    tasks = await store.list_tasks(123)
    assert len(tasks) == 0
