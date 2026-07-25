"""
core.billing.fallback_registry — Fallback chains para operações GCP.

Define a ordem de tentativa para cada operação:
  - "analyze_thumbnail": [Cloud Vision, MediaPipe local, heurística OpenCV]
  - "synthesize_speech": [Cloud TTS, Edge TTS (free), OpenAI TTS]
  - "geocode_query":    [Maps Geocoding, Places Text Search, Gemini LLM fallback]
  - "static_map":       [Maps Static API, sem fallback (só imagem)]

Cada fallback é registrado no GCPBudgetGuard via `register_fallback(operation, fn)`.
Quando o budget do serviço GCP principal está esgotado, o Seeker.Bot cai
automaticamente para a próxima opção — **zero interrupção** do pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

log = logging.getLogger("seeker.billing.fallbacks")


# ── Fallback Chains ───────────────────────────────────────────────────

# analyze_thumbnail: Cloud Vision → MediaPipe local → OpenCV heurística
FALLBACK_CHAINS: dict[str, list[str]] = {
    "analyze_thumbnail": ["cloud_vision", "mediapipe_local", "opencv_heuristic"],
    "synthesize_speech": ["cloud_text_to_speech", "edge_tts", "openai_tts"],
    "geocode_query":     ["maps_geocoding", "places_text_search", "gemini_llm"],
    "static_map":        ["maps_static"],  # sem fallback (visual)
    "places_text_search": ["places_api", "gemini_llm"],
}


def get_chain(operation: str) -> list[str]:
    """Retorna a ordem de fallback para uma operação."""
    return FALLBACK_CHAINS.get(operation, [])


def register_all_fallbacks() -> None:
    """Registra todos os fallbacks conhecidos no GCPBudgetGuard.

    Chamado uma vez no startup do Seeker. As funções aqui referenciadas
    são importadas lazy para evitar ciclos de import.
    """
    from src.core.billing.gcp_budget_guard import GCPBudgetGuard

    guard = GCPBudgetGuard.get()

    # ── analyze_thumbnail ─────────────────────────────────────────────
    # Primary: Cloud Vision (label + face + safe_search)
    # Fallback 1: MediaPipe local (já existe em thumbnail_analyzer.py)
    # Fallback 2: OpenCV heurística (já existe em thumbnail_analyzer.py)

    async def _cloud_vision_thumbnail(video_id: str) -> dict[str, Any]:
        """Análise via Cloud Vision API."""
            _download_thumbnail, _analyze_face, _analyze_color, _analyze_text
        )
        import numpy as np
        from PIL import Image
        import io
        import aiohttp

        api_key = os.getenv("GOOGLE_CLOUD_API_KEY", "")
        img_bytes = await _download_thumbnail(video_id)
        if img_bytes is None:
            return {"score": 0.5, "error": "download_failed"}

        # Análise local (face/color/text) como sempre
        np_img = np.array(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
        face = _analyze_face(np_img)
        color = _analyze_color(np_img)
        text = _analyze_text(np_img)

        # Bônus Cloud Vision: safe-search + label semantic
        try:
            url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
            payload = {
                "requests": [{
                    "image": {"content": _b64(img_bytes)},
                    "features": [
                        {"type": "SAFE_SEARCH_DETECTION"},
                        {"type": "LABEL_DETECTION", "maxResults": 5},
                    ]
                }]
            }
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        r = data.get("responses", [{}])[0]
                        safe = r.get("safeSearchAnnotation", {})
                        # Penaliza se adult/violence/racy >= LIKELY
                        bad = sum(1 for k in ("adult", "violence", "racy")
                                  if safe.get(k, "UNLIKELY") in ("LIKELY", "VERY_LIKELY"))
                        safety_bonus = max(0.0, 1.0 - 0.3 * bad)
                        labels = [l["description"] for l in r.get("labelAnnotations", [])]
                        # Score de relevância semântica: nº de labels
                        semantic_score = min(len(labels) / 5.0, 1.0)
                        return {
                            "score": (face * 0.3 + color["composite"] * 0.3
                                      + text * 0.2 + semantic_score * 0.1 + safety_bonus * 0.1),
                            "face": face,
                            "color": color,
                            "text": text,
                            "labels": labels,
                            "safety_bonus": safety_bonus,
                            "source": "cloud_vision",
                        }
        except Exception as e:
            log.debug(f"[fallback] Cloud Vision falhou em _cloud_vision_thumbnail: {e}")

        # Se Vision falhou, retorna só análise local (sem bônus)
        score = face * FACE_WEIGHT + color["composite"] * COLOR_WEIGHT + text * TEXT_WEIGHT
        return {"score": score, "face": face, "color": color, "text": text,
                "source": "local_only"}

    async def _mediapipe_thumbnail(video_id: str) -> dict[str, Any]:
        """Análise local via MediaPipe + OpenCV."""
        return await analyze_thumbnail(video_id)

    async def _opencv_heuristic_thumbnail(video_id: str) -> dict[str, Any]:
        """Último recurso: análise OpenCV pura (sem MediaPipe)."""
        import numpy as np
        from PIL import Image
        import io

        img_bytes = await _download_thumbnail(video_id)
        if img_bytes is None:
            return {"score": 0.5, "face": 0.0, "color": {}, "text": 0.0}
        np_img = np.array(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
        # Sem MediaPipe, retorna análise de cor/texto apenas
        color = _analyze_color(np_img)
        text = _analyze_text(np_img)
        score = color["composite"] * 0.6 + text * 0.4
        return {"score": score, "face": 0.0, "color": color, "text": text,
                "source": "opencv_only"}

    guard.register_fallback("analyze_thumbnail", _cloud_vision_thumbnail, position=0)
    guard.register_fallback("analyze_thumbnail", _mediapipe_thumbnail, position=1)
    guard.register_fallback("analyze_thumbnail", _opencv_heuristic_thumbnail, position=2)

    # ── synthesize_speech ─────────────────────────────────────────────
    async def _cloud_tts_synthesize(text: str, voice: str = "pt-BR-Standard-A", **kw) -> bytes:
        import aiohttp
        import os
        api_key = os.getenv("GOOGLE_CLOUD_API_KEY", "")
        url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
        payload = {
            "input": {"text": text},
            "voice": {"languageCode": "pt-BR", "name": voice},
            "audioConfig": {"audioEncoding": "MP3"},
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(f"TTS API {resp.status}: {data.get('error', {}).get('message')}")
                import base64
                return base64.b64decode(data["audioContent"])

    async def _edge_tts_synthesize(text: str, voice: str = "pt-BR-AntonioNeural", **kw) -> bytes:
        # Edge TTS via subprocess
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            out_path = f.name
        try:
            subprocess.run([
                "edge-tts", "--voice", voice, "--text", text, "--write-media", out_path,
            ], check=True, capture_output=True, timeout=30)
            with open(out_path, "rb") as f:
                return f.read()
        finally:
            import os as _os
            try:
                _os.unlink(out_path)
            except Exception:
                pass

    async def _openai_tts_synthesize(text: str, voice: str = "alloy", **kw) -> bytes:
        import os
        import aiohttp
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY não configurada")
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": "tts-1", "input": text, "voice": voice},
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"OpenAI TTS {resp.status}")
                return await resp.read()

    guard.register_fallback("synthesize_speech", _cloud_tts_synthesize, position=0)
    guard.register_fallback("synthesize_speech", _edge_tts_synthesize, position=1)
    guard.register_fallback("synthesize_speech", _openai_tts_synthesize, position=2)

    # ── geocode_query ─────────────────────────────────────────────────
    async def _maps_geocode(query: str) -> dict[str, Any] | None:
        """Geocoding via Maps API."""
        import os
        import aiohttp
        api_key = os.getenv("GOOGLE_CLOUD_API_KEY", "")
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"address": query, "key": api_key}) as resp:
                data = await resp.json()
                if data.get("status") == "OK" and data.get("results"):
                    loc = data["results"][0]["geometry"]["location"]
                    return {"lat": loc["lat"], "lng": loc["lng"], "formatted": data["results"][0]["formatted_address"]}
        return None

    async def _places_text_search(query: str) -> dict[str, Any] | None:
        """Places API (New) Text Search."""
        import os
        import aiohttp
        api_key = os.getenv("GOOGLE_CLOUD_API_KEY", "")
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"textQuery": query}, headers=headers) as resp:
                data = await resp.json()
                if data.get("places"):
                    p = data["places"][0]
                    return {
                        "name": p.get("displayName", {}).get("text"),
                        "address": p.get("formattedAddress"),
                        "location": p.get("location"),
                    }
        return None

    async def _gemini_geocode(query: str) -> dict[str, Any] | None:
        """Último recurso: pede ao Gemini pra adivinhar coordenadas."""
        try:
            from src.providers.base import invoke_with_fallback, LLMRequest
            from config.models import CognitiveRole
            resp = await invoke_with_fallback(
                CognitiveRole.JUDGE,
                LLMRequest(
                    messages=[{"role": "user", "content":
                        f"Responda APENAS JSON com coordenadas lat/lng para: {query}. "
                        f"Formato: {{\"lat\": -23.5, \"lng\": -46.6}}. "
                        f"Se não souber, retorne null."}],
                    temperature=0.0,
                    max_tokens=50,
                    response_format="json",
                ),
                None, None,  # router/keys resolvidos pelo pipeline
            )
            from src.core.utils import parse_llm_json
            return parse_llm_json(resp.text)
        except Exception:
            return None

    guard.register_fallback("geocode_query", _maps_geocode, position=0)
    guard.register_fallback("geocode_query", _places_text_search, position=1)
    guard.register_fallback("geocode_query", _gemini_geocode, position=2)

    log.info("[fallbacks] Fallback chains registrados para %d operações", len(FALLBACK_CHAINS))


def _b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode()


# ── Usage Example ─────────────────────────────────────────────────────
#
#   from src.core.billing.gcp_budget_guard import GCPBudgetGuard, BudgetExceededError
#   from src.core.billing.fallback_registry import register_all_fallbacks
#
#   register_all_fallbacks()
#   guard = GCPBudgetGuard.get()
#
#   async def analyze(video_id):
#       try:
#           return await guard.consume("cloud_vision", units=1)
#       except BudgetExceededError:
#           for fallback in guard.get_fallbacks("analyze_thumbnail"):
#               result = await fallback(video_id)
#               if result:
#                   return result
#       raise RuntimeError("Vision + fallbacks falharam")