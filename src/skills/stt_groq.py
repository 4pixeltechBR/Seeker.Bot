import os
import io
import logging
import httpx

log = logging.getLogger("seeker.stt")

async def transcribe_audio_groq(audio_bytes: bytes, filename: str = "audio.ogg") -> str:
    """
    Transcreve áudio usando a API do Whisper via Groq.
    Extremamente rápido e não pesa na VRAM local.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        log.error("[stt] GROQ_API_KEY não configurada no .env", exc_info=True)
        return ""

    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    files = {
        "file": (filename, audio_bytes, "audio/ogg"),
    }
    
    data = {
        "model": "whisper-large-v3-turbo",
        "language": "pt",  # Força idioma pt-BR para evitar hallucination de tradução
        "response_format": "json"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, files=files, data=data)
            response.raise_for_status()
            
            result = response.json()
            text = result.get("text", "").strip()
            log.info(f"[stt] Transcrição concluída ({len(text)} chars)")
            return text
            
    except Exception as e:
        log.warning(f"[stt] Groq falhou: {e}. Tentando fallback local...")
        try:
            from src.skills.stt_local import transcribe_audio_local
            local_text = await transcribe_audio_local(audio_bytes)
            if local_text:
                log.info("[stt] Transcrição via fallback local concluída.")
                return local_text
        except Exception as local_err:
            log.error(f"[stt] Fallback local também falhou: {local_err}")
            
        return ""
