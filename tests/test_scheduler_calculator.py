"""
Scheduler Conversacional — Testes do Calculator

Testa cálculo de próxima execução.
"""

import pytest
from datetime import datetime
import pytz

from src.skills.scheduler_conversacional.models import (
    ScheduledTask,
    ScheduleType,
)
from src.skills.scheduler_conversacional.calculator import NextRunCalculator


@pytest.fixture
def daily_task():
    """Tarefa diária às 14h"""
    return ScheduledTask(
        id="daily_1",
        title="Diária",
        schedule_type=ScheduleType.DAILY,
        hour=14,
    )


@pytest.fixture
def weekly_task():
    """Tarefa semanal (terça às 10h)"""
    return ScheduledTask(
        id="weekly_1",
        title="Semanal",
        schedule_type=ScheduleType.WEEKLY,
        hour=10,
        day_of_week=1,  # Terça
    )


@pytest.fixture
def monthly_task():
    """Tarefa mensal (dia 15 às 9h)"""
    return ScheduledTask(
        id="monthly_1",
        title="Mensal",
        schedule_type=ScheduleType.MONTHLY,
        hour=9,
        day_of_month=15,
    )


@pytest.fixture
def annual_task():
    """Tarefa anual (25/12 às 0h)"""
    return ScheduledTask(
        id="annual_1",
        title="Anual",
        schedule_type=ScheduleType.ANNUAL,
        hour=0,
        day_of_month=25,
        month=12,
    )


def test_daily_next_run(daily_task):
    """Testa próxima execução diária"""
    # Se for 12h, próxima é hoje às 14h
    from_time = datetime(2026, 4, 16, 12, 0, 0)  # 12h
    next_run = NextRunCalculator.calculate_next_run(daily_task, from_time)

    assert next_run.hour == 14
    assert next_run.day == 16

    # Se for 15h, próxima é amanhã às 14h
    from_time = datetime(2026, 4, 16, 15, 0, 0)  # 15h
    next_run = NextRunCalculator.calculate_next_run(daily_task, from_time)

    assert next_run.hour == 14
    assert next_run.day == 17


def test_weekly_next_run(weekly_task):
    """Testa próxima execução semanal"""
    # 2026-04-13 é segunda
    # Procura terça (dia_semana=1)

    from_time = datetime(2026, 4, 13, 9, 0, 0)  # Segunda 9h
    next_run = NextRunCalculator.calculate_next_run(weekly_task, from_time)

    assert next_run.hour == 10
    assert next_run.weekday() == 1  # Terça

    # Se for terça mas já passou a hora
    from_time = datetime(2026, 4, 14, 11, 0, 0)  # Terça 11h
    next_run = NextRunCalculator.calculate_next_run(weekly_task, from_time)

    assert next_run.hour == 10
    assert (next_run - from_time).days >= 6  # Próxima terça


def test_monthly_next_run(monthly_task):
    """Testa próxima execução mensal"""
    # Dia 15 do mês

    from_time = datetime(2026, 4, 10, 8, 0, 0)  # 10 de abril
    next_run = NextRunCalculator.calculate_next_run(monthly_task, from_time)

    assert next_run.day == 15
    assert next_run.month == 4
    assert next_run.hour == 9

    # Se for depois do dia 15
    from_time = datetime(2026, 4, 20, 8, 0, 0)  # 20 de abril
    next_run = NextRunCalculator.calculate_next_run(monthly_task, from_time)

    assert next_run.day == 15
    assert next_run.month == 5  # Próximo mês


def test_annual_next_run(annual_task):
    """Testa próxima execução anual"""
    # 25/12

    from_time = datetime(2026, 6, 1, 12, 0, 0)  # Junho
    next_run = NextRunCalculator.calculate_next_run(annual_task, from_time)

    assert next_run.day == 25
    assert next_run.month == 12
    assert next_run.year == 2026
    assert next_run.hour == 0

    # Se já passou 25/12
    from_time = datetime(2026, 12, 26, 12, 0, 0)  # 26 de dezembro
    next_run = NextRunCalculator.calculate_next_run(annual_task, from_time)

    assert next_run.day == 25
    assert next_run.month == 12
    assert next_run.year == 2027


def test_timezone_handling(daily_task):
    """Testa timezone corretamente"""
    daily_task.timezone = "America/Sao_Paulo"

    # Em UTC, pode ser dia diferente que em SP
    from_time = datetime(2026, 4, 16, 4, 0, 0)  # UTC 4h = SP 0h (meia-noite)
    next_run = NextRunCalculator.calculate_next_run(daily_task, from_time)

    # Próxima execução deve ser hoje às 14h no horário de SP
    # Que é 17h em UTC
    assert next_run.hour == 17  # 14h SP = 17h UTC (UTC-3)


def test_edge_case_february_29(monthly_task):
    """Testa caso limite: dia 29 em fevereiro (não-bissexto)"""
    task = ScheduledTask(
        id="feb29",
        title="29 de fevereiro",
        schedule_type=ScheduleType.MONTHLY,
        hour=12,
        day_of_month=29,
    )

    # 2027 não é bissexto, então 29/02 não existe
    # Deve usar 28 em fevereiro
    from_time = datetime(2027, 2, 1, 12, 0, 0)
    next_run = NextRunCalculator.calculate_next_run(task, from_time)

    # Deve ter encontrado um dia válido
    assert next_run is not None
