import httpx
import pytest

from seeker.agent import Agent, Broker, Control
from seeker.browser import PageReader, check_url, format_page, page_text, read_page_skill, submit_form_skill
from seeker.providers import Cascade
from seeker.schedule import TaskBook
from seeker.store import Store
from seeker.tools import Files
from seeker.transcript import ToolCall


def _public(host, port, *rest):
    return [(socket_family(), "", "", "", ("1.1.1.1", 0))]


def socket_family():
    return 0


def test_extrai_texto_e_mostra_a_fonte():
    html = "<html><style>body{}</style><p>Olá</p><script>alert(1)</script><p>mundo</p></html>"
    assert page_text(html) == "Olá\n\nmundo"
    assert format_page("Olá", "https://ex.test/a", 200).endswith("Fonte: https://ex.test/a")


def test_recusa_pagina_local():
    with pytest.raises(Exception, match="fora"):
        check_url("http://127.0.0.1/segredo", resolve=_public)
    with pytest.raises(Exception, match="fora"):
        check_url("http://localhost/x", resolve=_public)
    assert check_url("https://ex.test/dia", resolve=_public) == "https://ex.test/dia"


def test_leitura_nao_pede_licenca_e_formulario_pede():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text="<p>enviado</p>", headers={"content-type": "text/html"})
        return httpx.Response(200, text="<p>boletim</p>", headers={"content-type": "text/html"})

    reader = PageReader(httpx.Client(transport=httpx.MockTransport(handler)), resolve=_public)
    reading = read_page_skill(reader)
    sending = submit_form_skill(reader)
    assert reading.needs_approval is False
    assert sending.needs_approval is True
    assert "Fonte: https://ex.test/dia" in reading.run({"url": "https://ex.test/dia"})
    assert "boletim" in reading.run({"url": "https://ex.test/dia"})


def test_formulario_recusado_nao_envia(tmp_path):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.method)
        return httpx.Response(200, text="<p>ok</p>")

    reader = PageReader(httpx.Client(transport=httpx.MockTransport(handler)), resolve=_public)
    root = tmp_path / "workspace"
    root.mkdir()
    store = Store(tmp_path / "s.db")
    chat = store.create_chat()

    class Scripted:
        name = "Teste"

        def __init__(self):
            self.steps = [
                [{"type": "tool_calls", "calls": [ToolCall("1", "submit_form", {"url": "https://ex.test/form", "fields": {"q": "oi"}})]}],
                [{"type": "token", "text": "não enviei"}],
            ]

        def available(self):
            return True

        def stream(self, messages, tools):
            yield from self.steps.pop(0)

    agent = Agent(store, Cascade([Scripted()]), Files((root,), 1000), None, lambda query: "", TaskBook(store), Broker(), Control())
    agent.catalog.add(submit_form_skill(reader))

    def emit(event):
        if event["type"] == "approval":
            agent.broker.resolve(event["id"], False)

    agent.run(chat["id"], "envie o formulário", emit)
    assert sent == []


def test_formulario_autorizado_envia(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, text="<p>enviado</p>")

    reader = PageReader(httpx.Client(transport=httpx.MockTransport(handler)), resolve=_public)
    root = tmp_path / "workspace"
    root.mkdir()
    store = Store(tmp_path / "s.db")
    chat = store.create_chat()

    class Scripted:
        name = "Teste"

        def __init__(self):
            self.seen = []
            self.steps = [
                [{"type": "tool_calls", "calls": [ToolCall("1", "submit_form", {"url": "https://ex.test/form", "fields": {"q": "oi"}})]}],
                [{"type": "token", "text": "foi"}],
            ]

        def available(self):
            return True

        def stream(self, messages, tools):
            self.seen.append(messages)
            yield from self.steps.pop(0)

    scripted = Scripted()
    agent = Agent(store, Cascade([scripted]), Files((root,), 1000), None, lambda query: "", TaskBook(store), Broker(), Control())
    agent.catalog.add(submit_form_skill(reader))

    def emit(event):
        if event["type"] == "approval":
            assert "ex.test/form" in event["command"]
            assert "q=oi" in event["command"]
            agent.broker.resolve(event["id"], True)

    agent.run(chat["id"], "envie o formulário", emit)
    assert seen["body"] == "q=oi"
    assert "enviado" in scripted.seen[1][-1].content
    assert "Fonte:" in scripted.seen[1][-1].content
