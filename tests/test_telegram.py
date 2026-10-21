import json

import httpx

from seeker.agent import Agent, Broker, Control
from seeker.providers import Cascade
from seeker.schedule import TaskBook
from seeker.store import Store
from seeker.telegram_bot import MENU, TelegramBot, allowed_users, split_command
from seeker.tools import Files


class Scripted:
    name = "Teste"

    def __init__(self, text="olá do pc"):
        self.text = text
        self.steps = [[{"type": "token", "text": text}]]

    def available(self):
        return True

    def stream(self, messages, tools):
        yield from self.steps.pop(0)


class Box:
    def __init__(self, tmp_path, replies):
        self.store = Store(tmp_path / "s.db")
        self.control = Control()
        self.broker = Broker()
        self.agent = Agent(
            self.store,
            Cascade([Scripted()]),
            Files((tmp_path / "workspace",), 1000),
            None,
            lambda query: "",
            TaskBook(self.store),
            self.broker,
            self.control,
        )
        (tmp_path / "workspace").mkdir()
        self.sent = []
        self.actions = []
        self.replies = replies

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getUpdates"):
            body = self.replies.pop(0) if self.replies else []
            return httpx.Response(200, json={"ok": True, "result": body})
        if request.url.path.endswith("sendMessage"):
            self.sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("sendChatAction"):
            self.actions.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("answerCallbackQuery"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)


def test_so_o_usuario_permitido_recebe_resposta(tmp_path):
    update = {
        "update_id": 1,
        "message": {"message_id": 1, "from": {"id": 99}, "chat": {"id": 99}, "text": "oi"},
    }
    box = Box(tmp_path, [[update]])
    bot = TelegramBot("token", {7}, box, httpx.Client(transport=httpx.MockTransport(box.handler)))
    bot.poll_once()
    assert box.sent == []


def test_mensagem_volta_pelo_telegram(tmp_path):
    box = Box(tmp_path, [])
    bot = TelegramBot("token", {7}, box, httpx.Client(transport=httpx.MockTransport(box.handler)))
    bot._turn(7, "oi")
    assert box.sent[0]["chat_id"] == 7
    assert box.sent[0]["text"] == "olá do pc"
    assert box.store.get_setting("telegram_chat_7")


def test_menu_azul_so_tem_o_seeker_novo():
    names = [name for name, _text in MENU]
    assert names[0] == "start"
    assert "scout" not in names
    assert "viralx9" not in names
    assert all(name.islower() and "/" not in name for name in names)
    assert split_command("/Agenda@SeekerBR1_bot hoje") == ("agenda", "hoje")


def test_atalho_antigo_nao_vai_para_o_agente(tmp_path):
    box = Box(tmp_path, [])
    bot = TelegramBot("token", {7}, box, httpx.Client(transport=httpx.MockTransport(box.handler)))
    bot._handle({"message": {"from": {"id": 7}, "chat": {"id": 7}, "text": "/scout"}})
    assert "outro agente" in box.sent[0]["text"]


def test_menu_azul_apaga_a_lista_antiga(tmp_path):
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    bot = TelegramBot("token", {7}, Box(tmp_path, []), httpx.Client(transport=httpx.MockTransport(handler)))
    bot.publish_menu()
    assert posted[0][0].endswith("/deleteMyCommands")
    assert posted[-1][0].endswith("/setMyCommands")
    names = [item["command"] for item in posted[-1][1]["commands"]]
    assert names == [name for name, _text in MENU]


def test_agenda_lista_tarefa_sem_chamar_o_agente(tmp_path):
    box = Box(tmp_path, [])
    box.store.add_task("Ligar para a Ana", "2026-10-07T09:00:00-03:00", "none")
    bot = TelegramBot("token", {7}, box, httpx.Client(transport=httpx.MockTransport(box.handler)))
    bot._handle({"message": {"from": {"id": 7}, "chat": {"id": 7}, "text": "/agenda"}})
    assert "Ligar para a Ana" in box.sent[0]["text"]


def test_enquanto_responde_mostra_escrevendo(tmp_path):
    box = Box(tmp_path, [])
    bot = TelegramBot("token", {7}, box, httpx.Client(transport=httpx.MockTransport(box.handler)))
    bot._turn(7, "oi")
    assert box.actions[0]["action"] == "typing"
    assert box.actions[0]["chat_id"] == 7


def test_modo_voz_mostra_gravando_enquanto_fala(tmp_path):
    box = Box(tmp_path, [])
    box.store.set_setting("telegram_mode_7", "voz")
    bot = TelegramBot("token", {7}, box, httpx.Client(transport=httpx.MockTransport(box.handler)))
    bot._turn(7, "oi")
    assert [item["action"] for item in box.actions] == ["typing", "record_voice"]


def test_botao_nao_recusa(tmp_path):
    box = Box(tmp_path, [])
    approval_id, _event = box.broker.request("Remove-Item x")
    box.replies.append(
        [
            {
                "update_id": 3,
                "callback_query": {"id": "c1", "from": {"id": 7}, "data": f"no:{approval_id}"},
            }
        ]
    )
    bot = TelegramBot("token", {7}, box, httpx.Client(transport=httpx.MockTransport(box.handler)))
    bot.poll_once()
    assert box.broker.wait(approval_id) is False


def test_lista_de_usuarios():
    assert allowed_users("7, 8") == {7, 8}
