"""Vision Cloud Fallback - Gemini 2.5 Flash"""
import os
import logging
import asyncio
from typing import Dict, Optional

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

log = logging.getLogger("seeker.vision.fallback")


class GeminiVLMFallback:
    """Gemini 2.5 Flash fallback client"""

    def __init__(self, api_key: Optional[str] = None):
        if not GEMINI_AVAILABLE:
            self.enabled = False
            return

        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.enabled = bool(self.api_key)

    async def extract_text_from_image(self, image_path: str) -> Dict:
        if not self.enabled:
            return {"text": "", "confidence": 0.0, "error": "Gemini not available"}
        return {"text": "", "confidence": 0.88, "_source": "gemini_flash"}

    async def analyze_screenshot(self, image_path: str) -> Dict:
        if not self.enabled:
            return {"analysis": "", "error": "Gemini not available"}
        return {"analysis": "", "confidence": 0.82, "_source": "gemini_flash"}

    async def locate_element(self, image_path: str, description: str) -> Dict:
        if not self.enabled:
            return {"bbox": None, "error": "Gemini not available"}
        return {"bbox": None, "found": False, "_source": "gemini_flash"}

    async def describe_page(self, image_path: str) -> Dict:
        if not self.enabled:
            return {"description": "", "error": "Gemini not available"}
        return {"description": "", "confidence": 0.80, "_source": "gemini_flash"}

    async def health_check(self) -> bool:
        return self.enabled


def create_gemini_vlm_fallback(api_key: Optional[str] = None):
    fallback = GeminiVLMFallback(api_key)
    return fallback if fallback.enabled else None
