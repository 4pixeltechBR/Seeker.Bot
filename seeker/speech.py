"""Síntese local por Kokoro-82M. A placa só entra se houver cerca de 1 GB livre, e o modelo volta para a RAM 5 minutos depois do áudio."""

from __future__ import annotations

import io
import re
import threading
import wave

from seeker.store import Store

SAMPLE_LINE = "Olá. Estou à disposição."
PART_CHARS = 180
MIN_CHARS = 15
VRAM_NEED_MB = 1024
GPU_HOLD_SECONDS = 300

VOICE_MAP = {
    "female": "pf_dora",
    "male": "pm_santa",
}
DEFAULT_VOICE = "pm_santa"

# Termos técnicos em inglês que o G2P do Kokoro pronuncia mal em português.
REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bAPI\b", re.I), "a pê i"),
    (re.compile(r"\bGPU\b", re.I), "gê p ê u"),
    (re.compile(r"\bCPU\b", re.I), "cê p ê u"),
    (re.compile(r"\bRAM\b", re.I), "rã m"),
    (re.compile(r"\bSSD\b", re.I), "esse esse dê"),
    (re.compile(r"\bUSB\b", re.I), "u éss bê"),
    (re.compile(r"\bWi-?Fi\b", re.I), "uâi fái"),
    (re.compile(r"\bURL\b", re.I), "u ár éll"),
    (re.compile(r"\bHTTP[S]?\b", re.I), "aitríti piés"),
    (re.compile(r"\bJSON\b", re.I), "jéissôn"),
    (re.compile(r"\bSQL\b", re.I), "essi quiél"),
    (re.compile(r"\bPDF\b", re.I), "pê dê éffi"),
    (re.compile(r"\bID\b", re.I), "ai dí"),
    (re.compile(r"\bAI\b", re.I), "ei ai"),
    (re.compile(r"\bML\b", re.I), "em élle"),
    (re.compile(r"\bLLM\b", re.I), "elle elle émme"),
    (re.compile(r"\bTTS\b", re.I), "tê tê ésse"),
    (re.compile(r"\bSTT\b", re.I), "ésse tê tê"),
    (re.compile(r"\bSDK\b", re.I), "es dê quê"),
    (re.compile(r"\bCLI\b", re.I), "cê élle ai"),
    (re.compile(r"\bUI\b", re.I), "u ai"),
    (re.compile(r"\bUX\b", re.I), "u écs"),
    (re.compile(r"\bCRUD\b", re.I), "crúdi"),
    (re.compile(r"\bOAuth\b", re.I), "ô auth"),
    (re.compile(r"\bGitHub\b", re.I), "git hab"),
    (re.compile(r"\bGitLab\b", re.I), "git lab"),
    (re.compile(r"\bVS\s*Code\b", re.I), "vi éss cóud"),
    (re.compile(r"\bPython\b", re.I), "páiton"),
    (re.compile(r"\bJavaScript\b", re.I), "djáva scripit"),
    (re.compile(r"\bTypeScript\b", re.I), "taípi scripit"),
    (re.compile(r"\bDocker\b", re.I), "dôker"),
    (re.compile(r"\bKubernetes\b", re.I), "cubernétis"),
    (re.compile(r"\bLinux\b", re.I), "línux"),
    (re.compile(r"\bWindows\b", re.I), "uindôs"),
    (re.compile(r"\bmacOS\b", re.I), "mák óuess"),
    (re.compile(r"\biOS\b", re.I), "ai óuess"),
    (re.compile(r"\bAndroid\b", re.I), "andróid"),
    (re.compile(r"\bTelegram\b", re.I), "telegrrãm"),
    (re.compile(r"\bWhatsApp\b", re.I), "uasáp"),
    (re.compile(r"\bObsidian\b", re.I), "obsídiain"),
    (re.compile(r"\bNotion\b", re.I), "nóushon"),
    (re.compile(r"\bSlack\b", re.I), "slæk"),
    (re.compile(r"\bDiscord\b", re.I), "discórd"),
    (re.compile(r"\bYouTube\b", re.I), "iútub"),
    (re.compile(r"\bInstagram\b", re.I), "instagrãm"),
    (re.compile(r"\bTwitter\b", re.I), "tuítâr"),
    (re.compile(r"\bLinkedIn\b", re.I), "linkdin"),
    (re.compile(r"\bGoogle\b", re.I), "gûgul"),
    (re.compile(r"\bGemini\b", re.I), "djémini"),
    (re.compile(r"\bOpenAI\b", re.I), "ôpen ei ai"),
    (re.compile(r"\bAnthropic\b", re.I), "antrópik"),
    (re.compile(r"\bGroq\b", re.I), "grók"),
    (re.compile(r"\bWhisper\b", re.I), "uíspir"),
    (re.compile(r"\bKokoro\b", re.I), "cócôro"),
    (re.compile(r"\bPowerShell\b", re.I), "páuershél"),
    (re.compile(r"\bNode\.js\b", re.I), "noud djê es"),
    (re.compile(r"\bnpm\b", re.I), "en pi émme"),
    (re.compile(r"\bNginx\b", re.I), "ênjinx"),
    (re.compile(r"\bRedis\b", re.I), "rédis"),
    (re.compile(r"\bPostgres(?:QL)?\b", re.I), "póstgrès"),
    (re.compile(r"\bMongoDB\b", re.I), "mongô di bi"),
    (re.compile(r"\bSQLite\b", re.I), "essi quéli ait"),
    (re.compile(r"\bRegex\b", re.I), "rédjéks"),
    (re.compile(r"\bMarkdown\b", re.I), "márkdaun"),
    (re.compile(r"\bHTML\b", re.I), "eitír ému élli"),
    (re.compile(r"\bCSS\b", re.I), "ci éssi éssi"),
    (re.compile(r"\bSSH\b", re.I), "esse échi esse"),
    (re.compile(r"\bVPN\b", re.I), "vi pi énne"),
    (re.compile(r"\bDNS\b", re.I), "di énne éssi"),
    (re.compile(r"\bSMTP\b", re.I), "éssem ti ép em pé"),
    (re.compile(r"\bIMAP\b", re.I), "ai máp"),
    (re.compile(r"\bOAuth2\b", re.I), "ô auth tu"),
    (re.compile(r"\bJWT\b", re.I), "djê dabliu ti"),
    (re.compile(r"\bCORS\b", re.I), "córs"),
    (re.compile(r"\bWebhook\b", re.I), "uébhuk"),
    (re.compile(r"\bWebSocket\b", re.I), "uébsékét"),
    (re.compile(r"\bREST\b", re.I), "rést"),
    (re.compile(r"\bGraphQL\b", re.I), "griquiél"),
    (re.compile(r"\bgRPC\b", re.I), "djê árpi si"),
    (re.compile(r"\bMQTT\b", re.I), "em quit quit"),
    (re.compile(r"\bRPA\b", re.I), "ér pi ê"),
    (re.compile(r"\bERP\b", re.I), "ê ár pi"),
    (re.compile(r"\bCRM\b", re.I), "si ár émme"),
    (re.compile(r"\bROI\b", re.I), "ár ô ai"),
    (re.compile(r"\bKPI\b", re.I), "quê pi ai"),
    (re.compile(r"\bSEO\b", re.I), "ési i ô"),
    (re.compile(r"\bSEM\b", re.I), "ési i émme"),
    (re.compile(r"\bCTA\b", re.I), "ci ti êi"),
    (re.compile(r"\bB2B\b", re.I), "bi tu bi"),
    (re.compile(r"\bB2C\b", re.I), "bi tu ci"),
    (re.compile(r"\bSaaS\b", re.I), "sás"),
    (re.compile(r"\bPaaS\b", re.I), "pás"),
    (re.compile(r"\bIaaS\b", re.I), "aiás"),
    (re.compile(r"\bCDN\b", re.I), "ci di énne"),
    (re.compile(r"\bETL\b", re.I), "i ti élle"),
    (re.compile(r"\bELT\b", re.I), "i ti ti"),
    (re.compile(r"\bOLAP\b", re.I), "oláp"),
    (re.compile(r"\bOLTP\b", re.I), "oltipi"),
    (re.compile(r"\bCI[/ ]?CD\b", re.I), "si ai si di"),
    (re.compile(r"\bDevOps\b", re.I), "dévosps"),
    (re.compile(r"\bMLOps\b", re.I), "emél ops"),
    (re.compile(r"\bFinOps\b", re.I), "finops"),
    (re.compile(r"\bSecOps\b", re.I), "sécosps"),
    (re.compile(r"\bA/B\b", re.I), "ei bi ei"),
    (re.compile(r"\bQA\b", re.I), "qui êi"),
    (re.compile(r"\bQC\b", re.I), "qui ci"),
    (re.compile(r"\bPOC\b", re.I), "pi ô si"),
    (re.compile(r"\bMVP\b", re.I), "ém vi pi"),
    (re.compile(r"\bPMF\b", re.I), "pi émme éffi"),
    (re.compile(r"\bGTM\b", re.I), "gi ti émme"),
    (re.compile(r"\bICP\b", re.I), "ai si pi"),
    (re.compile(r"\bSLA\b", re.I), "es élle ei"),
    (re.compile(r"\bSLO\b", re.I), "es élle ô"),
    (re.compile(r"\bOKR\b", re.I), "ô quê ár"),
    (re.compile(r"\bNDA\b", re.I), "én dê ei"),
    (re.compile(r"\bGDPR\b", re.I), "ji di pi ár"),
    (re.compile(r"\bLGPD\b", re.I), "élle ji pi dê"),
    (re.compile(r"\bCPF\b", re.I), "cé pé éffi"),
    (re.compile(r"\bCNPJ\b", re.I), "cé énne pi jê"),
    (re.compile(r"\bRG\b", re.I), "ár dji"),
    (re.compile(r"\bCEP\b", re.I), "cé ê pi"),
    (re.compile(r"\bIBGE\b", re.I), "ibi jê gi"),
    (re.compile(r"\bINSS\b", re.I), "inéss"),
    (re.compile(r"\bFGTS\b", re.I), "fgtês"),
    (re.compile(r"\bPIX\b", re.I), "pix"),
    (re.compile(r"\bBoleto\b", re.I), "boléitu"),
    (re.compile(r"\bNF-e\b", re.I), "enéfi"),
    (re.compile(r"\bXML\b", re.I), "ixéméli"),
    (re.compile(r"\bCSV\b", re.I), "cê éssi vi"),
    (re.compile(r"\bXLS[X]?\.?$", re.I), "exél"),
    (re.compile(r"\bDOC[X]?\.?$", re.I), "dók"),
    (re.compile(r"\bMP3\b", re.I), "empi tri"),
    (re.compile(r"\bMP4\b", re.I), "empi pôr"),
    (re.compile(r"\bWAV\b", re.I), "uáv"),
    (re.compile(r"\bOGG\b", re.I), "ôgu"),
    (re.compile(r"\bFLAC\b", re.I), "flak"),
    (re.compile(r"\bAAC\b", re.I), "ak"),
    (re.compile(r"\bH264\b", re.I), "aitchu duzentos e sessenta e quatro"),
    (re.compile(r"\bHEVC\b", re.I), "hévc"),
    (re.compile(r"\bHDR\b", re.I), "aitchu di ár"),
    (re.compile(r"\bSDR\b", re.I), "ésse di ár"),
    (re.compile(r"\bFPS\b", re.I), "éf pi ésse"),
    (re.compile(r"\bHz\b", re.I), "értz"),
    (re.compile(r"\bkHz\b", re.I), "quilórts"),
    (re.compile(r"\bMHz\b", re.I), "megártz"),
    (re.compile(r"\bGHz\b", re.I), "gigártz"),
    (re.compile(r"\bms\b(?=\s*[.,;])|\bms\b(?=\s*$)", re.I), "milissegundos"),
    (re.compile(r"\bRTF\b", re.I), "ér té éffi"),
    (re.compile(r"\bTTFA\b", re.I), "ti ti éffi ei"),
    (re.compile(r"\bRSS\b", re.I), "ér éssi ér"),
    (re.compile(r"\bVRAM\b", re.I), "vi rã m"),
    (re.compile(r"\bCUDA\b", re.I), "cúdá"),
    (re.compile(r"\bONNX\b", re.I), "ônix"),
    (re.compile(r"\bGGUF\b", re.I), "guf"),
    (re.compile(r"\bLoRA\b", re.I), "lóra"),
    (re.compile(r"\bQ\d+[_A-Za-z]*\b", re.I), ""),
    (re.compile(r"\bINT8\b", re.I), "int oito"),
    (re.compile(r"\bFP16\b", re.I), "ép pi dezesseis"),
    (re.compile(r"\bBF16\b", re.I), "bi éffi dezesseis"),
    (re.compile(r"\bW4A8\b", re.I), ""),
    (re.compile(r"\bNF4\b", re.I), ""),
    (re.compile(r"\bPT-BR\b", re.I), "português do brasil"),
    (re.compile(r"\bEN-US\b", re.I), "inglês americano"),
    (re.compile(r"\ben[-_]us\b", re.I), "inglês"),
    (re.compile(r"\bpt[-_]br\b", re.I), "português"),
]


