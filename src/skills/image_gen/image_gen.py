import os
import json
import logging
import requests
import asyncio
import uuid

log = logging.getLogger("seeker.image_gen")

DEFAULT_FAL_MODEL = "fal-ai/flux/schnell"

class ImageGenerator:
    """Skill de geração de imagens multimodal do Seeker.Bot (Fal.ai Flux / DALL-E 3)."""

    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "data",
            "image_cache"
        )
        os.makedirs(self.output_dir, exist_ok=True)

    async def generate(self, prompt: str, provider: str | None = None) -> str:
        """Gera imagem a partir do prompt e retorna o caminho do arquivo gerado localmente."""
        if not prompt or not prompt.strip():
            return "❌ O prompt da imagem é obrigatório."

        provider = (provider or os.getenv("IMAGE_PROVIDER", "fal")).lower().strip()
        filename = f"img_{uuid.uuid4().hex}.png"
        output_path = os.path.join(self.output_dir, filename)

        log.info(f"[image_gen] Gerando imagem via provider '{provider}' para o prompt: '{prompt}'")

        if provider == "fal":
            fal_key = os.getenv("FAL_KEY", "")
            if fal_key:
                return await self._generate_fal(prompt, fal_key, output_path)
            else:
                log.warning("[image_gen] FAL_KEY não configurada. Usando OpenAI (DALL-E 3) como fallback.")
                provider = "openai"

        if provider == "openai":
            api_key = self.pipeline.api_keys.get("openai") or os.getenv("OPENAI_API_KEY", "")
            if api_key:
                return await self._generate_openai(prompt, api_key, output_path)
            else:
                return "❌ Nenhuma chave de API para geração de imagens (Fal.ai ou OpenAI) configurada."

        return f"❌ Provedor de imagem desconhecido: {provider}"

    async def _generate_fal(self, prompt: str, fal_key: str, output_path: str) -> str:
        model = os.getenv("FAL_MODEL", DEFAULT_FAL_MODEL)
        url = f"https://queue.fal.run/{model}"
        headers = {
            "Authorization": f"Key {fal_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "prompt": prompt,
            "image_size": "landscape_16_9",
            "num_inference_steps": 4,
            "enable_safety_checker": True,
            "sync_mode": True
        }

        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                lambda: requests.post(url, json=payload, headers=headers, timeout=60)
            )
            res.raise_for_status()
            data = res.json()
            
            # Pega URL da imagem resultante
            images = data.get("images", [])
            if not images:
                return "❌ Fal.ai não retornou imagens no payload."
                
            img_url = images[0].get("url")
            
            # Baixa a imagem gerada
            img_res = await loop.run_in_executor(
                None,
                lambda: requests.get(img_url, timeout=30)
            )
            img_res.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(img_res.content)
                
            log.info(f"[image_gen] Imagem gerada via Fal.ai salva em: {output_path}")
            return output_path

        except Exception as e:
            log.error(f"[image_gen] Falha ao invocar Fal.ai: {e}", exc_info=True)
            return f"❌ Falha na geração de imagem via Fal.ai: {e}"

    async def _generate_openai(self, prompt: str, api_key: str, output_path: str) -> str:
        url = "https://api.openai.com/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024"
        }

        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                lambda: requests.post(url, json=payload, headers=headers, timeout=60)
            )
            res.raise_for_status()
            data = res.json()
            
            images = data.get("data", [])
            if not images:
                return "❌ DALL-E 3 não retornou dados de imagem no payload."
                
            img_url = images[0].get("url")
            
            img_res = await loop.run_in_executor(
                None,
                lambda: requests.get(img_url, timeout=30)
            )
            img_res.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(img_res.content)
                
            log.info(f"[image_gen] Imagem gerada via DALL-E 3 salva em: {output_path}")
            return output_path

        except Exception as e:
            log.error(f"[image_gen] Falha ao invocar DALL-E 3: {e}", exc_info=True)
            return f"❌ Falha na geração de imagem via DALL-E 3: {e}"
