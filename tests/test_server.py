import threading
from datetime import datetime, timedelta

import httpx

from seeker.runtime import build_runtime
from seeker.schedule import TZ
from seeker.server import make_server


class Scripted:
    name = "Teste"

    def __init__(self):
        self.steps = [[{"type": "token", "text": "presente"}]]

    def available(self):
        return True

    def stream(self, messages, tools):
        yield from self.steps.pop(0)


def test_pagina_e_conversa(tmp_path):
    runtime = build_runtime(tmp_path, providers=[Scripted()], search=lambda query: "web")
    runtime.scheduler.on_fire = lambda text: None
    httpd = make_server(runtime)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        page = httpx.get(base + "/").text
        assert "Chat" in page and "Voz" in page and 'id="thread"' in page
        health = httpx.get(base + "/api/health").json()
        assert health["providers"]
        chat = httpx.post(base + "/api/chats", json={}).json()
        events = []
        with httpx.stream("POST", base + f"/api/chats/{chat['id']}/messages", json={"text": "oi"}) as response:
            for line in response.iter_lines():
                if line.startswith("data:"):
                    events.append(line)
        assert any("presente" in line for line in events)
        past = (datetime.now(TZ) - timedelta(minutes=5)).isoformat(timespec="minutes")
        runtime.store.add_task("ligar", past, "none")
        runtime.scheduler.tick()
        pulse = httpx.get(base + "/api/pulse").json()
        assert "ligar" in str(pulse)
    finally:
        httpd.shutdown()
        runtime.close()
