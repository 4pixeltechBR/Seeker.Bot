"""
Gemini VLM Client (Vision 3.0).

Handles both General Reasoning (gemini-2.5-pro) and Spatial Grounding (gemini-robotics-er-1.6).
Uses the modern google.genai SDK.
"""
import os
import io
import logging
import asyncio
from typing import Dict, Optional
from PIL import Image

try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

log = logging.getLogger("seeker.vision.gemini")

class GeminiVLMClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.enabled = bool(self.api_key) and GEMINI_AVAILABLE
        
        if self.enabled:
            # We initialize the client per method or globally
            self.client = genai.Client(api_key=self.api_key)
            log.info("[vision] Gemini VLM Client initialized (modern SDK)")
        else:
            log.warning("[vision] Gemini VLM Client disabled (no API key or genai not installed)")

    def _get_image(self, image_path_or_bytes: str | bytes) -> Image.Image:
        """Helper to load image from path or bytes."""
        if isinstance(image_path_or_bytes, bytes):
            return Image.open(io.BytesIO(image_path_or_bytes))
        return Image.open(image_path_or_bytes)

    async def _call_gemini(self, model_name: str, prompt: str, image: Image.Image, temperature: float = 0.0) -> str:
        """Call Gemini model asynchronously."""
        if not self.enabled:
            raise RuntimeError("Gemini API not enabled")
            
        def _sync_call():
            response = self.client.models.generate_content(
                model=model_name,
                contents=[image, prompt],
                config=types.GenerateContentConfig(
                    temperature=temperature,
                )
            )
            return response.text

        return await asyncio.to_thread(_sync_call)

    async def extract_text_from_image(self, image_path: str) -> Dict:
        """OCR fallback (Gemini 2.5 Pro)"""
        try:
            img = self._get_image(image_path)
            model_name = "gemini-2.5-pro"
            prompt = "Extraia todo o texto visível nesta imagem. Retorne apenas o texto cru, preservando o layout na medida do possível."
            
            text = await self._call_gemini(model_name, prompt, img, temperature=0.0)
            return {"text": text.strip(), "confidence": 0.95, "_source": model_name}
        except Exception as e:
            log.error(f"[gemini] Extract text error: {e}")
            return {"text": "", "confidence": 0.0, "error": str(e)}

    async def analyze_screenshot(self, image_path: str | bytes, prompt: Optional[str] = None) -> Dict:
        """General scene understanding (Gemini 2.5)"""
        try:
            img = self._get_image(image_path)
            model_name = "gemini-2.5-pro"
            prompt = prompt or "Descreva a interface atual. O que estou vendo? Se for um aplicativo, qual é? Há avisos ou elementos interativos principais?"

            analysis = await self._call_gemini(model_name, prompt, img, temperature=0.3)
            return {"analysis": analysis.strip(), "confidence": 0.90, "_source": model_name}
        except Exception as e:
            log.error(f"[gemini] Analyze screenshot error: {e}")
            return {"analysis": "", "error": str(e)}

    async def locate_element(self, image_path: str, description: str) -> Dict:
        """
        Spatial Grounding (Gemini Robotics-ER 1.6).
        Returns coordinates normalized or exact pixels if math is applied.
        """
        try:
            img = self._get_image(image_path)
            width, height = img.size
            
            # Usando o modelo aprovado pelo usuário para grounding
            model_name = "gemini-robotics-er-1.6" 
            
            prompt = (
                f"Você é um agente de controle de interface. "
                f"Retorne o bounding box do elemento: '{description}'. "
                f"Formato de saída estrito: [ymin, xmin, ymax, xmax] normalizados entre 0 e 1000. "
                f"Se o elemento não existir, retorne: [not_found]"
            )
            
            try:
                result = await self._call_gemini(model_name, prompt, img, temperature=0.0)
            except Exception as routing_e:
                log.warning(f"[gemini] Erro no Robotics-ER: {routing_e}. Tentando fallback para gemini-2.5-pro...")
                # Fallback to general model if Robotics-ER is not active/available for this key
                model_name = "gemini-2.5-pro"
                result = await self._call_gemini(model_name, prompt, img, temperature=0.0)

            result = result.strip()
            
            if "[not_found]" in result.lower() or not result.startswith("["):
                return {"bbox": None, "found": False, "raw": result, "_source": model_name}
                
            import re
            match = re.search(r'\[(.*?)\]', result)
            if match:
                coords = [int(x.strip()) for x in match.group(1).split(',')]
                if len(coords) == 4:
                    ymin, xmin, ymax, xmax = coords
                    # Convert 0-1000 scale to absolute pixels
                    abs_xmin = int((xmin / 1000.0) * width)
                    abs_xmax = int((xmax / 1000.0) * width)
                    abs_ymin = int((ymin / 1000.0) * height)
                    abs_ymax = int((ymax / 1000.0) * height)
                    
                    center_x = (abs_xmin + abs_xmax) // 2
                    center_y = (abs_ymin + abs_ymax) // 2
                    
                    return {
                        "found": True,
                        "center": [center_x, center_y],
                        "bbox": [abs_xmin, abs_ymin, abs_xmax, abs_ymax],
                        "width": width,
                        "height": height,
                        "_source": model_name
                    }
                    
            return {"bbox": None, "found": False, "raw": result, "error": "Parsing error"}
        except Exception as e:
            log.error(f"[gemini] Locate element error: {e}")
            return {"bbox": None, "found": False, "error": str(e)}

    async def describe_page(self, image_path: str) -> Dict:
        """Scene description."""
        try:
            img = self._get_image(image_path)
            model_name = "gemini-2.5-pro"
            prompt = "Forneça uma descrição densa e técnica desta tela para o log do sistema."
            description = await self._call_gemini(model_name, prompt, img, temperature=0.2)
            return {"description": description.strip(), "confidence": 0.95, "_source": model_name}
        except Exception as e:
            return {"description": "", "error": str(e)}

    async def health_check(self) -> bool:
        return self.enabled
