from datetime import datetime, timedelta

from seeker.brain import Brain
from seeker.curiosity import curiosity_question, curiosity_slot, curiosity_text
from seeker.mail import mail_notice
from seeker.schedule import TZ, Scheduler
from seeker.store import Store

NOW = datetime(2026, 10, 11, 18, 0, tzinfo=TZ)


def test_aviso_repetido_nao_volta(tmp_path):
    store = Store(tmp_path / "s.db")
    items = [{"uid": "4", "from": "Ana", "subject": "Orçamento"}]
    first = mail_notice(store, items)
    assert "Ana: Orçamento. Número 4." in first
    assert mail_notice(store, items) == ""


def test_sem_ontem_fica_quieto(tmp_path):
    brain = Brain(tmp_path / "cerebro")
    assert curiosity_question(brain, NOW) == ""
    assert curiosity_text(lambda url: (200, "{}"), brain, NOW) == ""
    assert curiosity_slot(NOW.replace(hour=17)) is None
    assert curiosity_slot(NOW) == "2026-10-11"


def test_curiosidade_manda_uma_fonte(tmp_path):
    brain = Brain(tmp_path / "cerebro")
    yesterday = NOW - timedelta(days=1)
    brain.log_exchange(yesterday, "quero um agente local que rode no meu computador", "Vou olhar isso.")

    def fetch(url: str):
        if "algolia" in url:
            return 200, '{"hits":[{"title":"Agente no PC","url":"https://ex.test/agente","points":12,"objectID":"1"}]}'
        return 200, "{}"

    text = curiosity_text(fetch, brain, NOW)
    assert text.startswith("Curiosidade")
    assert "https://ex.test/agente" in text
    assert "agente local" in text.casefold()


def test_curiosidade_uma_vez(tmp_path):
    store = Store(tmp_path / "s.db")
    calls = []
    scheduler = Scheduler(store, lambda text: None, clock=lambda: NOW)
    scheduler.on_curiosity = lambda now: calls.append(now)
    scheduler.tick()
    scheduler.tick()
    assert len(calls) == 1
