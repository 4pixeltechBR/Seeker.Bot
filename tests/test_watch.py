from datetime import datetime, timedelta

from seeker.mail import new_mail
from seeker.schedule import TZ, Scheduler
from seeker.store import Store

NOW = datetime(2026, 10, 9, 15, 0, tzinfo=TZ)


class Box:
    def __init__(self, items):
        self.items = items

    def ready(self):
        return True

    def unseen_items(self, limit=15):
        return self.items[:limit]


def test_primeira_leitura_nao_avisa_e_a_nova_avisa_uma_vez(tmp_path):
    store = Store(tmp_path / "s.db")
    box = Box([{"uid": "4", "from": "Ana", "subject": "Orçamento"}])
    assert new_mail(box, store, NOW) == ""
    assert new_mail(box, store, NOW + timedelta(minutes=15)) == ""
    box.items.append({"uid": "9", "from": "Leo", "subject": "Nota"})
    text = new_mail(box, store, NOW + timedelta(minutes=30))
    assert "Leo: Nota. Número 9." in text
    assert "Ana" not in text
    assert "espero um sim" in text
    assert new_mail(box, store, NOW + timedelta(minutes=45)) == ""


def test_silencio_nao_observa_e_tarefa_continua_uma_vez(tmp_path):
    store = Store(tmp_path / "s.db")
    store.set_setting("quiet_start", "14:00")
    store.set_setting("quiet_end", "16:00")
    calls = []
    scheduler = Scheduler(store, lambda text: calls.append(text), clock=lambda: NOW)
    scheduler.on_watch = lambda now: calls.append("watch")
    scheduler.tick()
    assert calls == []
