from datetime import datetime, timedelta

from seeker.schedule import TZ, ParseError, TaskBook, advance, in_quiet, parse_quiet, parse_when
from seeker.store import Store
from seeker.suggest import ensure_suggestion

NOW = datetime(2026, 9, 30, 10, 0, tzinfo=TZ)  # quarta


def test_horarios_do_dia_a_dia():
    assert parse_when("amanhã às 9h", NOW).due == datetime(2026, 10, 1, 9, 0, tzinfo=TZ)
    assert parse_when("amanha 9h30", NOW).due == datetime(2026, 10, 1, 9, 30, tzinfo=TZ)
    assert parse_when("hoje 15:00", NOW).due == datetime(2026, 9, 30, 15, 0, tzinfo=TZ)
    assert parse_when("daqui a 15 minutos", NOW).due == NOW + timedelta(minutes=15)
    assert parse_when("em uma hora", NOW).due == NOW + timedelta(hours=1)
    assert parse_when("depois de amanhã de manhã", NOW).due == datetime(2026, 10, 2, 9, 0, tzinfo=TZ)
    assert parse_when("oito e meia amanhã", NOW).due == datetime(2026, 10, 1, 8, 30, tzinfo=TZ)
    assert parse_when("3 da tarde amanhã", NOW).due == datetime(2026, 10, 1, 15, 0, tzinfo=TZ)
    assert parse_when("sexta às 11h", NOW).due == datetime(2026, 10, 2, 11, 0, tzinfo=TZ)
    assert parse_when("toda segunda às 8h", NOW).repeat == "weekly"
    assert parse_when("toda segunda às 8h", NOW).due == datetime(2026, 10, 5, 8, 0, tzinfo=TZ)
    assert parse_when("todo dia às 8h30", NOW).due == datetime(2026, 10, 1, 8, 30, tzinfo=TZ)
    assert parse_when("dias úteis às 9h", NOW).due == datetime(2026, 10, 1, 9, 0, tzinfo=TZ)
    assert parse_when("30/09/2026 14:00", NOW).due == datetime(2026, 9, 30, 14, 0, tzinfo=TZ)


def test_hoje_passado_e_sexta_que_vem():
    try:
        parse_when("hoje 8h", NOW)
        raise AssertionError("devia recusar")
    except ParseError as exc:
        assert "passou" in str(exc)
    friday = datetime(2026, 10, 2, 12, 0, tzinfo=TZ)
    assert parse_when("sexta que vem às 11h", friday).due == datetime(2026, 10, 9, 11, 0, tzinfo=TZ)
    assert parse_when("sexta que vem às 11h", NOW).due == datetime(2026, 10, 2, 11, 0, tzinfo=TZ)


def test_recorrencia_e_silencio():
    due = datetime(2026, 9, 30, 8, 0, tzinfo=TZ)
    assert advance(due, "daily", NOW) == datetime(2026, 10, 1, 8, 0, tzinfo=TZ)
    assert advance(due, "none", NOW) is None
    assert in_quiet(due.time().replace(hour=22), due.time().replace(hour=7), NOW.replace(hour=23))
    assert not in_quiet(due.time().replace(hour=22), due.time().replace(hour=7), NOW)
    assert parse_quiet("22h às 7h")[0].hour == 22


def test_agenda_no_banco(tmp_path):
    book = TaskBook(Store(tmp_path / "s.db"), clock=lambda: NOW)
    text = book.schedule("pagar o banco", "amanhã às 9h")
    assert "Agendado" in text
    assert "pagar o banco" in book.list_pending()
    done = book.complete("pagar")
    assert "Concluí" in done
    book.schedule("água", "todo dia às 8h")
    again = book.complete("água")
    assert "próxima" in again


def test_sugestao_nao_repete_no_mesmo_dia(tmp_path):
    store = Store(tmp_path / "s.db")
    past = (NOW - timedelta(hours=2)).isoformat(timespec="minutes")
    store.add_task("ligar", past, "none")
    ensure_suggestion(store, NOW)
    ensure_suggestion(store, NOW)
    assert len(store.open_suggestions()) == 1
    store.set_suggestion_status(store.open_suggestions()[0]["id"], "dismissed")
    ensure_suggestion(store, NOW)
    assert store.open_suggestions() == []
