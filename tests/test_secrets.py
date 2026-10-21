import json
import threading
from datetime import datetime

import httpx

from seeker.agent import Agent, Broker, Control
from seeker.config import save_env_keys
from seeker.providers import Cascade
from seeker.runtime import build_runtime
from seeker.schedule import TZ, TaskBook
from seeker.secrets import PLACEHOLDER, guess_name, redact
from seeker.server import make_server
from seeker.store import Store
from seeker.tools import Files
from seeker.transcript import ToolCall

KEY = "AIzaSyTHISISFAKEKEYONLYX"
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
    def run(self, command):
        return "ok"

    def stop(self):
        pass


def make_agent(tmp_path, steps):
    root = tmp_path / "workspace"
    root.mkdir()
    store = Store(tmp_path / "s.db")
    chat = store.create_chat()
    scripted = Scripted(steps)
    agent = Agent(
        store,
        Cascade([scripted]),
        Files((root,), 1000),
        SpyShell(),
        lambda query: "resultado",
        TaskBook(store, clock=lambda: NOW),
        Broker(),
        Control(),
    )
    return agent, store, chat, scripted


def test_redige_a_chave_e_adivinha_o_nome():
    assert redact(KEY) == PLACEHOLDER
    assert KEY not in redact(f"qual o limite {KEY} hoje")
    assert "qual o limite" in redact(f"qual o limite {KEY} hoje")
    assert guess_name("a chave da gemini " + KEY) == "GEMINI_API_KEY"
    assert guess_name("gsk_" + "a" * 24) == "GROQ_API_KEY"
    assert redact("qual a capital") == "qual a capital"


def test_chave_colada_nao_chega_no_modelo(tmp_path):
    agent, store, chat, scripted = make_agent(tmp_path, [])

    def emit(event):
        if event.get("type") == "secret":
            assert event["name"] == "GEMINI_API_KEY"
            assert KEY not in str(event)
            agent.gate.finish(event["id"], "cancelled")

    agent.run(chat["id"], KEY, emit)
    blob = json.dumps(store.messages(chat["id"]), ensure_ascii=False)
    assert KEY not in blob
    assert PLACEHOLDER in blob
    assert scripted.seen == []
    assert agent.gate.pending() == []


def test_pedido_de_chave_ignora_o_valor_e_o_sim(tmp_path):
    agent, store, chat, scripted = make_agent(
        tmp_path,
        [
            [{"type": "tool_calls", "calls": [ToolCall("1", "request_secret", {"name": "GEMINI_API_KEY", "value": KEY})]}],
            [{"type": "token", "text": "O cartão está aberto."}],
        ],
    )
    seen = []

    def emit(event):
        seen.append(event["type"])
        if event.get("type") == "secret":
            assert "value" not in event
            assert KEY not in str(event)
            agent.gate.finish(event["id"], "cancelled")

    agent.run(chat["id"], "sim", emit)
    assert "secret" in seen
    assert "approval" not in seen
    blob = json.dumps(store.messages(chat["id"]) + store.events(chat["id"]), ensure_ascii=False)
    assert KEY not in blob
    assert KEY not in str(scripted.seen)
    calls = [call for message in scripted.seen[-1] if message.tool_calls for call in message.tool_calls]
    assert calls[0].arguments == {"name": "GEMINI_API_KEY"}


def test_telegram_abre_o_cartao_sem_travar(tmp_path):
    agent, store, chat, _scripted = make_agent(
        tmp_path,
        [
            [{"type": "tool_calls", "calls": [ToolCall("1", "request_secret", {"name": "Gemini"})]}],
            [{"type": "token", "text": "Abri no computador."}],
        ],
    )
    seen = []

    def emit(event):
        seen.append(event)

    agent.run(chat["id"], "guarda a chave da gemini", emit, origin="telegram")
    card = agent.gate.pending()[0]
    assert card["name"] == "GEMINI_API_KEY"
    assert "value" not in card
    assert any(event.get("type") == "secret" and KEY not in str(event) for event in seen)
    blob = json.dumps(store.messages(chat["id"]), ensure_ascii=False)
    assert KEY not in blob


