from datetime import datetime, timedelta, timezone

from seeker.agenda import events_on
from seeker.brain import Brain
from seeker.config import load_config
from seeker.mail import format_unseen
from seeker.radar import act, radar_cards, radar_text, remember
from seeker.schedule import TZ, Scheduler, TaskBook
from seeker.store import Store

EIGHT = datetime(2026, 10, 9, 8, 30, tzinfo=TZ)


def test_radar_junta_decisao_e_cala_se_vazio(tmp_path):
    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    assert radar_text(store, brain, EIGHT) == ""
    TaskBook(store, clock=lambda: EIGHT.replace(hour=7)).schedule("pagar o banco", "hoje às 9h")
    brain.write_lesson(EIGHT.replace(day=8), "não agendar depois das 22h")
    mail = format_unseen([{"uid": "4", "from": "Ana", "subject": "Orçamento"}])
    text = radar_text(store, brain, EIGHT, disks=["Disco D: está em 97%."], mail=mail)
    assert text.startswith("Radar")
    assert "pagar o banco às 09:00" in text
    assert "não agendar depois das 22h" not in text
    assert "Disco D: está em 97%." in text
    assert "4 Ana" in text
    assert "Rascunho ou arquivar." in text
    assert "espero um sim" not in text


def test_licao_sozinha_nao_entra(tmp_path):
    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    brain.write_lesson(EIGHT.replace(day=8), "não agendar depois das 22h")
    assert radar_text(store, brain, EIGHT) == ""


def test_fonte_desligada_sai_do_radar(tmp_path):
    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    TaskBook(store, clock=lambda: EIGHT.replace(hour=7)).schedule("pagar o banco", "hoje às 9h")
    text = radar_text(
        store,
        brain,
        EIGHT,
        disks=["Disco D: está em 97%."],
        mail=[{"uid": "4", "from": "Ana", "subject": "Orçamento"}],
        sources=("tarefa",),
    )
    assert "pagar o banco" in text
    assert "Disco D" not in text
    assert "Ana" not in text


def test_arquivar_tira_o_cartao_do_dia(tmp_path):
    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    TaskBook(store, clock=lambda: EIGHT.replace(hour=7)).schedule("pagar o banco", "hoje às 9h")
    cards = radar_cards(store, brain, EIGHT)
    remember(store, cards)
    assert act(store, TaskBook(store), cards[0].id, "arquivar", EIGHT)["text"] == "Arquivei por hoje."
    assert radar_cards(store, brain, EIGHT) == []


def test_conflito_e_mudanca_de_horario(tmp_path):
    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    book = TaskBook(store, clock=lambda: EIGHT.replace(hour=7))
    book.schedule("pagar o banco", "hoje às 9h")
    book.schedule("dentista", "hoje às 9h20")
    radar_cards(store, brain, EIGHT)
    task = store.find_task("dentista")
    store.update_task(task["id"], due_at=task["due_at"].replace("T09:20", "T09:10"))
    cards = radar_cards(store, brain, EIGHT)
    assert len(cards) == 1
    assert cards[0].line.startswith("dentista mudou de 09:20 para 09:10")
    assert "conflita com pagar o banco às 09:00" in cards[0].line
    assert not any(card.source == "tarefa" for card in cards)
    change = cards[0]
    remember(store, cards)
    before = store.get_task(task["id"])["due_at"]
    proposed = act(store, book, change.id, "remarcar", EIGHT)
    assert proposed["confirm"] == "Mover dentista para 10:10?"
    assert store.get_task(task["id"])["due_at"] == before
    moved = act(store, book, change.id, "sim", EIGHT)
    assert "10:10" in moved["text"]
    assert store.get_task(task["id"])["due_at"] != before


def test_conflito_sem_mudanca_vira_um_cartao(tmp_path):
    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    book = TaskBook(store, clock=lambda: EIGHT.replace(hour=7))
    book.schedule("pagar o banco", "hoje às 9h")
    book.schedule("dentista", "hoje às 9h20")
    cards = radar_cards(store, brain, EIGHT)
    assert len(cards) == 1
    assert cards[0].line == "conflito entre pagar o banco às 09:00 e dentista às 09:20"
    assert cards[0].actions == ("remarcar", "arquivar")


def test_botao_do_telegram_leva_o_nome(tmp_path):
    from seeker.radar import radar_keyboard

    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    TaskBook(store, clock=lambda: EIGHT.replace(hour=7)).schedule("pagar o banco", "hoje às 9h")
    cards = radar_cards(store, brain, EIGHT, mail=[{"uid": "4", "from": "Ana", "subject": "Orçamento"}])
    labels = [button["text"] for row in radar_keyboard(cards)["inline_keyboard"] for button in row]
    assert "Concluir pagar o banco" in labels
    assert "Arquivar pagar o banco" in labels
    assert "Rascunho Ana" in labels
    assert "Arquivar Ana" in labels
    assert all(len(button["callback_data"]) <= 64 for row in radar_keyboard(cards)["inline_keyboard"] for button in row)


