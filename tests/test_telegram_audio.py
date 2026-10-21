import io
import math
import struct
import wave

import httpx

from seeker.telegram_bot import TelegramBot, mode_choice, wav_to_voice_ogg


def tone_wav() -> bytes:
    rate = 24000
    frames = int(rate * 0.3)
    pcm = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
        for i in range(frames)
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


class Voice:
    def speak(self, text):
        return tone_wav()


class Runtime:
    def __init__(self, tmp_path):
        from seeker.agent import Broker, Control
        from seeker.store import Store
        self.store = Store(tmp_path / "s.db")
        self.broker = Broker()
        self.control = Control()
        self._voice = Voice()

    def voice(self):
        return self._voice


def test_telegram_envia_texto_e_audio(tmp_path):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, request.content))
        return httpx.Response(200, json={"ok": True})

    bot = TelegramBot("token", {1}, Runtime(tmp_path), httpx.Client(transport=httpx.MockTransport(handler)))
    bot.send(1, "Resposta")
    bot.send_voice_reply(1, "Resposta")
    assert sent[0][0].endswith("/sendMessage")
    assert b"Resposta" in sent[0][1]
    assert sent[1][0].endswith("/sendVoice")
    assert b"seeker.ogg" in sent[1][1]
    assert b"OggS" in sent[1][1]
    assert b"OpusHead" in sent[1][1]
    assert b"sendAudio" not in sent[1][0].encode()


def test_wav_vira_ogg_opus():
    ogg = wav_to_voice_ogg(tone_wav())
    assert ogg.startswith(b"OggS")
    assert b"OpusHead" in ogg


def test_seletor_grava_o_modo_sem_chamar_o_agente(tmp_path):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return httpx.Response(200, json={"ok": True})

    runtime = Runtime(tmp_path)
    bot = TelegramBot("token", {1}, runtime, httpx.Client(transport=httpx.MockTransport(handler)))
    bot._handle({"message": {"from": {"id": 1}, "chat": {"id": 1}, "text": "Voz"}})
    bot._handle({"message": {"from": {"id": 1}, "chat": {"id": 1}, "text": "/texto"}})
    assert runtime.store.get_setting("telegram_mode_1") == "texto"
    assert b"texto e por voz" in sent[0]
    assert b"Respondo por texto." in sent[1]


def test_modo_texto_nao_manda_voz(tmp_path):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    bot = TelegramBot("token", {1}, Runtime(tmp_path), httpx.Client(transport=httpx.MockTransport(handler)))
    bot._deliver(1, "Resposta")
    assert sent == ["/bottoken/sendMessage"]


def test_voz_longa_sai_em_um_audio(tmp_path):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, request.content))
        return httpx.Response(200, json={"ok": True})

    class Parts:
        def speak_parts(self, text):
            yield tone_wav()
            yield tone_wav()

    runtime = Runtime(tmp_path)
    runtime._voice = Parts()
    runtime.store.set_setting("telegram_mode_1", "voz")
    bot = TelegramBot("token", {1}, runtime, httpx.Client(transport=httpx.MockTransport(handler)))
    bot._deliver(1, "Resposta longa")
    voices = [item for item in sent if item[0].endswith("/sendVoice")]
    assert len(voices) == 1
    assert len(voices[0][1]) > len(wav_to_voice_ogg(tone_wav()))


def test_modo_voz_manda_texto_e_voz(tmp_path):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    runtime = Runtime(tmp_path)
    runtime.store.set_setting("telegram_mode_1", "voz")
    bot = TelegramBot("token", {1}, runtime, httpx.Client(transport=httpx.MockTransport(handler)))
    bot._deliver(1, "Resposta")
    assert sent[0].endswith("/sendMessage")
    assert sent[1].endswith("/sendVoice")


def test_escolha_de_modo():
    assert mode_choice("Voz") == "voz"
    assert mode_choice("/voz@SeekerBR1_bot") == "voz"
    assert mode_choice("Texto") == "texto"
    assert mode_choice("voz alta") is None


def test_falha_na_voz_nao_impede_texto(tmp_path):
    class BrokenVoice:
        def speak(self, text):
            raise RuntimeError("sem voz")

    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    runtime = Runtime(tmp_path)
    runtime._voice = BrokenVoice()
    bot = TelegramBot("token", {1}, runtime, httpx.Client(transport=httpx.MockTransport(handler)))
    bot.send(1, "Resposta")
    bot.send_voice_reply(1, "Resposta")
    assert sent == ["/bottoken/sendMessage"]
