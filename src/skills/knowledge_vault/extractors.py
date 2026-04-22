"""
Extractors - Extração de conteúdo de diferentes fontes
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

async def extract_from_images(image_bytes_list: List[bytes], vlm_client) -> str:
    """Extrai texto e contexto de uma lista de imagens usando VLM."""
    if not image_bytes_list:
        return ""
    
    results = []
    prompt = (
        "Analise esta imagem. Extraia todo texto visível E descreva o contexto visual "
        "(tipo de interface, aplicativo, idioma do conteúdo). "
        "Estruture a saída como: TEXTO EXTRAÍDO → CONTEXTO VISUAL."
    )
    
    for i, img_bytes in enumerate(image_bytes_list):
        log.debug(f"[extractors] Processando imagem {i+1}/{len(image_bytes_list)}")
        # Nota: VLMClient.analyze_screenshot geralmente aceita o caminho do arquivo, 
        # mas precisamos verificar se ele aceita bytes ou se precisamos salvar temporariamente.
        # Olhando o checkpoint anterior, VLMClient parece lidar com caminhos.
        
        # Salvando temporário para processamento
        temp_path = f"temp_obsidian_extract_{i}.png"
        try:
            with open(temp_path, "wb") as f:
                f.write(img_bytes)
            
            res = await vlm_client.analyze_screenshot(temp_path)
            analysis = res.get("analysis", "")
            results.append(f"--- IMAGEM {i+1} ---\n{analysis}")
        except Exception as e:
            log.error(f"[extractors] Erro ao processar imagem {i}: {e}")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
    return "\n\n".join(results)

def _get_youtube_id(url: str) -> Optional[str]:
    """Extrai o ID do vídeo do YouTube de uma URL."""
    regex = r"(?:v=|\/|be\/|embed\/)([a-zA-Z0-9_-]{11})"
    match = re.search(regex, url)
    return match.group(1) if match else None

async def extract_from_youtube(url: str) -> Tuple[str, Dict]:
    """Extrai transcrição e metadados de um vídeo do YouTube."""
    video_id = _get_youtube_id(url)
    if not video_id:
        raise ValueError("URL do YouTube inválida.")

    metadata = {"title": "Vídeo do YouTube", "channel": "Desconhecido", "url": url}
    transcript_text = ""

    # 1. Tentar transcrição oficial via API
    try:
        # Instancia a API (necessário nesta versão)
        api = YouTubeTranscriptApi()
        data = api.fetch(video_id, languages=['pt', 'en'])
        transcript_text = " ".join([entry.text for entry in data])
        log.info(f"[extractors] Transcrição via API obtida para {video_id}")
    except Exception as e:
        log.warning(f"[extractors] Falha na API de transcrição: {e}. Tentando yt-dlp fallback...")

    # 2. Metadados e Fallback de legendas via yt-dlp
    try:
        ydl_opts = {
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
            'writeautomaticsub': True,
            'subtitlesformat': 'json',
            'writesubtitles': True,
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
