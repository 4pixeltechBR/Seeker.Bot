"""
Extractors - Extração de conteúdo de diferentes fontes

Imports pesados (yt_dlp, youtube_transcript_api) são lazy — carregados só
quando extract_from_youtube() é efetivamente chamado. Sem isso, falha de
qualquer um derrubaria a importação do módulo e travaria o boot do bot
(incident 2026-05-17 — crash loop yt_dlp ausente na venv).
"""

import os
import re
import logging
from typing import List, Tuple, Dict, Optional

from src.core.search.web import fetch_page_text

log = logging.getLogger("seeker.knowledge_vault.extractors")


async def fetch_raw_text(url: str, max_chars: int = 12000) -> str:
    """
    Busca texto bruto de uma URL — diferente de fetch_page_text, NÃO rejeita
    conteúdo não-HTML (READMEs no raw.githubusercontent vêm como text/plain).
    Retorna "" em qualquer falha (degradação graciosa).
    """
    import httpx

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "SeekerBot/1.0 (research agent)"},
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return ""
            return resp.text[:max_chars]
    except Exception as e:
        log.debug(f"[extractors] fetch_raw_text falhou {url}: {e}")
        return ""


async def fetch_github_readme(owner: str, repo: str) -> str:
    """Tenta múltiplos nomes/locais de README via raw.githubusercontent."""
    candidates = [
        "README.md", "readme.md", "Readme.md",
        "README.rst", "README", "docs/README.md",
    ]
    base = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD"
    for name in candidates:
        text = await fetch_raw_text(f"{base}/{name}")
        if text and len(text.strip()) > 30:
            return text
    return ""


async def fetch_github_metadata(owner: str, repo: str) -> Dict:
    """
    Metadados do repo via API pública do GitHub.
    Usa GITHUB_TOKEN do env se presente (eleva o rate limit). Retorna {} em falha.
    """
    import httpx

    headers = {"Accept": "application/vnd.github+json", "User-Agent": "SeekerBot/1.0"}
    token = os.getenv("GITHUB_TOKEN")
    if token and not token.startswith("your_"):
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
            if resp.status_code != 200:
                return {}
            data = resp.json()
            return {
                "description": data.get("description") or "",
                "language": data.get("language") or "",
                "stars": data.get("stargazers_count", 0),
                "topics": data.get("topics", []),
                "homepage": data.get("homepage") or "",
            }
    except Exception as e:
        log.debug(f"[extractors] fetch_github_metadata falhou {owner}/{repo}: {e}")
        return {}


async def extract_from_images(image_bytes_list: List[bytes], vlm_client) -> str:
    """
    Extrai texto e contexto de uma lista de imagens usando VLM.

    Estratégia em 2 estágios (cherry-pick #1 — Florence-2 arm):
      1. ocr_fast() — Florence-2 local (~200ms) para extrair texto bruto.
      2. analyze_screenshot() — VLM Ollama generalista (~1-3s) para
         descrever o CONTEXTO visual (tipo de interface, app, idioma).

    Antes: 1 chamada VLM generalista para texto + contexto (~3s/imagem).
    Agora: 200ms Florence + 1-3s VLM generalista só para contexto. O
           Florence é OPCIONAL e pulado se não estiver disponível (deps
           faltando ou desabilitado via FLORENCE_OCR_ENABLED=false).

    Para prints onde o usuário só quer o texto (sem contexto rico), o caller
    pode chamar vlm_client.ocr_fast() diretamente — bem mais rápido.
    """
    if not image_bytes_list:
        return ""

    context_prompt = (
        "Descreva o CONTEXTO VISUAL desta imagem em 1-2 linhas: "
        "tipo de interface (app, site, terminal), idioma predominante, "
        "e qual a ação/tela mostrada. NÃO transcreva o texto — só o contexto."
    )

    results = []
    for i, img_bytes in enumerate(image_bytes_list):
        log.debug(f"[extractors] Processando imagem {i + 1}/{len(image_bytes_list)}")
        # Florence-2 (ou VLM Ollama fallback) para texto rápido
        try:
            ocr_text = await vlm_client.ocr_fast(img_bytes)
        except Exception as e:
            log.warning(f"[extractors] ocr_fast falhou imagem {i}: {e}")
            ocr_text = ""

        # VLM generalista (Ollama) para contexto — só vale a pena se temos
        # texto OU se a imagem é pequena (UI screenshot, não foto).
        try:
            context = await vlm_client.analyze_screenshot(
                img_bytes, prompt=context_prompt
            )
        except Exception as e:
            log.error(f"[extractors] context VLM falhou imagem {i}: {e}", exc_info=True)
            context = ""

        if not ocr_text and not context:
            continue

        results.append(
            f"--- IMAGEM {i + 1} ---\n"
            f"TEXTO EXTRAÍDO:\n{ocr_text or '(nenhum texto detectado)'}\n\n"
            f"CONTEXTO VISUAL:\n{context or '(sem contexto)'}"
        )

    return "\n\n".join(results)


