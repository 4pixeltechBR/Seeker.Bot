from datetime import datetime

from seeker.schedule import TZ, Scheduler
from seeker.scout import scout_digest, scout_slot
from seeker.store import Store

NIGHT = datetime(2026, 10, 9, 22, 0, tzinfo=TZ)


def test_so_depois_das_22():
    assert scout_slot(NIGHT.replace(hour=21, minute=59)) is None
    assert scout_slot(NIGHT) == "2026-10-09"


def test_sem_fonte_nao_manda_nada():
    assert scout_digest(lambda url: (503, ""), NIGHT) == ""


def test_digest_curto_com_fonte_e_sem_polymarket():
    def fetch(url: str):
        if "algolia" in url and "LLM" in url:
            return 200, '{"hits":[{"title":"Modelo novo","url":"https://ex.test/modelo","points":20,"objectID":"1"}]}'
        if "polymarket" in url:
            return 200, '{"events":[{"title":"Mercado","slug":"mercado","volume":9}]}'
        return 200, "{}"

    text = scout_digest(fetch, NIGHT)
    assert text.startswith("Tech scout")
    assert "https://ex.test/modelo" in text
    assert "Mercado" not in text
    assert text.count("http") == 1


def test_agenda_uma_vez_e_respeita_o_silencio(tmp_path):
    store = Store(tmp_path / "s.db")
    calls = []
    early = Scheduler(store, lambda text: None, clock=lambda: NIGHT.replace(hour=21))
    early.on_scout = lambda now: calls.append(now)
    early.tick()
    assert calls == []
    night = Scheduler(store, lambda text: None, clock=lambda: NIGHT)
    night.on_scout = lambda now: calls.append(now)
    night.tick()
    night.tick()
    assert len(calls) == 1
    quiet_store = Store(tmp_path / "q.db")
    quiet_store.set_setting("quiet_start", "22:00")
    quiet_store.set_setting("quiet_end", "07:00")
    later = Scheduler(quiet_store, lambda text: None, clock=lambda: NIGHT.replace(minute=10))
    later.on_scout = lambda now: calls.append(now)
    later.tick()
    assert calls == [NIGHT]
    assert quiet_store.get_setting("scout_2026-10-09") != "done"
