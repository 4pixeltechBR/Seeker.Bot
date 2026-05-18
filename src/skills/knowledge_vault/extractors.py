"""
Extractors - Extração de conteúdo de diferentes fontes

Imports pesados (yt_dlp, youtube_transcript_api) são lazy — carregados só
quando extract_from_youtube() é efetivamente chamado. Sem isso, falha de
qualquer um derrubaria a importação do módulo e travaria o boot do bot
(incident 2026-05-17 — crash loop yt_dlp ausente na venv).
"""

import re
import logging
from typing import List, Tuple, Dict, Optional

from src.core.search.web import fetch_page_text

log = logging.getLogger("seeker.knowledge_vault.extractors")


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
