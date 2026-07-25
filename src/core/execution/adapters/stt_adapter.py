"""
STT Adapter — registra Speech-to-Text como ferramenta portada no adapter manager.
Wraps src/skills/stt_groq.py e src/skills/stt_local.py.
"""

import os
import logging
from typing import Awaitable, Callable

log = logging.getLogger("seeker.execution.adapters.stt")

_tag = "STT"
_prompt_desc = (
    "[STT: \"caminho_do_arquivo\"] — Transcreve um arquivo de áudio/vídeo para texto via Groq Whisper. "
    "Use quando o usuário enviar áudio ou pedir transcrição."
)

_executor: Callable | None = None


async def _stt_executor(arg: str, response_text: str = "") -> str:
    try:
        if arg and os.path.isfile(arg):
            with open(arg, "rb") as f:
                audio_bytes = f.read()
        else:
            return "❌ Caminho de áudio inválido para STT."

        from src.skills.stt_groq import transcribe_audio_groq
        text = await transcribe_audio_groq(audio_bytes)
        if text:
            return f"📝 <b>Transcrição:</b>\n{text}"
        return "❌ Não foi possível transcrever o áudio."
    except Exception as e:
        log.error(f"[stt_adapter] Erro: {e}", exc_info=True)
        return f"❌ Erro na transcrição: {e}"


def register():
    global _executor
    _executor = _stt_executor
    from src.core.execution.adapters.manager import register_adapter
    register_adapter(
        "stt", _tag, _prompt_desc, _stt_executor,
        examples=[
            '[STT: "/tmp/audio.mp3"]',
            '[STT: "C:\\\\Users\\\\Victor\\\\Desktop\\\\recording.ogg"]',
        ],
    )
    log.info("Adaptador STT registrado com sucesso.")
