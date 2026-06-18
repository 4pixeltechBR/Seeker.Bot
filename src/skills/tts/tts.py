import os
import logging
import asyncio
import requests
import uuid

log = logging.getLogger("seeker.tts")

DEFAULT_EDGE_VOICE = "pt-BR-AntonioNeural"
DEFAULT_ELEVENLABS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel (exemplo)

class TTSGenerator:
    """Mecanismo de Text-to-Speech do Seeker.Bot (Edge TTS gratuito / ElevenLabs / OpenAI)."""

    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "data",
            "audio_cache"
        )
        os.makedirs(self.output_dir, exist_ok=True)

    async def generate_speech(self, text: str, voice: str | None = None, provider: str | None = None) -> str:
        """Gera áudio a partir do texto e salva no diretório de cache, retornando o caminho do arquivo."""
        if not text or not text.strip():
            return "❌ O texto para gerar fala é obrigatório."

        provider = (provider or os.getenv("TTS_PROVIDER", "edge")).lower().strip()
        filename = f"tts_{uuid.uuid4().hex}.mp3"
        output_path = os.path.join(self.output_dir, filename)

        log.info(f"[tts] Gerando fala via provider '{provider}' para texto de {len(text)} caracteres.")

        if provider == "elevenlabs":
            api_key = os.getenv("ELEVENLABS_API_KEY", "")
            if api_key:
                voice_id = voice or os.getenv("ELEVENLABS_VOICE_ID", DEFAULT_ELEVENLABS_VOICE_ID)
                return await self._generate_elevenlabs(text, voice_id, api_key, output_path)
            else:
                log.warning("[tts] ELEVENLABS_API_KEY não configurada. Usando Edge TTS gratuito como fallback.")
                provider = "edge"

        if provider == "openai":
            api_key = self.pipeline.api_keys.get("openai") or os.getenv("OPENAI_API_KEY", "")
            if api_key:
                voice_name = voice or os.getenv("OPENAI_VOICE", "alloy")
                return await self._generate_openai(text, voice_name, api_key, output_path)
            else:
                log.warning("[tts] OpenAI API key não configurada. Usando Edge TTS gratuito como fallback.")
                provider = "edge"

        # Edge TTS (padrão gratuito)
        voice_name = voice or os.getenv("EDGE_VOICE", DEFAULT_EDGE_VOICE)
        return await self._generate_edge(text, voice_name, output_path)

    async def _generate_edge(self, text: str, voice: str, output_path: str) -> str:
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
            log.info(f"[tts] Áudio gerado com sucesso via Edge TTS: {output_path}")
            return output_path
        except ImportError:
            # Auto-instalação rápida de edge-tts se ausente
            log.warning("[tts] edge-tts não está instalado. Tentando instalar dinamicamente...")
            try:
                import subprocess
                subprocess.run(["pip", "install", "edge-tts"], check=True, stdout=subprocess.DEVNULL)
                import edge_tts
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(output_path)
                return output_path
            except Exception as e:
                log.error(f"[tts] Falha ao auto-instalar edge-tts: {e}")
                return f"❌ Erro ao inicializar o Edge TTS: {e}. Instale via 'pip install edge-tts'."
        except Exception as e:
            log.error(f"[tts] Erro na síntese Edge TTS: {e}", exc_info=True)
            return f"❌ Falha no Edge TTS: {e}"

    async def _generate_elevenlabs(self, text: str, voice_id: str, api_key: str, output_path: str) -> str:
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
        }
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        
        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                lambda: requests.post(url, json=payload, headers=headers, timeout=30)
            )
            res.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(res.content)
            log.info(f"[tts] Áudio gerado com sucesso via ElevenLabs: {output_path}")
            return output_path
        except Exception as e:
            log.error(f"[tts] Falha ao invocar ElevenLabs: {e}", exc_info=True)
            return f"❌ Falha no ElevenLabs TTS: {e}"

    async def _generate_openai(self, text: str, voice: str, api_key: str, output_path: str) -> str:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "tts-1",
            "input": text,
            "voice": voice
        }
        url = "https://api.openai.com/v1/audio/speech"
        
        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                lambda: requests.post(url, json=payload, headers=headers, timeout=30)
            )
            res.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(res.content)
            log.info(f"[tts] Áudio gerado com sucesso via OpenAI TTS: {output_path}")
            return output_path
        except Exception as e:
            log.error(f"[tts] Falha ao invocar OpenAI TTS: {e}", exc_info=True)
            return f"❌ Falha no OpenAI TTS: {e}"
