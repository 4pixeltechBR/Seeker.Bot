from datetime import datetime, timedelta

from seeker.disk import disk_alerts, disk_due
from seeker.schedule import TZ, Scheduler
from seeker.store import Store

NOW = datetime(2026, 10, 8, 10, 0, tzinfo=TZ)


def _levels(mapping):
    def read(letter):
        if letter not in mapping:
            return None
        return mapping[letter]

    return read


def test_so_avisa_acima_de_95_nos_discos_combinados():
    lines = disk_alerts(_levels({"C": 94, "D": 95, "E": 96.4, "H": 99}))
    assert lines == ["Disco E: está em 96%.", "Disco H: está em 99%."]
    assert disk_alerts(_levels({"C": 10, "D": 20})) == []
    assert disk_alerts(_levels({})) == []


def test_checa_de_seis_em_seis_horas(tmp_path):
    store = Store(tmp_path / "s.db")
    assert disk_due(store, NOW) is True
    store.set_setting("disk_check_at", (NOW - timedelta(hours=5, minutes=59)).isoformat(timespec="minutes"))
    assert disk_due(store, NOW) is False
    store.set_setting("disk_check_at", (NOW - timedelta(hours=6)).isoformat(timespec="minutes"))
    assert disk_due(store, NOW) is True


def test_agenda_avisa_mesmo_no_silencio_e_nao_repete(tmp_path):
    store = Store(tmp_path / "s.db")
    store.set_setting("quiet_start", "22:00")
    store.set_setting("quiet_end", "07:00")
    calls = []
    scheduler = Scheduler(store, lambda text: None, clock=lambda: NOW.replace(hour=23))
    scheduler.on_disk = lambda now: calls.append(now)
    scheduler.tick()
    scheduler.tick()
    assert len(calls) == 1
    assert store.get_setting("disk_check_at")
