"""
STT Local Fallback using Faster-Whisper
Uses the Large-v3-Turbo model as requested.
"""
import os
import logging
import io
from typing import Optional

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

log = logging.getLogger("seeker.stt.local")

# Singleton for the model to avoid reloading
_MODEL_CACHE = None

def get_whisper_model():
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        if WhisperModel is None:
            log.error("[stt_local] faster-whisper não está instalado.")
            return None
            
        try:
            log.info("[stt_local] Carregando Whisper Large-v3 Turbo (Local)...")
            # large-v3-turbo é suportado no faster-whisper
            _MODEL_CACHE = WhisperModel(
                "large-v3-turbo", 
                device="cpu",      # User requested zero VRAM impact for Seeker
                compute_type="int8" # Optimized for CPU
            )
            log.info("[stt_local] Modelo carregado com sucesso.")
        except Exception as e:
            log.error(f"[stt_local] Falha ao carregar modelo: {e}")
            return None
    return _MODEL_CACHE

async def transcribe_audio_local(audio_bytes: bytes) -> Optional[str]:
    """Transcreve áudio localmente usando Faster-Whisper."""
    model = get_whisper_model()
    if not model:
        return None

    try:
        # Faster-whisper pode receber um stream ou bytes
        audio_stream = io.BytesIO(audio_bytes)
        segments, info = model.transcribe(audio_stream, beam_size=5, language="pt")
        
        text = "".join([segment.text for segment in segments]).strip()
        log.info(f"[stt_local] Transcrição concluída ({len(text)} chars)")
        return text
    except Exception as e:
        log.error(f"[stt_local] Erve na transcrição local: {e}")
        return None
