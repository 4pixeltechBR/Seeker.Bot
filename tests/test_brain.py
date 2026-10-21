from datetime import datetime

from seeker.brain import Brain
from seeker.review import parse_lessons, review_day
from seeker.schedule import TZ, Scheduler
from seeker.store import Store


def test_busca_nota_de_meses_atras(tmp_path):
    brain = Brain(tmp_path / "cerebro")
    old = datetime(2026, 3, 2, 15, 0, tzinfo=TZ)
    brain.log_exchange(old, "O aniversário da Ana é em março.", "Anotei o aniversário da Ana.")
    hits = brain.search("quando é o aniversário da Ana")
    assert hits
    assert "Ana" in hits[0]
    assert "2026-03-02" in hits[0]


def test_revisao_grava_no_maximo_tres_e_aparece_depois(tmp_path):
    store = Store(tmp_path / "s.db")
    brain = Brain(tmp_path / "cerebro")
    chat = store.create_chat()
    store.add_message(chat["id"], "user", "Não agende nada depois das 22h. Prefiro respostas curtas.")
    store.add_message(chat["id"], "assistant", "Certo.")
    with store._conn() as conn:
        conn.execute("UPDATE messages SET created_at = ?", ("2026-09-27T21:00:00-03:00",))
    raw = "\n".join(
        [
            "- não agendar nada depois das 22h",
            "- preferir respostas curtas",
            "- citar a fonte na pesquisa",
            "- quarta lição que não deve entrar",
            "um parágrafo sem marcador",
            "- senha do banco é segredo",
        ]
    )
    when = datetime(2026, 9, 27, 21, 30, tzinfo=TZ)
    lessons = review_day(store, brain, lambda prompt: raw, when)
    assert lessons == [
        "não agendar nada depois das 22h",
        "preferir respostas curtas",
        "citar a fonte na pesquisa",
    ]
    assert "22h" in brain.search("agendar depois das 22h")[0]
    assert any("22h" in item["text"] for item in store.memories())
    assert "Revisão do dia" in store.unseen_notices()[0]["text"]


def test_parser_ignora_texto_solto():
    assert parse_lessons("Hoje foi um dia produtivo e sem marcas.") == []


def test_revisao_roda_uma_vez_depois_das_21(tmp_path):
    store = Store(tmp_path / "s.db")
    calls = []
    clock = {"now": datetime(2026, 9, 27, 21, 5, tzinfo=TZ)}
    scheduler = Scheduler(store, lambda text: None, clock=lambda: clock["now"])
    scheduler.review_hour = 21
    scheduler.on_review = lambda when: calls.append(when)
    scheduler.tick()
    scheduler.tick()
    assert len(calls) == 1
    clock["now"] = datetime(2026, 9, 27, 18, 0, tzinfo=TZ)
    store.set_setting("review_2026-09-27", "")
    scheduler.tick()
    assert len(calls) == 1
