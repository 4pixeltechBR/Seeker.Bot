from datetime import datetime

from seeker.brain import Brain
from seeker.morning import morning_text
from seeker.schedule import TZ, Scheduler, TaskBook
from seeker.store import Store

EIGHT = datetime(2026, 9, 27, 8, 5, tzinfo=TZ)


def test_cartao_junta_tarefa_de_hoje_e_licao_de_ontem(tmp_path):
    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    book = TaskBook(store, clock=lambda: EIGHT.replace(hour=7))
    book.schedule("pagar o banco", "hoje às 9h")
    book.schedule("ligar amanhã", "amanhã às 11h")
    brain.write_lesson(EIGHT.replace(day=26), "não agendar depois das 22h")
    text = morning_text(store, brain, EIGHT)
    assert "pagar o banco às 09:00" in text
    assert "ligar amanhã" not in text
    assert "não agendar depois das 22h" in text


def test_sem_nada_fica_quieto(tmp_path):
    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    assert morning_text(store, brain, EIGHT) == ""


def test_dispara_uma_vez_depois_das_8_e_espera_o_silencio(tmp_path):
    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    brain.write_lesson(EIGHT.replace(day=26), "preferir respostas curtas")
    calls = []
    when = {"now": EIGHT.replace(hour=7)}
    scheduler = Scheduler(store, lambda text: None, clock=lambda: when["now"])
    scheduler.morning_hour = 8
    scheduler.on_morning = lambda now: calls.append(morning_text(store, brain, now))
    scheduler.tick()
    assert calls == []
    when["now"] = EIGHT
    store.set_setting("quiet_start", "22:00")
    store.set_setting("quiet_end", "09:00")
    scheduler.tick()
    assert calls == []
    assert store.get_setting("morning_2026-09-27") != "done"
    store.set_setting("quiet_end", "07:00")
    scheduler.tick()
    scheduler.tick()
    assert calls == ["De ontem: preferir respostas curtas."]
    assert store.get_setting("morning_2026-09-27") == "done"
