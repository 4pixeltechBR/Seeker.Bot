"""Vision Cloud Fallback - Gemini 2.5/3.1 Flash com Key Rotation Pool"""

import os
import base64
import logging
from typing import Dict, Optional
import httpx

log = logging.getLogger("seeker.vision.fallback")


class GeminiVLMFallback:
    """Gemini 2.5/3.1 Flash real Vision fallback client com Key Rotation Pool"""

    def __init__(self, api_key: Optional[str] = None):
        raw_keys = api_key or os.getenv("GEMINI_API_KEY", "")
        self.api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        self.current_idx = 0
        self.enabled = len(self.api_keys) > 0
        self.model_id = "gemini-3.1-flash-lite"  # Modelo de visão 3.1 Flash Lite otimizado com cota 500 RPD

    def _get_active_key(self) -> str:
        if not self.api_keys:
            return ""
        return self.api_keys[self.current_idx]

    def _rotate_key(self):
        if len(self.api_keys) > 1:
            self.current_idx = (self.current_idx + 1) % len(self.api_keys)
            log.warning(
                f"[vision-fallback] Rate limit ou erro. Rotacionando chave de visão para a posição {self.current_idx}."
            )

    async def _call_gemini_vision(self, image_path: str, prompt: str) -> str:
        if not self.enabled:
            raise RuntimeError("Gemini Vision está desativado (sem chaves configuradas).")

        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            img_b64 = base64.b64encode(image_bytes).decode("utf-8")
        except Exception as e:
            log.error(f"[vision-fallback] Falha ao ler imagem em {image_path}: {e}")
            raise e

        # Determina o MIME type com base na extensão
        ext = os.path.splitext(image_path)[1].lower()
        mime_type = "image/png" if ext == ".png" else "image/jpeg"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": img_b64
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.0
            }
        }

        active_key = self._get_active_key()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_id}:generateContent"

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    url,
                    headers={"x-goog-api-key": active_key},
                    json=payload
                )
                if resp.status_code == 429 and len(self.api_keys) > 1:
                    self._rotate_key()
                    active_key = self._get_active_key()
                    resp = await client.post(
                        url,
                        headers={"x-goog-api-key": active_key},
                        json=payload
                    )
                resp.raise_for_status()
                data = resp.json()
                
                candidate = data.get("candidates", [{}])[0]
                text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                return text
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and len(self.api_keys) > 1:
                    self._rotate_key()
                    active_key = self._get_active_key()
                    resp = await client.post(
                        url,
                        headers={"x-goog-api-key": active_key},
                        json=payload
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    candidate = data.get("candidates", [{}])[0]
                    return candidate.get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                else:
                    raise e

    async def extract_text_from_image(self, image_path: str) -> Dict:
        if not self.enabled:
            return {"text": "", "confidence": 0.0, "error": "Gemini not available"}
        
        prompt = "Extract all text from this image. Preserve layout, structure, columns, and formatting exactly. Return raw text only, without any Markdown blocks or comments."
        try:
            text = await self._call_gemini_vision(image_path, prompt)
            return {"text": text, "confidence": 0.95, "_source": "gemini_flash"}
        except Exception as e:
            log.error(f"[vision-fallback] OCR falhou: {e}")
            return {"text": "", "confidence": 0.0, "error": str(e)}

    async def analyze_screenshot(self, image_path: str) -> Dict:
        if not self.enabled:
            return {"analysis": "", "error": "Gemini not available"}
        
        prompt = "Analyze this screenshot. Describe the active interface, main UI elements, potential action targets, and overall page state."
        try:
            analysis = await self._call_gemini_vision(image_path, prompt)
            return {"analysis": analysis, "confidence": 0.90, "_source": "gemini_flash"}
        except Exception as e:
            log.error(f"[vision-fallback] Análise de screenshot falhou: {e}")
            return {"analysis": "", "confidence": 0.0, "error": str(e)}

    async def locate_element(self, image_path: str, description: str) -> Dict:
        if not self.enabled:
            return {"bbox": None, "error": "Gemini not available"}
        
        prompt = f"Locate the element described as: '{description}' in this screenshot. Return the approximate normalized coordinates (ymin, xmin, ymax, xmax) on a 0-1000 scale."
        try:
            text = await self._call_gemini_vision(image_path, prompt)
            return {"bbox": text, "found": True, "_source": "gemini_flash"}
        except Exception as e:
            log.error(f"[vision-fallback] Element localization falhou: {e}")
            return {"bbox": None, "found": False, "error": str(e)}

    async def describe_page(self, image_path: str) -> Dict:
        if not self.enabled:
            return {"description": "", "error": "Gemini not available"}
        
        prompt = "Describe this page. Provide a detailed summary of the main textual, structural, and visual components."
        try:
            description = await self._call_gemini_vision(image_path, prompt)
            return {"description": description, "confidence": 0.92, "_source": "gemini_flash"}
        except Exception as e:
            log.error(f"[vision-fallback] Page description falhou: {e}")
            return {"description": "", "confidence": 0.0, "error": str(e)}

    async def health_check(self) -> bool:
        return self.enabled


def create_gemini_vlm_fallback(api_key: Optional[str] = None):
    fallback = GeminiVLMFallback(api_key)
    return fallback if fallback.enabled else None
