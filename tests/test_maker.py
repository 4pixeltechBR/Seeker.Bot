import pytest

from seeker.agent import Agent, Broker, Control
from seeker.providers import Cascade
from seeker.schedule import TaskBook
from seeker.skills.contract import Catalog, SkillError
from seeker.skills.maker import create_skill_tool, install
from seeker.store import Store
from seeker.tools import Files
from seeker.transcript import ToolCall

WHEN = "Devolve pronto quando pedem a ferramenta de eco."
SOURCE = f'''from seeker.skills.contract import Skill

def build():
    def run(arguments):
        return "pronto"
    return Skill(
        name="eco_teste",
        when="{WHEN}",
        risk="leitura",
        needs_approval=False,
        parameters={{"type": "object", "properties": {{}}}},
        run=run,
    )
'''
TEST = "def test_eco():\n    assert True\n"


def test_cria_a_ferramenta_depois_do_teste(tmp_path):
    catalog = Catalog()
    message = install(tmp_path, catalog, "eco_teste", WHEN, "leitura", SOURCE, TEST, check=lambda root, path: None)
    assert message == "Criei a ferramenta eco_teste. Já pode usar."
    assert catalog.run("eco_teste", {}) == "pronto"
    assert (tmp_path / "seeker" / "skills" / "custom" / "eco_teste.py").exists()


def test_teste_ruim_apaga_a_ferramenta(tmp_path):
    catalog = Catalog()

    def fail(root, path):
        raise SkillError("falhou")

    with pytest.raises(SkillError, match="falhou"):
        install(tmp_path, catalog, "eco_teste", WHEN, "leitura", SOURCE, TEST, check=fail)
    assert catalog.has("eco_teste") is False
    assert not (tmp_path / "seeker" / "skills" / "custom" / "eco_teste.py").exists()


def test_criar_sempre_pede_autorizacao(tmp_path):
    skill = create_skill_tool(Catalog(), tmp_path, check=lambda root, path: None)
    assert skill.needs_approval is True
    assert skill.risk == "altera"


def test_sim_no_chat_nao_grava_sozinho(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    store = Store(tmp_path / "s.db")
    chat = store.create_chat()
    catalog = Catalog()
    calls = [
        [{
            "type": "tool_calls",
            "calls": [ToolCall("1", "create_skill", {
                "name": "eco_teste",
                "when": WHEN,
                "risk": "leitura",
                "source": SOURCE,
                "test": TEST,
            })],
        }],
        [{"type": "token", "text": "não criei"}],
    ]

    class Scripted:
        name = "Teste"

        def available(self):
            return True

        def stream(self, messages, tools):
            yield from calls.pop(0)

    agent = Agent(
        store,
        Cascade([Scripted()]),
        Files((root,), 1000),
        None,
        lambda query: "",
        TaskBook(store),
        Broker(),
        Control(),
    )
    agent.catalog.add(create_skill_tool(agent.catalog, tmp_path, check=lambda root, path: None))
    seen = []

    def emit(event):
        seen.append(event["type"])
        if event["type"] == "approval":
            agent.broker.resolve(event["id"], False)

    agent.run(chat["id"], "sim", emit)
    assert "approval" in seen
    assert not (tmp_path / "seeker" / "skills" / "custom" / "eco_teste.py").exists()
