import logging
import asyncio
from src.core.execution.adapters.manager import register_adapter

log = logging.getLogger("seeker.execution.adapters.media")

def register():
    desc = (
        "6. GERAÇÃO E TRANSCRIÇÃO DE MÍDIA (MEDIA):\n"
        "   Use para gerar imagens, sintetizar voz ou transcrever áudio.\n"
        "   Gerar Imagem: `[IMAGE_GEN: \"prompt\"]` (Exemplo: `[IMAGE_GEN: \"um gato cibernético\"]`)\n"
        "   Gerar Voz (TTS): `[TTS_GEN: \"texto para falar\"]` (Exemplo: `[TTS_GEN: \"Olá, como posso ajudar?\"]`)\n"
        "   Transcrever Áudio: `[TRANSCRIBE_AUDIO: \"caminho/do/audio.ogg\"]` (Exemplo: `[TRANSCRIBE_AUDIO: \"audio.mp3\"]`)\n"
    )

    async def execute_image_gen(arg: str, response_text: str) -> str:
        try:
            from seeker_agent.tools.image_generation_tool import _handle_image_generate
        except ImportError as ie:
            log.error(f"Erro ao importar image_generation_tool: {ie}")
            return f"[ERRO: Geração de imagem indisponível devido a erro de dependências: {ie}]"

        try:
            res = await asyncio.to_thread(_handle_image_generate, {"prompt": arg})
            return res
        except Exception as e:
            log.error(f"Falha na geração de imagem: {e}")
            return f"[ERRO ao gerar imagem: {e}]"

    async def execute_tts_gen(arg: str, response_text: str) -> str:
        try:
            from seeker_agent.tools.tts_tool import text_to_speech_tool
        except ImportError as ie:
            log.error(f"Erro ao importar tts_tool: {ie}")
            return f"[ERRO: Sintetizador de voz (TTS) indisponível devido a erro de dependências: {ie}]"

        try:
            res = await asyncio.to_thread(text_to_speech_tool, text=arg)
            return str(res)
        except Exception as e:
            log.error(f"Falha na síntese de voz: {e}")
            return f"[ERRO ao sintetizar voz: {e}]"

    async def execute_transcribe_audio(arg: str, response_text: str) -> str:
        try:
            from seeker_agent.tools.transcription_tools import transcribe_audio
        except ImportError as ie:
            log.error(f"Erro ao importar transcription_tools: {ie}")
            return f"[ERRO: Transcritor de áudio indisponível devido a erro de dependências: {ie}]"

        try:
            res = await asyncio.to_thread(transcribe_audio, arg)
            return str(res)
        except Exception as e:
            log.error(f"Falha na transcrição de áudio: {e}")
            return f"[ERRO ao transcrever áudio: {e}]"

    register_adapter("media", "IMAGE_GEN", desc, execute_image_gen)
    register_adapter("media", "TTS_GEN", "", execute_tts_gen)
    register_adapter("media", "TRANSCRIBE_AUDIO", "", execute_transcribe_audio)
