"""
Extractors v2.0 — Extração enriquecida de diferentes fontes.

Melhorias:
- YouTube: metadados ricos (canal, duração, data, views, thumbnail)
- Site: limite aumentado para 15K chars + extração de metadados da página
- Imagem: hook de busca web para enriquecimento contextual
"""
import re
import os
import logging
import asyncio
from typing import List, Tuple, Dict, Optional
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from src.core.search.web import fetch_page_text

log = logging.getLogger("seeker.knowledge_vault.extractors")


# ─────────────────────────────────────────────────────────────────────
# IMAGEM / OCR
# ─────────────────────────────────────────────────────────────────────

async def extract_from_images(
    image_bytes_list: List[bytes],
    vlm_client,
    web_searcher=None,
) -> Tuple[str, dict]:
    """
    Extrai texto e contexto visual de imagens via VLM.
    Se web_searcher for fornecido, realiza busca contextual para enriquecimento.

    Returns:
        (ocr_text, {"web_context": str})
    """
    if not image_bytes_list:
        return "", {}

    results = []
    prompt = (
        "Analise esta imagem. Extraia todo texto visível E descreva o contexto visual "
        "(tipo de interface, aplicativo, idioma do conteúdo). "
        "Estruture a saída como:\n"
        "TEXTO EXTRAÍDO:\n[texto aqui]\n\n"
        "CONTEXTO VISUAL:\n[descrição aqui]"
    )

    for i, img_bytes in enumerate(image_bytes_list):
        log.debug(f"[extractors] Processando imagem {i+1}/{len(image_bytes_list)}")
        try:
            result = await vlm_client.analyze_screenshot(img_bytes, prompt=prompt)
            if isinstance(result, dict):
                analysis_text = result.get("analysis") or result.get("text") or str(result)
            else:
                analysis_text = result or ""
            results.append(f"--- IMAGEM {i+1} ---\n{analysis_text}")
        except Exception as e:
            log.error(f"[extractors] Erro ao processar imagem {i}: {e}", exc_info=True)

    ocr_text = "\n\n".join(results)

    # Enriquecimento web opcional
    web_context = ""
    if web_searcher and ocr_text:
        try:
            web_context = await _enrich_with_web(ocr_text, web_searcher)
        except Exception as e:
            log.warning(f"[extractors] Falha no enriquecimento web da imagem: {e}")

    return ocr_text, {"web_context": web_context}


async def _enrich_with_web(text: str, web_searcher) -> str:
    """
    Gera 2 queries a partir do texto extraído e realiza busca web.
    Retorna snippets concatenados como contexto adicional.
    """
    # Extrai as primeiras 300 chars como base para as queries
    snippet = text[:300].strip()
    if not snippet:
        return ""

    # Gera duas queries simples: texto limpo + "o que é" para contexto
    words = re.findall(r'\b[A-Za-zÀ-ú]{4,}\b', snippet)
    key_terms = " ".join(words[:6])
    queries = [key_terms] if key_terms else []

    if not queries:
        return ""

    log.info(f"[extractors] Enriquecimento web: queries = {queries}")
    context_parts = []

    for q in queries[:2]:
        try:
            resp = await web_searcher.search(q, max_results=3)
            for r in resp.results[:3]:
                context_parts.append(f"[{r.title}] {r.snippet}")
        except Exception as e:
            log.warning(f"[extractors] Busca falhou para '{q}': {e}")

    return "\n\n".join(context_parts)


# ─────────────────────────────────────────────────────────────────────
# YOUTUBE
# ─────────────────────────────────────────────────────────────────────

def _get_youtube_id(url: str) -> Optional[str]:
    regex = r"(?:v=|\/|be\/|embed\/)([a-zA-Z0-9_-]{11})"
    match = re.search(regex, url)
    return match.group(1) if match else None