def test_rotina_nao_abre_o_cofre(tmp_path):
    agent, _store, chat, scripted = make_agent(
        tmp_path,
        [
            [{"type": "tool_calls", "calls": [ToolCall("1", "request_secret", {"name": "Groq"})]}],
            [{"type": "token", "text": "Pronto."}],
        ],
    )
    agent.routine_mode = True
    seen = []

    def emit(event):
        seen.append(event["type"])
        if event.get("type") == "secret":
            agent.gate.finish(event["id"], "cancelled")

    agent.run(chat["id"], "guarda a chave", emit)
    assert "secret" not in seen
    assert any("rotina não guarda" in (message.content or "") for batch in scripted.seen for message in batch)


def test_grava_so_nome_permitido_e_limpa_o_historico(tmp_path):
    env = tmp_path / ".env"
    assert save_env_keys(env, {"GROQ_API_KEY": "gsk_" + "b" * 24, "OUTRA": "nao", "GEMINI_API_KEY": "linha\nnova"}) == ["GROQ_API_KEY"]
    text = env.read_text(encoding="utf-8")
    assert "OUTRA" not in text
    assert "\nnova" not in text
    store = Store(tmp_path / "s.db")
    chat = store.create_chat()
    store.add_message(chat["id"], "user", KEY)
    assert store.rewrite_secrets(lambda item: "limpo" if KEY in item else item) == 1
    assert KEY not in store.messages(chat["id"])[0]["content"]


def test_cartao_http_nao_devolve_o_valor(tmp_path):
    runtime = build_runtime(tmp_path, providers=[Scripted([[{"type": "token", "text": "presente"}]])], search=lambda query: "web")
    runtime.scheduler.on_fire = lambda text: None
    httpd = make_server(runtime)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    groq = "gsk_" + "c" * 24
    reader = None
    try:
        page = httpx.get(base + "/").text
        assert "Cofre seguro" in page and 'id="secret-value"' in page
        saved = httpx.post(base + "/api/secrets", json={"name": "GROQ_API_KEY", "value": groq})
        body = saved.text
        assert saved.status_code == 200
        assert groq not in body
        assert saved.json()["set"] is True
        assert groq not in httpx.get(base + "/api/settings").text
        assert groq in (tmp_path / ".env").read_text(encoding="utf-8")
        refused = httpx.post(base + "/api/secrets", json={"name": "XAI_API_KEY", "value": groq})
        assert refused.status_code == 400
        assert "XAI_API_KEY" not in (tmp_path / ".env").read_text(encoding="utf-8")

        chat = httpx.post(base + "/api/chats", json={}).json()
        lines = []

        def read_stream():
            with httpx.stream("POST", base + f"/api/chats/{chat['id']}/messages", json={"text": KEY}, timeout=30) as response:
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        lines.append(line)

        reader = threading.Thread(target=read_stream)
        reader.start()
        secret = {}
        for _ in range(100):
            pulse = httpx.get(base + "/api/pulse").json()
            assert KEY not in json.dumps(pulse)
            if pulse["secrets"]:
                secret = pulse["secrets"][0]
                break
            threading.Event().wait(0.05)
        assert secret["name"] == "GEMINI_API_KEY"
        httpx.post(base + "/api/secrets", json={"id": secret["id"], "name": secret["name"], "cancel": True})
        reader.join(timeout=10)
        assert reader.is_alive() is False
        past = httpx.get(base + f"/api/chats/{chat['id']}").text
        assert KEY not in past
        assert PLACEHOLDER in past
    finally:
        runtime.control.cancel()
        runtime.agent.gate.cancel_all()
        if reader is not None:
            reader.join(timeout=5)
        httpd.shutdown()
        runtime.close()
