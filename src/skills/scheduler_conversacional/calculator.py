"""
Scheduler Conversacional — NextRunCalculator

Calcula a próxima execução de uma tarefa agendada.
"""

import logging
from datetime import datetime, timedelta
import pytz

from src.skills.scheduler_conversacional.models import ScheduledTask, ScheduleType

log = logging.getLogger("seeker.scheduler.calculator")


class NextRunCalculator:
    """Calcula próxima execução de tarefas agendadas"""

    @staticmethod
    def calculate_next_run(task: ScheduledTask, from_time: datetime = None) -> datetime:
        """
        Calcula próxima execução de uma tarefa

        Args:
            task: ScheduledTask
            from_time: referência de tempo (default: agora em UTC)

        Returns:
            datetime: próxima execução em UTC
        """
        if from_time is None:
            from_time = datetime.utcnow()

        # Converter para timezone da tarefa para cálculo
        tz = pytz.timezone(task.timezone)
        from_time_tz = from_time.replace(tzinfo=pytz.UTC).astimezone(tz)

        if task.schedule_type == ScheduleType.DAILY:
            return NextRunCalculator._next_daily(task, from_time_tz, tz)

        elif task.schedule_type == ScheduleType.WEEKLY:
            return NextRunCalculator._next_weekly(task, from_time_tz, tz)

        elif task.schedule_type == ScheduleType.MONTHLY:
            return NextRunCalculator._next_monthly(task, from_time_tz, tz)

        elif task.schedule_type == ScheduleType.ANNUAL:
            return NextRunCalculator._next_annual(task, from_time_tz, tz)

        else:
            raise ValueError(f"Tipo de agendamento desconhecido: {task.schedule_type}")

    @staticmethod
    def _next_daily(task: ScheduledTask, from_time_tz, tz) -> datetime:
        """Próxima execução diária"""
        # Cria datetime com a hora especificada TODAY
        next_run_tz = from_time_tz.replace(hour=task.hour, minute=0, second=0, microsecond=0)

        # Se já passou, vai pro próximo dia
        if next_run_tz <= from_time_tz:
            next_run_tz += timedelta(days=1)

        # Converter de volta para UTC
        return next_run_tz.astimezone(pytz.UTC).replace(tzinfo=None)

    @staticmethod
    def _next_weekly(task: ScheduledTask, from_time_tz, tz) -> datetime:
        """Próxima execução semanal"""
        target_day = task.day_of_week  # 0-6 (segunda-domingo)

        # Encontra próxima ocorrência do dia da semana
        days_ahead = (target_day - from_time_tz.weekday()) % 7

        # Se é hoje e já passou a hora, vai próxima semana
        if days_ahead == 0:
            next_run_tz = from_time_tz.replace(hour=task.hour, minute=0, second=0, microsecond=0)
            if next_run_tz <= from_time_tz:
                days_ahead = 7

        next_run_tz = from_time_tz + timedelta(days=days_ahead)
        next_run_tz = next_run_tz.replace(hour=task.hour, minute=0, second=0, microsecond=0)

        # Converter de volta para UTC
        return next_run_tz.astimezone(pytz.UTC).replace(tzinfo=None)

    @staticmethod
    def _next_monthly(task: ScheduledTask, from_time_tz, tz) -> datetime:
        """Próxima execução mensal"""
        target_day = task.day_of_month  # 1-31

        # Tenta no mês atual
        try:
            next_run_tz = from_time_tz.replace(
                day=target_day, hour=task.hour, minute=0, second=0, microsecond=0
            )
        except ValueError:
            # Dia inválido para este mês (ex: 31/fev)
            # Usar último dia do mês
            next_month = from_time_tz + timedelta(days=32)
            last_day = (next_month.replace(day=1) - timedelta(days=1)).day
            next_run_tz = from_time_tz.replace(
                day=min(target_day, last_day),
                hour=task.hour,
                minute=0,
                second=0,
                microsecond=0,
            )

        # Se já passou, vai próximo mês
        if next_run_tz <= from_time_tz:
            # Avançar para próximo mês
            if from_time_tz.month == 12:
                next_month = from_time_tz.replace(year=from_time_tz.year + 1, month=1)
            else:
                next_month = from_time_tz.replace(month=from_time_tz.month + 1)

            try:
                next_run_tz = next_month.replace(
                    day=target_day, hour=task.hour, minute=0, second=0, microsecond=0
                )
            except ValueError:
                last_day = (next_month + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                next_run_tz = next_month.replace(
                    day=min(target_day, last_day.day),
                    hour=task.hour,
                    minute=0,
                    second=0,
                    microsecond=0,
                )

        # Converter de volta para UTC
        return next_run_tz.astimezone(pytz.UTC).replace(tzinfo=None)

    @staticmethod
    def _next_annual(task: ScheduledTask, from_time_tz, tz) -> datetime:
        """Próxima execução anual"""
        target_day = task.day_of_month  # 1-31
        target_month = task.month  # 1-12

        # Tenta este ano
        try:
            next_run_tz = from_time_tz.replace(
                month=target_month,
                day=target_day,
                hour=task.hour,
                minute=0,
                second=0,
                microsecond=0,
            )
        except ValueError:
            # Dia inválido (ex: 29/fev em ano não-bissexto)
            next_run_tz = from_time_tz.replace(
                month=target_month,
                day=28,
                hour=task.hour,
                minute=0,
                second=0,
                microsecond=0,
            )

        # Se já passou, vai próximo ano
        if next_run_tz <= from_time_tz:
            try:
                next_run_tz = from_time_tz.replace(
                    year=from_time_tz.year + 1,
                    month=target_month,
                    day=target_day,
                    hour=task.hour,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
            except ValueError:
                next_run_tz = from_time_tz.replace(
                    year=from_time_tz.year + 1,
                    month=target_month,
                    day=28,
                    hour=task.hour,
                    minute=0,
                    second=0,
                    microsecond=0,
                )

        # Converter de volta para UTC
        return next_run_tz.astimezone(pytz.UTC).replace(tzinfo=None)
