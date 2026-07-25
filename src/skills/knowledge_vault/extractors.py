"""
Extractors - Extração de conteúdo de diferentes fontes

Imports pesados (yt_dlp, youtube_transcript_api) são lazy — carregados só
quando extract_from_youtube() é efetivamente chamado. Sem isso, falha de
qualquer um derrubaria a importação do módulo e travaria o boot do bot
(incident 2026-05-17 — crash loop yt_dlp ausente na venv).
"""

import os
import re
import json
import time
import math
import asyncio
import subprocess
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Optional

from src.core.search.web import fetch_page_text
from src.core.utils import filter_ytdlp_stderr

log = logging.getLogger("seeker.knowledge_vault.extractors")


GEO_CACHE_FILENAME = "whatsapp_geo_cache.json"
GEO_CACHE_TTL_DAYS = 30
SECONDS_PER_DAY = 86400


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: write to .tmp, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass


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
        with filter_ytdlp_stderr():
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


async def extract_from_zip(zip_bytes: bytes, vlm_client=None) -> str:
    """Extrai conteúdo de arquivos dentro de um ZIP e consolida em texto único."""
    import zipfile
    import io
    
    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except Exception as e:
        raise ValueError(f"Arquivo ZIP inválido ou corrompido: {e}")
        
    results = []
    processed_count = 0
    max_files = 20
    
    for name in z.namelist():
        if name.endswith("/") or "__MACOSX" in name or name.startswith("."):
            continue
        if processed_count >= max_files:
            results.append(f"\n\n[⚠️ ZIP truncado: limite de {max_files} arquivos atingido]")
            break
            
        try:
            info = z.getinfo(name)
            if info.file_size > 10 * 1024 * 1024: # Pula arquivos maiores que 10MB
                continue
                
            content_bytes = z.read(name)
            content_text = ""
            
            if name.lower().endswith((".txt", ".md", ".py", ".js", ".json", ".csv", ".xml", ".yaml", ".yml", ".ini", ".conf")):
                try:
                    content_text = content_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        content_text = content_bytes.decode("latin-1")
                    except Exception:
                        pass
            elif name.lower().endswith(".pdf"):
                try:
                    content_text = await extract_from_pdf(content_bytes, vlm_client)
                except Exception as e:
                    content_text = f"[Falha ao ler PDF {name}: {e}]"
            elif name.lower().endswith((".html", ".htm")):
                try:
                    html_raw = content_bytes.decode("utf-8", errors="ignore")
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html_raw, "html.parser")
                    for s in soup(["script", "style"]):
                        s.decompose()
                    content_text = soup.get_text("\n").strip()
                except Exception:
                    pass
            elif name.lower().endswith(".mht"):
                try:
                    content_text = await extract_from_mht(content_bytes)
                except Exception:
                    pass
            
            if content_text.strip():
                results.append(f"### 📂 Arquivo: {name}\n\n{content_text.strip()}")
                processed_count += 1
        except Exception as e:
            log.warning(f"[extractors] Falha ao processar arquivo {name} do ZIP: {e}")
            
    z.close()
    if not results:
        return "[ZIP não contém nenhum arquivo de texto suportado ou legível]"
        
    return "\n\n---\n\n".join(results)


async def extract_from_mht(mht_bytes: bytes) -> str:
    """Extrai o texto principal de um arquivo MHTML (.mht) convertendo o HTML para markdown limpo."""
    import email
    import re
    from bs4 import BeautifulSoup
    
    try:
        msg = email.message_from_bytes(mht_bytes)
    except Exception as e:
        raise ValueError(f"MHTML inválido: {e}")
        
    html_content = ""
    text_content = ""
    
    for part in msg.walk():
        content_type = part.get_content_type()
        if content_type == "text/html" and not html_content:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            try:
                html_content = payload.decode(charset, errors="ignore")
            except Exception:
                html_content = payload.decode("latin-1", errors="ignore")
        elif content_type == "text/plain" and not text_content:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            try:
                text_content = payload.decode(charset, errors="ignore")
            except Exception:
                text_content = payload.decode("latin-1", errors="ignore")
                
    if html_content:
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            for s in soup(["script", "style", "iframe", "noscript"]):
                s.decompose()
            
            # Conversão básica de tags HTML estruturais para Markdown
            for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
                level = int(h.name[1])
                h.replace_with(f"\n\n{'#' * level} {h.get_text().strip()}\n\n")
            for p in soup.find_all("p"):
                p.replace_with(f"\n\n{p.get_text().strip()}\n\n")
            for br in soup.find_all("br"):
                br.replace_with("\n")
            for a in soup.find_all("a"):
                href = a.get("href")
                text = a.get_text().strip()
                if href and text:
                    a.replace_with(f" [{text}]({href}) ")
                    
            text_body = soup.get_text()
            text_body = re.sub(r"\n\s*\n\s*\n+", "\n\n", text_body)
            return text_body.strip()
        except Exception as e:
            log.warning(f"[extractors] Falha ao converter HTML do MHT: {e}")
            
    if text_content:
        return text_content.strip()
        
    return "[MHT vazio ou sem partes textuais compatíveis]"


