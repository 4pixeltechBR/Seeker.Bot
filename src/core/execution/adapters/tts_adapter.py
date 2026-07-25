"""
TTS Adapter — registra Text-to-Speech como ferramenta portada no adapter manager.
Wraps src/skills/tts/tts.py (TTSGenerator).
Nao depende do pipeline — usa edge-tts gratuito e Open AI via env var.
"""

import os
import logging
from typing import Callable

log = logging.getLogger("seeker.execution.adapters.tts")

_tag = "TTS"
_prompt_desc = (
    "[TTS: \"texto\"] — Converte texto em áudio falado via Edge TTS (gratuito). "
    "Use quando o usuário pedir para ouvir o resultado ou gerar áudio."
)


async def _tts_executor(arg: str, response_text: str = "") -> str:
    try:
        from src.skills.tts.tts import TTSGenerator

        class _FakePipeline:
            api_keys = {"openai": os.getenv("OPENAI_API_KEY", "")}

        tts = TTSGenerator(_FakePipeline())
        result_path = await tts.generate_speech(arg)
        if result_path and not result_path.startswith("❌"):
            return f"🔊 Áudio gerado: {result_path}"
        return result_path
    except Exception as e:
        log.error(f"[tts_adapter] Erro: {e}", exc_info=True)
        return f"❌ Erro no TTS: {e}"


def register():
    from src.core.execution.adapters.manager import register_adapter
    register_adapter(
        "tts", _tag, _prompt_desc, _tts_executor,
        examples=[
            '[TTS: "Olá, bem-vindo ao Seeker.Bot"]',
            '[TTS: "Reunião amanhã às 14h, não esqueça."]',
        ],
    )
    log.info("Adaptador TTS registrado com sucesso.")
