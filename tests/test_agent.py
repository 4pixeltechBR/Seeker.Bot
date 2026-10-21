from datetime import datetime

from seeker.agent import Agent, Broker, Control, gave_up
from seeker.skills.contract import Skill
from seeker.providers import Cascade
from seeker.schedule import TZ, TaskBook
from seeker.store import Store
from seeker.tools import Files
from seeker.transcript import ToolCall

NOW = datetime(2026, 9, 30, 10, 0, tzinfo=TZ)


class Scripted:
    name = "Teste"

    def __init__(self, steps):
        self.steps = list(steps)
        self.seen = []

    def available(self):
        return True

    def stream(self, messages, tools):
        self.seen.append(messages)
        yield from self.steps.pop(0)


class SpyShell:
    def __init__(self):
        self.commands = []

    def run(self, command):
        self.commands.append(command)
        return "ok"

    def stop(self):
        pass


def make_agent(tmp_path, steps, shell=None):
    root = tmp_path / "workspace"
    root.mkdir()
    store = Store(tmp_path / "s.db")
    chat = store.create_chat()
    scripted = Scripted(steps)
    agent = Agent(
        store,
        Cascade([scripted]),
        Files((root,), 1000),
        shell or SpyShell(),
        lambda query: "resultado " + query,
        TaskBook(store, clock=lambda: NOW),
        Broker(),
        Control(),
    )
    return agent, store, chat, scripted, root


def test_recusa_sem_ferramenta_volta_e_pede_a_skill(tmp_path):
    agent, _store, chat, scripted, _root = make_agent(
        tmp_path,
        [
            [{"type": "token", "text": "Não consigo criar uma skill para isso."}],
            [{"type": "tool_calls", "calls": [ToolCall("1", "create_skill", {"name": "canal"})]}],
            [{"type": "token", "text": "Mostrei o código."}],
        ],
    )
    agent.catalog.add(Skill(
        name="create_skill",
        when="Cria uma ferramenta nova quando falta um jeito concreto de resolver.",
        risk="altera",
        needs_approval=True,
        parameters={"type": "object", "properties": {}},
        run=lambda arguments: "criei",
    ))
    seen = []

    def emit(event):
        seen.append(event["type"])
        if event["type"] == "approval":
            agent.broker.resolve(event["id"], False)

    agent.run(chat["id"], "crie uma skill para o nome do canal", emit)
    assert "approval" in seen
    contents = [message.content or "" for message in scripted.seen[-1]]
    assert any("Não repita que não tem ferramenta" in item for item in contents)
    assert gave_up("Não tenho ferramenta para isso.")
    assert gave_up("A capital é Brasília.") is False


def test_resposta_normal_nao_forca_outra_tentativa(tmp_path):
    _agent, _store, chat, scripted, _root = make_agent(
        tmp_path,
        [[{"type": "token", "text": "A capital é Brasília."}]],
    )
    _agent.run(chat["id"], "qual a capital?", lambda event: None)
    assert len(scripted.seen) == 1


def test_le_arquivo_e_responde(tmp_path):
    agent, store, chat, scripted, root = make_agent(
        tmp_path,
        [
            [{"type": "tool_calls", "calls": [ToolCall("1", "read_file", {"path": "nota.txt"})]}],
            [{"type": "token", "text": "diz olá"}],
        ],
    )
    (root / "nota.txt").write_text("olá", encoding="utf-8")
    agent.run(chat["id"], "o que tem na nota?", lambda event: None)
    assert store.messages(chat["id"])[-1]["content"] == "diz olá"
    tool = scripted.seen[1][-1]
    assert tool.role == "tool"
    assert "olá" in tool.content


def test_comando_simples_roda_sem_licenca(tmp_path):
    shell = SpyShell()
    agent, _store, chat, scripted, _root = make_agent(
        tmp_path,
        [
            [{"type": "tool_calls", "calls": [ToolCall("1", "run_command", {"command": "Get-ChildItem"})]}],
            [{"type": "token", "text": "listado"}],
        ],
        shell,
    )
    seen = []
    agent.run(chat["id"], "lista a pasta", lambda event: seen.append(event["type"]))
    assert shell.commands == ["Get-ChildItem"]
    assert "approval" not in seen
    assert "ok" in scripted.seen[1][-1].content


def test_sim_no_chat_roda_o_destrutivo(tmp_path):
    shell = SpyShell()
    agent, _store, chat, _scripted, _root = make_agent(
        tmp_path,
        [
            [{"type": "tool_calls", "calls": [ToolCall("1", "run_command", {"command": "Remove-Item x"})]}],
            [{"type": "token", "text": "apaguei"}],
        ],
        shell,
    )
    seen = []
    agent.run(chat["id"], "sim", lambda event: seen.append(event["type"]))
    assert shell.commands == ["Remove-Item x"]
    assert "approval" not in seen


def test_comando_recusado_nao_roda(tmp_path):
    shell = SpyShell()
    agent, store, chat, scripted, _root = make_agent(
        tmp_path,
        [
            [{"type": "tool_calls", "calls": [ToolCall("1", "run_command", {"command": "Remove-Item x"})]}],
            [{"type": "token", "text": "então não"}],
        ],
        shell,
    )

    def emit(event):
        if event["type"] == "approval":
            agent.broker.resolve(event["id"], False)

    agent.run(chat["id"], "apaga", emit)
    assert shell.commands == []
    assert "recusou" in scripted.seen[1][-1].content


def test_agenda_pelo_texto(tmp_path):
    agent, store, chat, _scripted, _root = make_agent(
        tmp_path,
        [
            [{"type": "tool_calls", "calls": [ToolCall("1", "schedule_task", {"title": "pagar o banco", "when_text": "amanhã às 9h"})]}],
            [{"type": "token", "text": "marcado"}],
        ],
    )
    agent.run(chat["id"], "me lembra de pagar o banco amanhã às 9h", lambda event: None)
    tasks = store.pending_tasks()
    assert tasks[0]["title"] == "pagar o banco"
    assert tasks[0]["due_at"].startswith("2026-10-01T09:00")


def test_memoria_entra_no_proximo_turno(tmp_path):
    agent, store, chat, scripted, _root = make_agent(
        tmp_path,
        [
            [{"type": "tool_calls", "calls": [ToolCall("1", "remember", {"text": "gosta de respostas curtas"})]}],
            [{"type": "token", "text": "guardei"}],
            [{"type": "token", "text": "oi"}],
        ],
    )
    agent.run(chat["id"], "seja curto", lambda event: None)
    agent.run(chat["id"], "oi", lambda event: None)
    assert "respostas curtas" in scripted.seen[-1][0].content
