import json

import httpx

from seeker.providers import Cascade, GeminiProvider, OpenAIProvider, ProviderError, grounded_search
from seeker.transcript import Message, ToolCall, to_gemini, to_openai


class Scripted:
    def __init__(self, events, fail=False, name="Um"):
        self.name = name
        self.events = events
        self.fail = fail
        self.calls = 0

    def available(self):
        return True

    def stream(self, messages, tools):
        self.calls += 1
        if self.fail:
            raise ProviderError("cota")
        yield from self.events


def test_cascata_pula_quem_cai_antes_do_texto():
    first = Scripted([], fail=True, name="Gemini")
    second = Scripted([{"type": "token", "text": "oi"}], name="Maritaca")
    events = list(Cascade([first, second]).stream([], None))
    assert events[0]["text"].startswith("Gemini indisponível")
    assert events[1] == {"type": "token", "text": "oi"}
    assert second.calls == 1


def test_cascata_nao_troca_no_meio():
    class Die:
        name = "Gemini"

        def available(self):
            return True

        def stream(self, messages, tools):
            yield {"type": "token", "text": "come"}
            raise ProviderError("caiu", started=True)

    second = Scripted([{"type": "token", "text": "não"}], name="Maritaca")
    events = list(Cascade([Die(), second]).stream([], None))
    assert any(event["type"] == "error" for event in events)
    assert second.calls == 0


def test_openai_junta_ferramenta_em_fluxo():
    sse = (
        'data: {"choices":[{"delta":{"content":"Olá"}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"read_file","arguments":""}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"path\\": \\"a.txt\\"}"}}]}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sse)

    provider = OpenAIProvider("Groq", "https://example.test/v1", "m", "key", httpx.Client(transport=httpx.MockTransport(handler)))
    events = list(provider.stream([Message("user", "oi")], []))
    assert events[0]["text"] == "Olá"
    assert events[1]["calls"][0].arguments == {"path": "a.txt"}


def test_gemini_erro_antes_de_falar():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota"}})

    provider = GeminiProvider("Gemini", "https://example.test", "gemini-2.5-flash", "key", httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        list(provider.stream([Message("user", "oi")], None))
        raise AssertionError("devia falhar")
    except ProviderError as exc:
        assert exc.started is False
        assert "429" in str(exc)


def test_busca_pede_grounding():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "achado"}]},
                        "groundingMetadata": {"groundingChunks": [{"web": {"title": "Fonte", "uri": "https://ex.test"}}]},
                    }
                ]
            },
        )

    text = grounded_search(httpx.Client(transport=httpx.MockTransport(handler)), "https://example.test", "gemini-2.5-flash", "key", "clima")
    assert seen["body"]["tools"] == [{"google_search": {}}]
    assert "achado" in text
    assert "https://ex.test" in text


def test_formato_das_mensagens():
    messages = [
        Message("system", "seja curto"),
        Message("user", "leia"),
        Message("assistant", "", [ToolCall("1", "read_file", {"path": "a"}), ToolCall("2", "list_dir", {})]),
        Message("tool", "um", tool_call_id="1", name="read_file"),
        Message("tool", "dois", tool_call_id="2", name="list_dir"),
    ]
    openai = to_openai(messages, None)
    assert openai["messages"][3]["role"] == "tool"
    gemini = to_gemini(messages, None)
    responses = [part for part in gemini["contents"][-1]["parts"]]
    assert len(responses) == 2
    assert responses[0]["functionResponse"]["name"] == "read_file"