class SpeechError(Exception):
    pass


def sanitize(text: str) -> str:
    cleaned = text.replace("*", "").replace("_", "").replace("`", "").replace("#", "")
    cleaned = re.sub(r"(?:https?|ftp)://\S+", " ", cleaned, flags=re.I)
    for pattern, replacement in REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", r"\1 por cento", cleaned)
    cleaned = re.sub(r"[\[\](){}<>|\\/~@^$%&+=]", " ", cleaned)
    cleaned = re.sub(r"\d{1,2}:\d{2}", _clock, cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def pad_short(text: str) -> str:
    if len(text) >= MIN_CHARS:
        return text
    if not text:
        return text
    return f"{text}, sim, exatamente isso."


def free_vram_mb() -> int | None:
    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None
    free, _total = torch.cuda.mem_get_info()
    return int(free // (1024 * 1024))


def choose_device(prefer: str, free_mb: int | None, need_mb: int = VRAM_NEED_MB) -> str:
    if prefer != "cuda":
        return "cpu"
    if free_mb is None or free_mb < need_mb:
        return "cpu"
    return "cuda"


def spoken_parts(text: str) -> list[str]:
    """Parte o texto em trechos curtos. O Kokoro corta a fala perto de 510 fonemas."""
    cleaned = sanitize(text)
    if not cleaned:
        return []
    units: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
        sentence = sentence.strip()
        if sentence:
            units.extend(_fit_words(sentence, PART_CHARS))
    packed: list[str] = []
    current = ""
    for unit in units:
        candidate = unit if not current else f"{current} {unit}"
        if len(candidate) <= PART_CHARS:
            current = candidate
        else:
            if current:
                packed.append(current)
            current = unit
    if current:
        packed.append(current)
    return [pad_short(part) for part in packed]


def _fit_words(text: str, limit: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    parts: list[str] = []
    current = ""
    for word in words:
        if len(word) > limit:
            if current:
                parts.append(current)
                current = ""
            for start in range(0, len(word), limit):
                parts.append(word[start:start + limit])
            continue
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= limit:
            current = candidate
        else:
            parts.append(current)
            current = word
    if current:
        parts.append(current)
    return parts


def _chunks_to_wav(chunks) -> bytes:
    pcm = b"".join(chunk.audio.cpu().numpy().astype("<f4").tobytes() for chunk in chunks)
    import numpy as np

    floats = np.frombuffer(pcm, dtype="<f4")
    ints = (np.clip(floats, -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(ints.tobytes())
    return buffer.getvalue()


def join_wavs(wavs: list[bytes]) -> bytes:
    frames = []
    for wav in wavs:
        with wave.open(io.BytesIO(wav), "rb") as handle:
            frames.append(handle.readframes(handle.getnframes()))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"".join(frames))
    return buffer.getvalue()


def _clock(match: re.Match[str]) -> str:
    hours, minutes = match.group(0).split(":")
    h = int(hours) % 24
    m = int(minutes) % 60
    if m == 0:
        return f"{h} horas"
    return f"{h} horas e {m} minutos"


class LocalVoice:
    def __init__(self, store: Store, device: str = "cuda", voice: str = DEFAULT_VOICE):
        self.store = store
        self.prefer = device if device in {"cuda", "cpu"} else "cpu"
        self.device = "cpu"
        self.configured_voice = voice
        self._pipeline = None
        self._loaded_device: str | None = None
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def arm(self) -> str:
        """O seletor de voz ligou. Sobe na placa só se couber."""
        with self._lock:
            self._cancel_timer()
            self.device = choose_device(self.prefer, free_vram_mb())
            self._ensure_pipeline()
            self._schedule_release()
            return self.device

    def warm(self) -> None:
        self.arm()

    def speak(self, text: str) -> bytes:
        wavs = list(self.speak_parts(text))
        if len(wavs) == 1:
            return wavs[0]
        return join_wavs(wavs)

    def speak_parts(self, text: str):
        parts = spoken_parts(text)
        if not parts:
            raise SpeechError("Nada para falar.")
        with self._lock:
            self._cancel_timer()
            if self._loaded_device != "cuda":
                self.device = choose_device(self.prefer, free_vram_mb())
            pipeline = self._ensure_pipeline()
            voice = self._voice_name()
            produced = False
            wavs = []
            try:
                for part in parts:
                    chunks = list(pipeline(part, voice=voice))
                    if not chunks:
                        continue
                    produced = True
                    wavs.append(_chunks_to_wav(chunks))
            finally:
                self._schedule_release()
        if not produced:
            raise SpeechError("O Kokoro não devolveu áudio.")
        yield from wavs

    def preview(self) -> bytes:
        return self.speak(SAMPLE_LINE)

    def profile(self) -> dict:
        return {
            "engine": "kokoro",
            "voice": self._voice_name(),
            "device": self.device,
            "ready": True,
        }

    def save_profile(self, prompt: str, style: str, gender: str) -> None:
        gender = gender if gender in {"female", "male"} else ""
        self.store.set_setting("voice_gender", gender)
        self.store.set_setting("voice_name", VOICE_MAP.get(gender, DEFAULT_VOICE))

    def _voice_name(self) -> str:
        selected = self.store.get_setting("voice_name", self.configured_voice)
        if selected in {"pf_dora", "pm_alex", "pm_santa"}:
            return selected
        gender = self.store.get_setting("voice_gender", "male")
        return VOICE_MAP.get(gender, DEFAULT_VOICE)

    def _ensure_pipeline(self):
        if self._pipeline is not None and self._loaded_device == self.device:
            return self._pipeline
        if self._pipeline is not None and self._loaded_device != self.device:
            self._move(self.device)
            return self._pipeline
        from kokoro import KPipeline

        try:
            self._pipeline = KPipeline(lang_code="p", device=self.device, repo_id="hexgrad/Kokoro-82M")
        except RuntimeError:
            self._pipeline = KPipeline(lang_code="p", device="cpu", repo_id="hexgrad/Kokoro-82M")
            self.device = "cpu"
        self._loaded_device = self.device
        list(self._pipeline("Aquecimento.", voice=self._voice_name()))
        return self._pipeline

    def _move(self, device: str) -> None:
        try:
            self._pipeline.model.to(device)
        except RuntimeError:
            device = "cpu"
            self._pipeline.model.to("cpu")
        self.device = device
        self._loaded_device = device
        if device == "cpu":
            self._empty_cache()

    def _schedule_release(self) -> None:
        self._cancel_timer()
        if self._loaded_device != "cuda":
            return
        timer = threading.Timer(GPU_HOLD_SECONDS, self.release_gpu)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def release_gpu(self) -> None:
        with self._lock:
            self._timer = None
            if self._pipeline is None or self._loaded_device != "cuda":
                return
            self._move("cpu")

    def _empty_cache(self) -> None:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            return