# ─────────────────────────────────────────────────────────────────────
# WhatsApp v3.12 Phase 1b — novos extractors (Office, vCard, video, geo)
# ─────────────────────────────────────────────────────────────────────

async def extract_from_docx(docx_bytes: bytes) -> str:
    """Extract text from DOCX. Lazy import python-docx. Returns markdown."""
    if not docx_bytes:
        return "[Documento vazio]"
    if len(docx_bytes) > 50 * 1024 * 1024:
        return "[ERRO: DOCX maior que 50MB]"
    try:
        import docx
        import io
        doc = docx.Document(io.BytesIO(docx_bytes))
        parts = []
        for para in doc.paragraphs:
            if para.text.strip():
                parts.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text for cell in row.cells)
                parts.append(f"| {row_text} |")
        return "\n".join(parts) if parts else "[Sem texto extraível]"
    except Exception as e:
        log.warning(f"[extractors] DOCX falhou: {e}")
        return f"[ERRO DOCX: {e}]"


async def extract_from_xlsx(xlsx_bytes: bytes) -> str:
    """Extract sheets from XLSX. Lazy import openpyxl. Returns CSV-like markdown."""
    if not xlsx_bytes:
        return "[Planilha vazia]"
    if len(xlsx_bytes) > 50 * 1024 * 1024:
        return "[ERRO: XLSX maior que 50MB]"
    try:
        from openpyxl import load_workbook
        import io
        wb = load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
        parts = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            parts.append(f"## Sheet: {sheet_name}")
            for row in ws.iter_rows(values_only=True):
                if any(cell is not None for cell in row):
                    cells = [str(c) if c is not None else "" for c in row]
                    parts.append("| " + " | ".join(cells) + " |")
        wb.close()
        return "\n".join(parts) if len(parts) > 1 else "[Sem dados]"
    except Exception as e:
        log.warning(f"[extractors] XLSX falhou: {e}")
        return f"[ERRO XLSX: {e}]"


async def extract_from_pptx(pptx_bytes: bytes) -> str:
    """Extract slides from PPTX. Lazy import python-pptx. Returns markdown."""
    if not pptx_bytes:
        return "[Apresentação vazia]"
    if len(pptx_bytes) > 50 * 1024 * 1024:
        return "[ERRO: PPTX maior que 50MB]"
    try:
        from pptx import Presentation
        import io
        prs = Presentation(io.BytesIO(pptx_bytes))
        parts = []
        for i, slide in enumerate(prs.slides, 1):
            parts.append(f"## Slide {i}")
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    parts.append(shape.text)
        return "\n".join(parts) if parts else "[Sem texto extraível]"
    except Exception as e:
        log.warning(f"[extractors] PPTX falhou: {e}")
        return f"[ERRO PPTX: {e}]"


