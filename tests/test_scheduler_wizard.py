"""
Scheduler Conversacional — Testes do Wizard

Testa o state machine do wizard conversacional.
"""

import pytest
from datetime import datetime, timedelta

from src.skills.scheduler_conversacional.models import (
    WizardSession,
    WizardState,
    ScheduleType,
)
from src.skills.scheduler_conversacional.store import SchedulerStore
from src.skills.scheduler_conversacional.wizard import SchedulerWizard


@pytest.fixture
def memory_mock():
    """Mock database"""
    from unittest.mock import AsyncMock
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
def wizard(store):
    """SchedulerWizard instance"""
    return SchedulerWizard(store)


@pytest.mark.asyncio
async def test_wizard_start(wizard):
    """Testa início do wizard"""
    session = await wizard.start_wizard(chat_id=123, user_id="user1")

    assert session.chat_id == 123
    assert session.user_id == "user1"
    assert session.state == WizardState.COLLECTING_TITLE
    assert session.expires_at is not None


@pytest.mark.asyncio
async def test_wizard_collect_title(wizard):
    """Testa coleta de título"""
    session = await wizard.start_wizard(chat_id=123, user_id="user1")

    # Título válido
    success, msg, updated = await wizard.collect_input(123, "Backup diário")
    assert success is True
    assert updated.state == WizardState.COLLECTING_SCHEDULE_TYPE
    assert updated.get_collected_value("title") == "Backup diário"

    # Título muito curto
    session2 = await wizard.start_wizard(chat_id=456, user_id="user2")
    success, msg, updated = await wizard.collect_input(456, "ab")
    assert success is False
    assert "muito curto" in msg.lower()


@pytest.mark.asyncio
async def test_wizard_collect_schedule_type(wizard):
    """Testa coleta de tipo de agendamento"""
    session = await wizard.start_wizard(chat_id=123, user_id="user1")

    # Coletar título primeiro
    await wizard.collect_input(123, "Minha tarefa")

    # Escolher daily
    success, msg, updated = await wizard.collect_input(123, "1")
    assert success is True
    assert updated.get_collected_value("schedule_type") == "daily"
    assert updated.state == WizardState.COLLECTING_HOUR


@pytest.mark.asyncio
async def test_wizard_collect_schedule_weekly(wizard):
    """Testa coleta de agendamento semanal"""
    await wizard.start_wizard(chat_id=123, user_id="user1")

    # Título
    await wizard.collect_input(123, "Semanal")

    # Weekly
    success, msg, updated = await wizard.collect_input(123, "2")
    assert success is True
    assert updated.state == WizardState.COLLECTING_DAY_OF_WEEK

    # Day of week
    success, msg, updated = await wizard.collect_input(123, "2")  # Terça
    assert success is True
    assert updated.get_collected_value("day_of_week") == 2
    assert updated.state == WizardState.COLLECTING_HOUR


@pytest.mark.asyncio
async def test_wizard_collect_hour(wizard):
    """Testa coleta de hora"""
    await wizard.start_wizard(chat_id=123, user_id="user1")

    # Título
    await wizard.collect_input(123, "Tarefa")

    # Daily
    await wizard.collect_input(123, "1")

    # Hour
    success, msg, updated = await wizard.collect_input(123, "14")
    assert success is True
    assert updated.get_collected_value("hour") == 14
    assert updated.state == WizardState.COLLECTING_INSTRUCTION

    # Hour inválido
    await wizard.start_wizard(chat_id=456, user_id="user2")
    await wizard.collect_input(456, "Outra")
    await wizard.collect_input(456, "1")
    success, msg, _ = await wizard.collect_input(456, "25")
    assert success is False


@pytest.mark.asyncio
async def test_wizard_collect_instruction(wizard):
    """Testa coleta de instrução"""
    await wizard.start_wizard(chat_id=123, user_id="user1")

    # Preencher até instrução
    await wizard.collect_input(123, "Tarefa")
    await wizard.collect_input(123, "1")
    await wizard.collect_input(123, "9")

    # Instrução válida
    success, msg, updated = await wizard.collect_input(123, "Executar backup do banco")
    assert success is True
    assert updated.state == WizardState.CONFIRMATION
    assert updated.get_collected_value("instruction_text") == "Executar backup do banco"


@pytest.mark.asyncio
async def test_wizard_confirmation(wizard):
    """Testa confirmação final"""
    await wizard.start_wizard(chat_id=123, user_id="user1")

    # Preencher tudo
    await wizard.collect_input(123, "Backup")
    await wizard.collect_input(123, "1")
    await wizard.collect_input(123, "3")

    # Chegar em confirmation
    success, msg, _ = await wizard.collect_input(123, "Executar backup")
    assert success is True

    # Confirmar
    success, msg, updated = await wizard.collect_input(123, "sim")
    assert success is True
    assert updated.state == WizardState.COMPLETED

    # Cancelar wizard novo
    await wizard.start_wizard(chat_id=456, user_id="user2")
    await wizard.collect_input(456, "Task")
    await wizard.collect_input(456, "1")
    await wizard.collect_input(456, "5")
    await wizard.collect_input(456, "Instr")

    success, msg, updated = await wizard.collect_input(456, "não")
    assert success is True
    assert updated is None  # Sessão foi deletada


@pytest.mark.asyncio
async def test_wizard_back_step(wizard):
    """Testa voltar um passo"""
    await wizard.start_wizard(chat_id=123, user_id="user1")

    # Preencher alguns passos
    await wizard.collect_input(123, "Tarefa")
    success, msg, updated = await wizard.collect_input(123, "1")
    assert updated.state == WizardState.COLLECTING_HOUR

    # Voltar
    success, msg, updated = await wizard.back_step(123)
    assert success is True
    assert updated.state == WizardState.COLLECTING_SCHEDULE_TYPE


@pytest.mark.asyncio
async def test_wizard_cancel(wizard):
    """Testa cancelamento"""
    await wizard.start_wizard(chat_id=123, user_id="user1")

    msg = await wizard.cancel_wizard(123)
    assert "cancelado" in msg.lower()

    # Wizard não existe mais
    session = await wizard.get_session(123)
    assert session is None


@pytest.mark.asyncio
async def test_wizard_expiration(wizard):
    """Testa expiração de sessão"""
    session = await wizard.start_wizard(chat_id=123, user_id="user1")

    # Forçar expiração
    session.expires_at = datetime.utcnow() - timedelta(minutes=1)
    await wizard.store.update_wizard_session(session)

    # Tentar usar
    retrieved = await wizard.get_session(123)
    assert retrieved is None  # Sessão foi deletada por estar expirada