def test_ics_sem_preparo_entra_e_grupo_de_whatsapp_nao(tmp_path):
    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:dentista-1
SUMMARY:Dentista
DTSTART;TZID=America/Sao_Paulo:20261009T100000
DESCRIPTION:
END:VEVENT
END:VCALENDAR
"""
    cards = radar_cards(
        store,
        brain,
        EIGHT,
        events=events_on(ics, EIGHT),
        whatsapp=[
            {"id": "1", "title": "Ana", "body": "consegue amanhã?"},
            {"id": "2", "title": "Família", "body": "João: chega que horas?"},
        ],
    )
    lines = " ".join(card.line for card in cards)
    assert "Dentista às 10:00 está sem preparo" in lines
    assert "Ana — consegue amanhã?" in lines
    assert "Família" not in lines
    assert "João" not in lines


def test_email_arquivado_nao_volta(tmp_path):
    from seeker.radar import kept_mail

    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    cards = radar_cards(store, brain, EIGHT, mail=[{"uid": "4", "from": "Ana", "subject": "Orçamento"}])
    remember(store, cards)
    assert kept_mail(store, EIGHT)[0]["from"] == "Ana"
    act(store, TaskBook(store), cards[0].id, "arquivar", EIGHT)
    assert kept_mail(store, EIGHT) == []
    assert radar_cards(store, brain, EIGHT, mail=[{"uid": "4", "from": "Ana", "subject": "Orçamento"}]) == []


def test_rascunho_nao_envia(tmp_path):
    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    cards = radar_cards(store, brain, EIGHT, mail=[{"uid": "4", "from": "Ana", "subject": "Orçamento"}])
    remember(store, cards)
    seen = []

    def complete(prompt):
        seen.append(prompt)
        return "Ana, vi o orçamento."

    result = act(store, TaskBook(store), cards[0].id, "rascunho", EIGHT, complete=complete)
    assert result["text"] == "Rascunho, você envia:\nAna, vi o orçamento."
    assert "Orçamento" in seen[0]
    assert "confirm" not in result


def test_config_desliga_whatsapp(tmp_path):
    (tmp_path / "config.toml").write_text('[radar]\nwhatsapp = false\ncalendar_ics = "agenda.ics"\n', encoding="utf-8")
    config = load_config(tmp_path)
    assert "whatsapp" not in config.radar_sources()
    assert config.radar_sources() == ("tarefa", "disco", "email", "agenda")
    assert config.calendar_ics.endswith("agenda.ics")


def test_radar_so_depois_das_8h30(tmp_path):
    store = Store(tmp_path / "s.db")
    calls = []
    when = {"now": EIGHT.replace(minute=29)}
    scheduler = Scheduler(store, lambda text: None, clock=lambda: when["now"])
    scheduler.morning_hour = 8
    scheduler.morning_minute = 30
    scheduler.on_morning = lambda now: calls.append(now)
    scheduler.tick()
    assert calls == []
    when["now"] = EIGHT
    scheduler.tick()
    scheduler.tick()
    assert len(calls) == 1


def test_aviso_do_whatsapp_ignora_outro_aplicativo(tmp_path):
    import sqlite3

    from seeker.whatsapp import read_toasts

    path = tmp_path / "wpndatabase.db"
    now = datetime(2026, 10, 9, 11, 30, tzinfo=timezone.utc)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE NotificationHandler (RecordId INTEGER, PrimaryId TEXT)")
        conn.execute("CREATE TABLE Notification (Id INTEGER, HandlerId INTEGER, Payload BLOB, ArrivalTime INTEGER)")
        conn.execute("INSERT INTO NotificationHandler VALUES (1, '5319275A.WhatsAppDesktop_app!App')")
        conn.execute("INSERT INTO NotificationHandler VALUES (2, 'OpenAI.Codex_app!App')")
        fresh = _filetime(now)
        old = _filetime(now - timedelta(days=3))
        direct = b"<toast><visual><binding><text>Ana</text><text>consegue amanha?</text></binding></visual></toast>"
        group = b"<toast><visual><binding><text>Familia</text><text>Joao: chega que horas?</text></binding></visual></toast>"
        other = b"<toast><visual><binding><text>LyrIA</text><text>falta parear o WhatsApp</text></binding></visual></toast>"
        conn.execute("INSERT INTO Notification VALUES (1, 1, ?, ?)", (direct, fresh))
        conn.execute("INSERT INTO Notification VALUES (2, 1, ?, ?)", (group, fresh))
        conn.execute("INSERT INTO Notification VALUES (3, 1, ?, ?)", (direct, old))
        conn.execute("INSERT INTO Notification VALUES (4, 2, ?, ?)", (other, fresh))
    found = read_toasts(path, now)
    assert [item["title"] for item in found] == ["Ana"]


def _filetime(moment: datetime) -> int:
    return int((moment.timestamp() + 11644473600) * 10_000_000)
