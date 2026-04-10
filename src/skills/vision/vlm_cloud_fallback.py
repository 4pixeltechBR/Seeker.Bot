"""
Vision 2.0 — Gemini 2.5 Flash Cloud VLM Fallback (Sprint 12).

Fallback remoto para quando VLM local (Ollama) falha ou está indisponível.
Integrado no cascade 6-tier via um novo tier VLM específico.

Trigger conditions:
1. Ollama offline (health_check falho)
2. GPU semaphore bloqueado >30s
3. VLM local retorna confidence <0.5

Env vars (em .env):
    GEMINI_API_KEY — obrigatório
    GEMINI_VLM_FALLBACK=true — ativa o fallback
    GEMINI_VLM_MODEL=gemini-2.5-flash — modelo a usar

Audit trail integrada com SafetyLayer.audit_log (Sprint 7.3).
"""

import base64
import logging
import os
from typing import Optional

log = logging.getLogger("seeker.vision.vlm_cloud_fallback")


class GeminiVLMFallback:
    """Cliente remoto para Gemini 2.5 Flash (multimodal)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.5-flash",
    ):
        """
        Inicializa cliente Gemini.

        Args:
            api_key: GEMINI_API_KEY. Se None, tenta env var.
            model: Nome do modelo (default: gemini-2.5-flash).
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model

        if not self.api_key:
            log.warning(
                "[gemini_vlm] GEMINI_API_KEY não configurado. "
                "Fallback desabilitado."
            )
            self.enabled = False
            return

        # Lazy import: só importa google-generativeai se realmente usado
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            self.genai = genai
            self.enabled = True
            log.info(f"[gemini_vlm] Client inicializado: model={self.model}")
        except ImportError:
            log.error(
                "[gemini_vlm] google-generativeai não instalado. "
                "Instale: pip install google-generativeai>=0.8.0"
            )
            self.enabled = False
        except Exception as e:
            log.error(f"[gemini_vlm] Falha ao inicializar: {e}")
            self.enabled = False

    async def analyze_screenshot(
        self,
        image_bytes: bytes,
        prompt: str,
    ) -> str:
        """
        Analisa screenshot via Gemini (mesmo formato que VLMClient.analyze_screenshot).

        Args:
            image_bytes: conteúdo da imagem em bytes
            prompt: prompt textual

        Returns:
            Resposta do modelo em string.
        """
        if not self.enabled:
            raise RuntimeError(
                "[gemini_vlm] Fallback não habilitado (chave/biblioteca ausente)"
            )

        try:
            # Converte imagem para base64
            img_b64 = base64.b64encode(image_bytes).decode("utf-8")

            # Cria requisição multimodal
            model = self.genai.GenerativeModel(self.model)
            img_part = {
                "mime_type": "image/png",  # ou detect automaticamente
                "data": img_b64,
            }
            text_part = prompt

            response = model.generate_content(
                [text_part, img_part],
                generation_config={
                    "temperature": 0.1,  # Mesmo que VLMClient local
                    "max_output_tokens": 1024,
                },
            )

            return response.text.strip()

        except Exception as e:
            log.error(f"[gemini_vlm] Erro na requisição: {e}")
            raise

    async def extract_text_from_image(self, image_bytes: bytes) -> str:
        """OCR via Gemini."""
        prompt = (
            "Extract all the text from this image exactly as written. "
            "Preserve the original language. Do not add explanatory text."
        )
        return await self.analyze_screenshot(image_bytes, prompt)

    async def locate_element(
        self,
        image_bytes: bytes,
        description: str,
    ) -> dict:
        """Localiza elemento UI (mesmo formato que VLMClient)."""
        prompt = (
            f"Find the UI element: '{description}'. "
            f"Return ONLY a JSON object with the center coordinates: "
            f'{{"x": <center_x_pixels>, "y": <center_y_pixels>, "confidence": <0.0-1.0>}}'
        )

        raw_text = await self.analyze_screenshot(image_bytes, prompt)
        log.info(f"[gemini_vlm] locate_element raw: {raw_text}")

        # Usa same parser que VLMClient (de vlm_client.py)
        from .vlm_client import _parse_bbox_response

        return _parse_bbox_response(raw_text)

    async def describe_page(self, image_bytes: bytes) -> str:
        """Descrição estruturada da página."""
        prompt = (
            "Describe this webpage screenshot in Portuguese (PT-BR). "
            "List: 1) Page title/header 2) Main content summary "
            "3) Clickable buttons or links visible 4) Any forms or input fields. "
            "Be concise and factual."
        )
        return await self.analyze_screenshot(image_bytes, prompt)

    async def health_check(self) -> bool:
        """Verifica conectividade com Gemini API."""
        if not self.enabled:
            return False

        try:
            model = self.genai.GenerativeModel(self.model)
            # Quick validation call
            response = model.generate_content("ping")
            return response.text is not None
        except Exception as e:
            log.warning(f"[gemini_vlm] Health check falhou: {e}")
            return False


# ── Integration point: Cascade 6-tier ───────────────────────────

def create_gemini_vlm_fallback() -> Optional[GeminiVLMFallback]:
    """
    Factory para criar fallback Gemini se configurado.

    Usado em src/providers/cascade_advanced.py para adicionar
    novo tier VLM ao cascade.
    """
    if not os.getenv("GEMINI_VLM_FALLBACK", "").lower() == "true":
        return None

    try:
        return GeminiVLMFallback()
    except Exception as e:
        log.error(f"[gemini_vlm] Falha ao criar fallback: {e}")
        return None
