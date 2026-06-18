import os
import logging
import requests
import asyncio

log = logging.getLogger("seeker.transcription")

class AudioTranscriber:
    """Mecanismo de transcrição de áudio (Speech-to-Text) do Seeker.Bot."""

    def __init__(self, pipeline):
        self.pipeline = pipeline

    async def transcribe(self, audio_file_path: str, provider: str | None = None) -> str:
        """Transcreve um arquivo de áudio local e retorna o texto transcrito."""
        if not audio_file_path or not os.path.exists(audio_file_path):
            return f"❌ Arquivo de áudio não encontrado no caminho: {audio_file_path}"

        provider = (provider or os.getenv("STT_PROVIDER", "groq")).lower().strip()

        if provider == "groq":
            api_key = self.pipeline.api_keys.get("groq") or os.getenv("GROQ_API_KEY", "")
            if api_key:
                return await self._transcribe_groq(audio_file_path, api_key)
            else:
                log.warning("[transcription] GROQ_API_KEY não configurada. Usando OpenAI como fallback.")
                provider = "openai"

        if provider == "openai":
            api_key = self.pipeline.api_keys.get("openai") or os.getenv("OPENAI_API_KEY", "")
            if api_key:
                return await self._transcribe_openai(audio_file_path, api_key)
            else:
                return "❌ Nenhuma chave de API para transcrição (Groq ou OpenAI) configurada."

        return f"❌ Provedor de transcrição desconhecido: {provider}"

    async def _transcribe_groq(self, file_path: str, api_key: str) -> str:
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        try:
            loop = asyncio.get_running_loop()
            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f.read())}
            
            data = {"model": "whisper-large-v3", "response_format": "json"}
            
            log.info(f"[transcription] Enviando áudio {file_path} para API da Groq...")
            res = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, files=files, data=data, timeout=60)
            )
            res.raise_for_status()
            result_json = res.json()
            transcription = result_json.get("text", "").strip()
            log.info(f"[transcription] Transcrição via Groq completa.")
            return transcription
            
        except Exception as e:
            log.error(f"[transcription] Erro ao transcrever via Groq: {e}", exc_info=True)
            return f"❌ Falha na transcrição via Groq: {e}"

    async def _transcribe_openai(self, file_path: str, api_key: str) -> str:
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        try:
            loop = asyncio.get_running_loop()
            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f.read())}
            
            data = {"model": "whisper-1"}
            
            log.info(f"[transcription] Enviando áudio {file_path} para API da OpenAI...")
            res = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, files=files, data=data, timeout=60)
            )
            res.raise_for_status()
            result_json = res.json()
            transcription = result_json.get("text", "").strip()
            log.info(f"[transcription] Transcrição via OpenAI completa.")
            return transcription
            
        except Exception as e:
            log.error(f"[transcription] Erro ao transcrever via OpenAI: {e}", exc_info=True)
            return f"❌ Falha na transcrição via OpenAI: {e}"
