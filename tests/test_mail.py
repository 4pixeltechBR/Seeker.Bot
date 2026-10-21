from datetime import datetime

from seeker.agent import _preview
from seeker.mail import format_unseen, mail_line, mail_slot, readable
from seeker.schedule import TZ, Scheduler
from seeker.skills.mail_skill import delete_mail_skill, read_mail_skill, send_mail_skill, write_mail_skill
from seeker.store import Store
from seeker.transcript import ToolCall

NINE = datetime(2026, 10, 9, 9, 0, tzinfo=TZ)


class Box:
    def __init__(self):
        self.sent = []
        self.drafts = []
        self.deleted = []

    def unseen(self, limit=8):
        return format_unseen([{"uid": "4", "from": "Ana", "subject": "Orçamento"}])

    def draft(self, to, subject, body):
        self.drafts.append((to, subject, body))
        return f"Rascunho salvo para {to}."

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))
        return f"Enviei para {to}."

    def delete(self, uid):
        self.deleted.append(uid)
        return f"Apaguei o e-mail {uid}."


def test_cabecalho_dobrado_junta_o_assunto():
    header = "Subject: =?UTF-8?q?Agentes_de_IA_no_projeto_de_hardware:_IBM_compara_uma_infer?=\n =?UTF-8?q?encia?=\n"
    from seeker.mail import _field
    assert readable(_field(header, "Subject")).endswith("inferencia")


def test_assunto_codificado_fica_legivel():
    raw = "=?UTF-8?Q?Start_Seu_Dia_=E2=80=94_StartSe?="
    assert readable(raw) == "Start Seu Dia — StartSe"
    line = mail_line({"uid": "7", "from": "=?utf-8?Q?Jo=C3=A3o?= <joao@ex.test>", "subject": raw})
    assert line.startswith("- João: Start Seu Dia — StartSe.")
    assert "Número 7." in line
    assert "=?" not in line


def test_leitura_e_livre_e_o_resto_pede_sim():
    box = Box()
    assert read_mail_skill(box).needs_approval is False
    assert "Ana" in read_mail_skill(box).run({})
    for skill in (write_mail_skill(box), send_mail_skill(box), delete_mail_skill(box)):
        assert skill.needs_approval is True
        assert skill.risk == "altera"
    assert format_unseen([]) == "Nenhum e-mail novo."


def test_preview_mostra_destinatario_e_texto():
    shown = _preview(ToolCall("1", "send_mail", {"to": "ana@ex.test", "subject": "Oi", "body": "Segue o texto."}))
    assert "ana@ex.test" in shown
    assert "Segue o texto." in shown
    assert "Apagar o e-mail 4" in _preview(ToolCall("2", "delete_mail", {"uid": "4"}))


def test_horario_e_uma_vez_por_edicao(tmp_path):
    assert mail_slot(NINE.replace(hour=8)) is None
    assert mail_slot(NINE) == "2026-10-09_0900"
    assert mail_slot(NINE.replace(hour=21)) == "2026-10-09_2100"
    store = Store(tmp_path / "s.db")
    calls = []
    scheduler = Scheduler(store, lambda text: None, clock=lambda: NINE)
    scheduler.on_mail = lambda now: calls.append(now)
    scheduler.tick()
    scheduler.tick()
    assert len(calls) == 1


def test_rascunho_e_envio_passam_pela_caixa():
    box = Box()
    assert write_mail_skill(box).run({"to": "ana@ex.test", "subject": "Oi", "body": "Texto"}) == "Rascunho salvo para ana@ex.test."
    assert send_mail_skill(box).run({"to": "ana@ex.test", "subject": "Oi", "body": "Texto"}) == "Enviei para ana@ex.test."
    assert delete_mail_skill(box).run({"uid": "4"}) == "Apaguei o e-mail 4."
    assert box.drafts and box.sent and box.deleted == ["4"]