def _get_youtube_id(url: str) -> Optional[str]:
    """Extrai o ID do vídeo do YouTube de uma URL."""
    regex = r"(?:v=|\/|be\/|embed\/)([a-zA-Z0-9_-]{11})"
    match = re.search(regex, url)
    return match.group(1) if match else None


async def extract_from_youtube(url: str) -> Tuple[str, Dict]:
    """Extrai transcrição e metadados de um vídeo do YouTube.

    Lazy import de yt_dlp / youtube_transcript_api — se as deps faltarem,
    falha aqui com mensagem clara em vez de derrubar o boot do bot.
    """
    try:
        import yt_dlp
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as e:
        log.error(
            f"[extractors] yt_dlp/youtube_transcript_api ausentes: {e}. "
            f"Instale com: pip install yt-dlp youtube-transcript-api"
        )
        raise RuntimeError(
            "Dependências do YouTube não instaladas. Veja log para o pip install."
        ) from e

    video_id = _get_youtube_id(url)
    if not video_id:
        raise ValueError("URL do YouTube inválida.")

    metadata = {"title": "Vídeo do YouTube", "channel": "Desconhecido", "url": url}
    transcript_text = ""

    # 1. Tentar transcrição oficial via API
    try:
        # Instancia a API (necessário nesta versão)
        api = YouTubeTranscriptApi()
        data = api.fetch(video_id, languages=["pt", "en"])
        transcript_text = " ".join([entry.text for entry in data])
        log.info(f"[extractors] Transcrição via API obtida para {video_id}")
    except Exception as e:
        log.warning(
            f"[extractors] Falha na API de transcrição: {e}. Tentando yt-dlp fallback..."
        )

    # 2. Metadados e Fallback de legendas via yt-dlp
    try:
        ydl_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "writeautomaticsub": True,
            "subtitlesformat": "json",
            "writesubtitles": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            metadata["title"] = info.get("title", metadata["title"])
            metadata["channel"] = info.get("uploader", metadata["channel"])
            metadata["duration"] = info.get("duration")

            if not transcript_text:
                # Se não pegamos via API, podemos tentar ler os arquivos de legenda se o yt-dlp baixasse,
                # mas o youtube-transcript-api é mais direto. Se chegamos aqui sem texto,
                # é provável que não existam legendas ativas.
                transcript_text = "[Sem legendas disponíveis para este vídeo]"
    except Exception as e:
        log.error(f"[extractors] Erro ao extrair metadados/fallback: {e}")

    return transcript_text, metadata


async def extract_from_site(url: str) -> str:
    """Extrai conteúdo textual de uma URL genérica."""
    # Reutiliza o fetch_page_text que já limpa scripts/styles
    text = await fetch_page_text(url)
    return text


async def extract_from_audio(audio_bytes: bytes) -> str:
    """Transcrição de áudio via Groq com fallback local (Whisper)."""
    from src.skills.stt_groq import transcribe_audio_groq

    # Nota: O fallback local Whisper Turbo será implementado no stt_local.py
    # e injetado no stt_groq.py conforme o plano.
    return await transcribe_audio_groq(audio_bytes)


async def extract_from_pdf(pdf_bytes: bytes, vlm_client) -> str:
    """
    Extrai texto de PDF. Para páginas escaneadas (pouco texto),
    renderiza como imagem e usa VLM OCR.

    Lazy import de PyMuPDF (fitz) — se faltar, erro claro.
    Limita a ~15 páginas para custo controlado.
    """
    try:
        import fitz
    except ImportError as e:
        log.error(
            f"[extractors] pymupdf ausente: {e}. "
            f"Instale com: pip install pymupdf"
        )
        raise RuntimeError(
            "Dependências do PDF não instaladas. Veja log para o pip install."
        ) from e

    import io

    try:
        pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"PDF inválido: {e}") from e

    results = []
    total_pages = len(pdf)
    MAX_PAGES = 15
    page_limit = min(MAX_PAGES, total_pages)

    for page_num in range(page_limit):
        page = pdf[page_num]
        page_text = page.get_text(sort=True).strip()

        # Se página tem pouco texto (< 100 chars), trata como escaneada
        if len(page_text) < 100 and vlm_client:
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_bytes = pix.tobytes("png")
                ocr_text = await vlm_client.ocr_fast(img_bytes)
                page_text = ocr_text or page_text
            except Exception as e:
                log.debug(f"[extractors] OCR falhou página {page_num + 1}: {e}")

        if page_text:
            results.append(f"--- PÁGINA {page_num + 1} ---\n{page_text}")

    pdf.close()

    if not results:
        return "[PDF vazio ou falha na extração]"

    body = "\n\n".join(results)
    if total_pages > MAX_PAGES:
        body += (
            f"\n\n[⚠️ Documento truncado: {MAX_PAGES} de {total_pages} "
            f"páginas processadas]"
        )
    return body
