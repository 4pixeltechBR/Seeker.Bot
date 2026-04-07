"""
Captura de Tela (Desktop Takeover L1)

Usa mss para captura rápida + Pillow para compressão JPEG 720p.
JPEG comprimido (~200-400KB) vs PNG full-size (~3-5MB):
  - Menor payload = menos tempo de encode base64 para VLM
  - Menos VRAM consumida pelo VLM durante inferência
  - Upload mais rápido para Telegram
"""
import io
import mss
from PIL import Image


# Resolução máxima para o VLM — 720p é suficiente para OCR e localização
VLM_MAX_RESOLUTION = (1280, 720)
JPEG_QUALITY = 80


async def capture_desktop(
    max_resolution: tuple[int, int] = VLM_MAX_RESOLUTION,
    quality: int = JPEG_QUALITY,
) -> bytes:
    """Captura a tela principal e retorna JPEG comprimido em bytes."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        raw = sct.grab(monitor)

        img = Image.frombytes("RGB", raw.size, raw.rgb)

        # Resize mantendo aspect ratio — LANCZOS para qualidade de downscale
        img.thumbnail(max_resolution, Image.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()
