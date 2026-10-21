from datetime import datetime

from seeker.news import news_digest, news_slot
from seeker.schedule import TZ, Scheduler
from seeker.store import Store

MORNING = datetime(2026, 10, 9, 7, 30, tzinfo=TZ)
EVENING = datetime(2026, 10, 9, 19, 30, tzinfo=TZ)


def test_horario_da_edicao():
    assert news_slot(MORNING.replace(minute=29)) is None
    assert news_slot(MORNING) == "2026-10-09_0730"
    assert news_slot(MORNING.replace(hour=10)) == "2026-10-09_0730"
    assert news_slot(EVENING) == "2026-10-09_1930"


def test_sem_fonte_nao_manda_nada():
    assert news_digest(lambda url: (503, ""), MORNING) == ""


def test_digest_traz_titulo_e_link():
    def fetch(url: str):
        if "algolia" in url and "local" in url:
            return 200, '{"hits":[{"title":"Agente local","url":"https://ex.test/ia","points":10,"objectID":"1"}]}'
        return 200, "{}"

    text = news_digest(fetch, MORNING)
    assert "Inteligência artificial local" in text
    assert "https://ex.test/ia" in text
    assert "Comércio" not in text


def test_agenda_manda_uma_vez_e_respeita_o_silencio(tmp_path):
    store = Store(tmp_path / "s.db")
    calls = []
    scheduler = Scheduler(store, lambda text: None, clock=lambda: MORNING)
    scheduler.on_news = lambda now: calls.append(now)
    scheduler.tick()
    scheduler.tick()
    assert len(calls) == 1
    store.set_setting("quiet_start", "19:00")
    store.set_setting("quiet_end", "21:00")
    evening = Scheduler(store, lambda text: None, clock=lambda: EVENING)
    evening.on_news = lambda now: calls.append(now)
    evening.tick()
    assert len(calls) == 1