async def extract_from_vcard(vcf_bytes: bytes) -> str:
    """Parse vCard 3.0/4.0 bytes. Returns formatted text."""
    if not vcf_bytes:
        return "[vCard vazio]"
    try:
        text = vcf_bytes.decode("utf-8", errors="replace")
        cards = []
        current = {}
        for line in text.splitlines():
            if line.strip() == "BEGIN:VCARD":
                current = {}
            elif line.strip() == "END:VCARD":
                if current:
                    cards.append(current)
            elif ":" in line and not line.startswith("BEGIN") and not line.startswith("END"):
                key, _, value = line.partition(":")
                base_key = key.strip().split(";")[0]
                current[base_key] = value.strip()
        if not cards:
            return "[vCard inválido]"
        out = ["# Contatos extraídos"]
        for c in cards:
            out.append(f"## {c.get('FN', c.get('N', '?'))}")
            for k in ("TEL", "EMAIL", "ORG", "TITLE", "URL", "ADR"):
                if k in c:
                    out.append(f"- **{k}**: {c[k]}")
        return "\n".join(out)
    except Exception as e:
        log.warning(f"[extractors] vCard falhou: {e}")
        return f"[ERRO vCard: {e}]"


async def extract_from_video(video_bytes: bytes, vlm_client=None) -> str:
    """Extract audio track from video and transcribe (Groq Whisper + local fallback).

    NOTE: Keyframe OCR is intentionally NOT implemented in v3.12 — only audio
    transcript. Add keyframe support in v3.13+ if needed.
    """
    if not video_bytes:
        return "[Vídeo vazio]"
    if len(video_bytes) > 50 * 1024 * 1024:
        return "[ERRO: Vídeo maior que 50MB]"
    try:
        import tempfile
        import imageio_ffmpeg

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as v_in:
            v_in.write(video_bytes)
            v_in_path = v_in.name
        audio_path = v_in_path + ".mp3"
        try:
            # Extract audio via thread pool (no event-loop block)
            proc = await asyncio.to_thread(
                subprocess.run,
                [ffmpeg_exe, "-y", "-i", v_in_path, "-vn", "-acodec", "libmp3lame",
                 "-ar", "16000", audio_path],
                capture_output=True, timeout=60,
            )
            transcript = ""
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                try:
                    from src.skills.transcription.stt_groq import transcribe_audio_groq
                    with open(audio_path, "rb") as af:
                        transcript = await transcribe_audio_groq(af.read())
                except Exception as e:
                    log.warning(f"[extractors] transcrição falhou: {e}")
                    transcript = "[Transcrição falhou]"

            # OCR keyframes if VLM available — for now skip with clear log message
            if vlm_client and hasattr(vlm_client, "ocr_fast"):
                log.debug("[extractors] Keyframe OCR ainda não implementado; only audio")

            parts = ["# Transcrição de vídeo"]
            if transcript:
                parts.append(transcript)
            return "\n\n".join(parts) if len(parts) > 1 else "[Sem conteúdo extraível]"
        finally:
            for p in (v_in_path, audio_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass
    except Exception as e:
        log.warning(f"[extractors] Vídeo falhou: {e}")
        return f"[ERRO Vídeo: {e}]"


def reverse_geocode(lat: float, lon: float) -> str:
    """Reverse-geocode via Google Maps API with 30-day file cache."""
    try:
        from pathlib import Path
        cache_path = Path(__file__).resolve().parents[3] / "data" / GEO_CACHE_FILENAME
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        cache: dict = {}
        if cache_path.exists():
            try:
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                cache = {}

        key = f"{round(lat, 4)},{round(lon, 4)}"
        now_ts = time.time()
        if key in cache:
            age_days = (now_ts - cache[key].get("ts", 0)) / SECONDS_PER_DAY
            if age_days < GEO_CACHE_TTL_DAYS:
                return cache[key]["address"]

        api_key = os.getenv("GOOGLE_CLOUD_API_KEY", "")
        if not api_key:
            return f"{lat:.4f}, {lon:.4f}"

        try:
            import httpx
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {"latlng": f"{lat},{lon}", "key": api_key, "language": "pt-BR"}
            with httpx.Client(timeout=5.0) as client:
                r = client.get(url, params=params)
                data = r.json()
            results = data.get("results", [])
            address = results[0].get("formatted_address", key) if results else key
        except Exception as e:
            log.warning(f"[extractors] geocode falhou: {e}")
            return f"{lat:.4f}, {lon:.4f}"

        try:
            cache[key] = {"address": address, "ts": now_ts}
            _atomic_write_json(cache_path, cache)
        except OSError as e:
            log.debug(f"[extractors] cache write ignorado: {e}")

        return address
    except Exception as e:
        log.warning(f"[extractors] reverse_geocode falhou: {e}")
        return f"{lat:.4f}, {lon:.4f}"
