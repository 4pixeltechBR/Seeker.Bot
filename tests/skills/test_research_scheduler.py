"""
Testes unitários — research_machine.scheduler (parser de schedule)
"""
import asyncio
import sys
from pathlib import Path

# Força UTF-8 no stdout (Windows console default = cp1252)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Adiciona raiz ao path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.skills.research_machine.scheduler import (
    parse_schedule,
    build_scheduled_task,
    ScheduleSpec,
)
from src.skills.scheduler_conversacional.models import ScheduleType, ScheduledTask


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: esperado {expected!r}, obtido {actual!r}")


def test_daily_simple():
    spec = parse_schedule("every day 8am")
    assert_eq(spec.ok, True, "ok daily 8am")
    assert_eq(spec.schedule_type, ScheduleType.DAILY)
    assert_eq(spec.hour, 8)
    assert_eq(spec.minute, 0)


def test_daily_24h():
    spec = parse_schedule("every day 20:30")
    assert_eq(spec.ok, True)
    assert_eq(spec.hour, 20)
    assert_eq(spec.minute, 30)


def test_weekly_pt():
    spec = parse_schedule("every sexta 18:00")
    assert_eq(spec.ok, True)
    assert_eq(spec.schedule_type, ScheduleType.WEEKLY)
    assert_eq(spec.day_of_week, 4)  # sexta
    assert_eq(spec.hour, 18)


def test_weekly_en():
    spec = parse_schedule("every monday 9am")
    assert_eq(spec.ok, True)
    assert_eq(spec.schedule_type, ScheduleType.WEEKLY)
    assert_eq(spec.day_of_week, 0)  # segunda


def test_cron_range():
    spec = parse_schedule("0 8 * * 1-5")
    assert_eq(spec.ok, True)
    assert_eq(spec.schedule_type, ScheduleType.WEEKLY)
    assert_eq(spec.day_of_week, 1)
    assert_eq(spec.hour, 8)


def test_cron_comma():
    spec = parse_schedule("30 14 * * 1,3,5")
    assert_eq(spec.ok, True)
    assert_eq(spec.day_of_week, 1)
    assert_eq(spec.hour, 14)
    assert_eq(spec.minute, 30)


def test_invalid_format():
    spec = parse_schedule("qualquer coisa aleatória")
    assert_eq(spec.ok, False)


def test_empty():
    spec = parse_schedule("")
    assert_eq(spec.ok, False)


def test_invalid_time():
    spec = parse_schedule("every day 99:00")
    assert_eq(spec.ok, False)


def test_build_scheduled_task_daily():
    spec = parse_schedule("every day 9am")
    assert spec.ok
    task = build_scheduled_task(
        spec,
        query="Claude 4 release notes",
        chat_id=12345,
        user_id="999",
    )
    assert_eq(task.schedule_type, ScheduleType.DAILY)
    assert_eq(task.hour, 9)
    assert_eq(task.chat_id, 12345)
    assert "research_machine" in task.instruction_text
    assert "Claude 4 release notes" in task.instruction_text
    assert task.next_run_at is not None
    assert task.is_enabled is True


def test_build_scheduled_task_weekly():
    spec = parse_schedule("every monday 14:30")
    assert spec.ok
    task = build_scheduled_task(spec, query="agentes autônomos", chat_id=42)
    assert_eq(task.schedule_type, ScheduleType.WEEKLY)
    assert_eq(task.day_of_week, 0)
    assert_eq(task.hour, 14)
    assert_eq(task.minute, 30)


def main():
    tests = [
        test_daily_simple,
        test_daily_24h,
        test_weekly_pt,
        test_weekly_en,
        test_cron_range,
        test_cron_comma,
        test_invalid_format,
        test_empty,
        test_invalid_time,
        test_build_scheduled_task_daily,
        test_build_scheduled_task_weekly,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: ERRO {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"RESULTADO: {passed} passaram, {failed} falharam")
    print(f"{'='*60}")
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
