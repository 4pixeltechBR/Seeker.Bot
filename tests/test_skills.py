import pytest

from seeker.agent import Agent, Broker, Control
from seeker.providers import Cascade
from seeker.schedule import TaskBook
from seeker.skills.contract import Catalog, Skill, SkillError
from seeker.skills.research import Evidence, Source, evidence_from_payload, format_research, research_skill
from seeker.store import Store
from seeker.tools import Files
from seeker.transcript import ToolCall


def test_contrato_recusa_skill_incompleta():
    catalog = Catalog()
    with pytest.raises(SkillError):
        catalog.add(Skill("research", "curta", "leitura", False, {}, lambda arguments: "x"))
    with pytest.raises(SkillError):
        catalog.add(
            Skill(
                "perigosa",
                "Mexe no computador sem dizer o que faz direito.",
                "altera",
                False,
                {},
                lambda arguments: "x",
            )
        )


def test_contrato_recusa_nome_repetido():
    catalog = Catalog()
    skill = research_skill(lambda query: Evidence("ok", (Source("Fonte", "https://ex.test"),)))
    catalog.add(skill)
    with pytest.raises(SkillError, match="já existe"):
        catalog.add(skill)


def test_pesquisa_numera_as_fontes_e_recusa_sem_fonte():
    evidence = evidence_from_payload(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Choveu."}]},
                    "groundingMetadata": {
                        "groundingChunks": [
                            {"web": {"title": "Clima", "uri": "https://clima.test"}},
                            {"web": {"uri": "https://clima.test"}},
                            {"web": {"title": "Outra", "uri": "https://outra.test"}},
                        ]
                    },
                }
            ]
        }
    )
    text = format_research(evidence)
    assert text.startswith("Choveu.")
    assert "1. Clima — https://clima.test" in text
    assert "2. Outra — https://outra.test" in text
    assert text.count("https://clima.test") == 1
    assert format_research(Evidence("chute", ())) == "A pesquisa não trouxe fonte. Não trate o texto como fato."


def test_agente_devolve_a_fonte_no_resultado(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    store = Store(tmp_path / "s.db")
    chat = store.create_chat()

    class Scripted:
        name = "Teste"

        def __init__(self):
            self.seen = []
            self.steps = [
                [{"type": "tool_calls", "calls": [ToolCall("1", "research", {"query": "clima em Goiânia"})]}],
                [{"type": "token", "text": "Choveu, segundo o Clima."}],
            ]

        def available(self):
            return True

        def stream(self, messages, tools):
            self.seen.append((messages, tools))
            yield from self.steps.pop(0)

    scripted = Scripted()
    agent = Agent(
        store,
        Cascade([scripted]),
        Files((root,), 1000),
        None,
        lambda query: "não usar",
        TaskBook(store),
        Broker(),
        Control(),
    )
    agent.catalog.add(
        research_skill(lambda query: Evidence("Choveu.", (Source("Clima", "https://clima.test"),)))
    )
    agent.run(chat["id"], "qual o clima?", lambda event: None)
    assert "https://clima.test" in scripted.seen[1][0][-1].content
    assert any(item["name"] == "research" for item in scripted.seen[0][1])
    assert all(item["name"] != "web_search" for item in scripted.seen[0][1])