async def extract_from_youtube(url: str) -> Tuple[str, Dict]:
    """
    Extrai transcrição e metadados ricos de um vídeo do YouTube.
    
    Returns:
        (transcript_text, metadata_dict)
        metadata: title, channel, duration, view_count, upload_date, thumbnail, url
    """
    video_id = _get_youtube_id(url)
    if not video_id:
        raise ValueError("URL do YouTube inválida.")

    metadata = {
        "title": "Vídeo do YouTube",
        "channel": "Desconhecido",
        "url": url,
        "duration": None,
        "view_count": None,
        "upload_date": None,
        "thumbnail": None,
    }
    transcript_text = ""

    # 1. Transcrição oficial via API
    try:
        api = YouTubeTranscriptApi()
        data = api.fetch(video_id, languages=["pt", "en"])
        transcript_text = " ".join([entry.text for entry in data])
        log.info(f"[extractors] Transcrição via API obtida ({len(transcript_text)} chars) para {video_id}")
    except Exception as e:
        log.warning(f"[extractors] Falha na API de transcrição: {e}. Tentando yt-dlp fallback...")

    # 2. Metadados ricos via yt-dlp
    try:
        ydl_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }
        loop = asyncio.get_event_loop()

        def _run_ydl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        info = await loop.run_in_executor(None, _run_ydl)

        metadata["title"] = info.get("title", metadata["title"])
        metadata["channel"] = info.get("uploader", info.get("channel", metadata["channel"]))
        metadata["duration"] = info.get("duration")
        metadata["view_count"] = info.get("view_count")
        metadata["upload_date"] = info.get("upload_date")
        metadata["thumbnail"] = info.get("thumbnail")

        log.info(f"[extractors] Metadados YT extraídos: {metadata['title']} | {metadata['channel']}")

        if not transcript_text:
            transcript_text = "[Sem legendas disponíveis para este vídeo]"

    except Exception as e:
        log.error(f"[extractors] Erro ao extrair metadados via yt-dlp: {e}")

    return transcript_text, metadata


# ─────────────────────────────────────────────────────────────────────
# SITE / ARTIGO
# ─────────────────────────────────────────────────────────────────────

async def extract_from_site(url: str) -> Tuple[str, Dict]:
    """
    Extrai conteúdo e metadados de uma URL.
    Limite aumentado para 15K chars.

    Returns:
        (page_text, page_metadata)
        metadata: title, author, description, og_image
    """
    try:
        import httpx
        import html as html_mod

        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": "SeekerBot/2.0 (research agent)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            if "text/html" not in resp.headers.get("content-type", ""):
                return f"[Conteúdo não-HTML: {resp.headers.get('content-type', '')}]", {}

            raw_html = resp.text
            metadata = _extract_page_metadata(raw_html, url)

            # Limpa HTML → texto limpo
            text = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL)
            text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            text = html_mod.unescape(text)

            return text[:15000], metadata

    except Exception as e:
        log.error(f"[extractors] Erro ao extrair site {url}: {e}")
        return f"[Erro ao buscar {url}: {e}]", {}


def _extract_page_metadata(html: str, url: str) -> Dict:
    """Extrai metadados da página via regex (sem dependência de bs4)."""
    meta = {"title": "", "author": "", "description": "", "og_image": ""}

    # Title
    t = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if t:
        meta["title"] = re.sub(r"\s+", " ", t.group(1)).strip()

    # Meta description
    d = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
    if d:
        meta["description"] = d.group(1).strip()

    # OG description fallback
    if not meta["description"]:
        d2 = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
        if d2:
            meta["description"] = d2.group(1).strip()

    # Author
    a = re.search(r'<meta[^>]+name=["\']author["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
    if a:
        meta["author"] = a.group(1).strip()

    # OG Image
    og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
    if og:
        meta["og_image"] = og.group(1).strip()

    return meta


# ─────────────────────────────────────────────────────────────────────
# ÁUDIO
# ─────────────────────────────────────────────────────────────────────

async def extract_from_audio(audio_bytes: bytes) -> str:
    """
    Transcrição de áudio via Groq Whisper com fallback local.
    """
    from src.skills.stt_groq import transcribe_audio_groq
    return await transcribe_audio_groq(audio_bytes)
