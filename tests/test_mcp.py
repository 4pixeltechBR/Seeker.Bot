import json
from types import SimpleNamespace

import pytest

from seeker.agent import Agent, Broker, Control
from seeker.mcp_hub import (
    McpHub,
    McpReport,
    McpServer,
    configure_mcp_skill,
    format_call_result,
    load_servers,
    needs_approval,
    parse_servers,
    register_tools,
    skill_name,
    upsert_server,
)
from seeker.providers import Cascade
from seeker.schedule import TaskBook
from seeker.skills.contract import Catalog
from seeker.store import Store
from seeker.tools import Files
from seeker.transcript import ToolCall


class Tool:
    def __init__(self, name, description, read_only=None, destructive=None):
        self.name = name
        self.description = description
        self.input_schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        self.annotations = SimpleNamespace(readOnlyHint=read_only, destructiveHint=destructive, openWorldHint=None)


def test_leitura_segue_e_escrita_pede_licenca():
    assert needs_approval(Tool("search_books", "Busca no catálogo.", read_only=True)) is False
    assert needs_approval(Tool("list_issues", "Lista issues do repositório.")) is False
    assert needs_approval(Tool("send_mail", "Envia um email.", destructive=True)) is True
    assert needs_approval(Tool("send_mail", "Envia um email para o destinatário.")) is True


def test_registra_e_formata_resultado(tmp_path):
    called = {}

    def call(name, arguments):
        called["name"] = name
        called["arguments"] = arguments
        return SimpleNamespace(is_error=False, content=[SimpleNamespace(text="3 livros")], structured_content={"n": 3})

    catalog = Catalog()
    count = register_tools(catalog, "livros", [Tool("search_books", "Busca no catálogo por título.", read_only=True)], call)
    assert count == 1
    name = skill_name("livros", "search_books")
    assert catalog.get(name).needs_approval is False
    assert catalog.run(name, {"q": "Duna"}) == '{"n": 3}'
    assert called == {"name": "search_books", "arguments": {"q": "Duna"}}
    failed = SimpleNamespace(is_error=True, content=[SimpleNamespace(text="não achei")], structured_content=None)
    assert format_call_result(failed) == "não achei"


def test_arquivo_de_servidores(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": [{"name": "local", "command": "python", "args": ["s.py"]}] }), encoding="utf-8")
    servers = load_servers(path)
    assert servers[0].name == "local"
    assert servers[0].args == ("s.py",)
    hub = McpHub()
    bad = tmp_path / "ruim.json"
    bad.write_text("{", encoding="utf-8")
    hub.start(bad, Catalog())
    assert hub.status()[0]["ok"] is False


def test_entende_json_e_grava_sem_duplicar(tmp_path):
    raw = json.dumps({"mcpServers": {"github": {"command": "npx", "args": ["srv"], "env": {"GITHUB_TOKEN": "x"}}}})
    specs = parse_servers({"config": raw})
    assert specs[0].name == "github"
    assert specs[0].args == ("srv",)
    assert specs[0].env == {"GITHUB_TOKEN": "x"}
    path = tmp_path / "mcp.json"
    upsert_server(path, specs[0])
    upsert_server(path, McpServer("github", command="node", args=("srv.js",)))
    saved = load_servers(path)
    assert len(saved) == 1
    assert saved[0].command == "node"
    catalog = Catalog()

    class FakeHub:
        def connect_one(self, spec, catalog):
            register_tools(catalog, spec.name, [Tool("list_issues", "Lista issues do repositório.", read_only=True)], lambda name, arguments: None)
            return McpReport(spec.name, True, 1)

    text = configure_mcp_skill(FakeHub(), catalog, path).run({"name": "github", "command": "npx", "args": ["srv"]})
    assert "github conectado" in text
    assert catalog.get(skill_name("github", "list_issues")).needs_approval is False


def test_configurar_sem_sim_nao_grava(tmp_path):
    path = tmp_path / "mcp.json"
    catalog = Catalog()
    wrote = []

    class FakeHub:
        def connect_one(self, spec, catalog):
            wrote.append(spec.name)
            return McpReport(spec.name, True, 0)

    root = tmp_path / "workspace"
    root.mkdir()
    store = Store(tmp_path / "s.db")
    chat = store.create_chat()
    agent = Agent(store, Cascade([_scripted()]), Files((root,), 1000), None, lambda query: "", TaskBook(store), Broker(), Control())
    agent.catalog.add(configure_mcp_skill(FakeHub(), catalog, path))

    def emit(event):
        if event["type"] == "approval":
            assert "npx" in event["command"]
            agent.broker.resolve(event["id"], False)

    agent.run(chat["id"], "configure esse mcp", emit)
    assert wrote == []
    assert not path.exists()


class _Script:
    name = "Teste"

    def __init__(self):
        self.steps = [
            [{"type": "tool_calls", "calls": [ToolCall("1", "configure_mcp", {"name": "github", "command": "npx", "args": ["srv"]})]}],
            [{"type": "token", "text": "não configurei"}],
        ]

    def available(self):
        return True

    def stream(self, messages, tools):
        yield from self.steps.pop(0)


def _scripted():
    return _Script()


def test_ferramenta_destrutiva_nao_roda_sem_sim(tmp_path):
    called = []

    def call(name, arguments):
        called.append(name)
        return SimpleNamespace(is_error=False, content=[SimpleNamespace(text="enviado")], structured_content=None)

    root = tmp_path / "workspace"
    root.mkdir()
    store = Store(tmp_path / "s.db")
    chat = store.create_chat()
    catalog = Catalog()
    register_tools(catalog, "mail", [Tool("send_mail", "Envia um email para alguém.")], call)

    class Scripted:
        name = "Teste"

        def __init__(self):
            self.steps = [
                [{"type": "tool_calls", "calls": [ToolCall("1", skill_name("mail", "send_mail"), {"q": "oi"})]}],
                [{"type": "token", "text": "não enviei"}],
            ]

        def available(self):
            return True

        def stream(self, messages, tools):
            yield from self.steps.pop(0)

    agent = Agent(store, Cascade([Scripted()]), Files((root,), 1000), None, lambda query: "", TaskBook(store), Broker(), Control())
    agent.catalog = catalog

    def emit(event):
        if event["type"] == "approval":
            agent.broker.resolve(event["id"], False)

    agent.run(chat["id"], "mande o email", emit)
    assert called == []
