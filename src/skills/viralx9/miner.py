"""
viralx9.miner — Núcleo de mineração de concorrentes (sem YouTube Data API).

Para cada canal da seed (config/viralx9_channels.yaml):
  1. Lista uploads recentes via yt-dlp (--flat-playlist).
  2. Busca metadados completos (view_count, upload_date) dos N mais recentes.
  3. mediana_canal = mediana das views (baseline do canal).
  4. Para cada upload "fresco" (<= FRESHNESS_DAYS):
       outlier   = view_count / mediana_canal
       velocity  = view_count / horas_no_ar
     Se outlier >= OUTLIER_THRESHOLD -> candidato.
  5. Traduz/adapta o título para PT-BR via LLM (mantém tema_original + idioma).

Assinatura estável (`mine_nicho`) — a "Fase 2" (thumbnail vision, swipe-file RAG
etc.) troca apenas o miolo do passo 4/5 sem alterar quem chama isto.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import statistics
from typing import Any

from config.models import CognitiveRole
from src.core.utils import parse_llm_json
from src.providers.base import LLMRequest, invoke_with_fallback

log = logging.getLogger("seeker.viralx9.miner")

FRESHNESS_DAYS = 14
OUTLIER_THRESHOLD = 2.0
PLAYLIST_END = 15  # uploads recentes listados por canal
DETAIL_LOOKUP = 10  # quantos desses recebem lookup completo (view_count/data)

# Descrição de cada nicho para o FILTRO DE RELEVÂNCIA. Canais amplos (ex.: um
# canal de ciência/IA) às vezes têm um breakout fora do nosso tema (ex.: tutorial
# de engenharia de LLM). O outlier dispara, mas o assunto não serve — então
# classificamos relevância junto com a tradução (mesma chamada LLM, custo ~zero).
NICHE_TOPICS: dict[str, str] = {
    "microbiologia_ia": (
        "microbiologia e biologia: micro-organismos, vírus, bactérias, fungos, parasitas, "
        "patógenos, doenças, biologia celular/molecular, e o uso de IA na CIÊNCIA, medicina "
        "ou diagnóstico. NÃO é relevante: programação, engenharia de software, frameworks de "
        "ML/LLM (vLLM, PyTorch, etc.), hardware, DevOps ou tutoriais de TI/computação."
    ),
    "forensic_tech": (
        "perícia criminal e true crime: ciência forense, investigação de crimes reais, DNA, "
        "análise de evidências, casos não resolvidos, criminologia, julgamentos."
    ),
    "sitio_404": (
        "deep/dark web, lost media, arquivos e sites deletados ou perdidos, mistérios digitais, "
        "analog horror, criptografia obscura, cantos esquecidos da internet."
    ),
    "crimes_digitais": (
        "crimes e segurança digital para o público geral: golpes online, phishing, ransomware, "
        "fraudes financeiras, vazamento de dados, engenharia social, como se proteger."
    ),
    "rastro_zero": (
        "OSINT, anonimato e privacidade digital, OpSec, rastreamento de pegada digital, "
        "blockchain forense, investigação de identidade online."
    ),
}


def _cookies_path() -> str | None:
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent.parent
    p1 = root / "config" / "cookies.txt"
    if p1.exists():
        return str(p1)
    p2 = root / "docs" / "all_cookies.txt"
    if p2.exists():
        return str(p2)
    return None


def _fetch_channel_uploads(channel_url: str) -> list[dict]:
    """Lista uploads recentes via --flat-playlist (síncrono, roda em thread)."""
    import yt_dlp

    url = channel_url.rstrip("/")
    if not url.endswith("/videos"):
        url = f"{url}/videos"

    ydl_opts = {
        "extract_flat": True,
        "playlistend": PLAYLIST_END,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 8,
        "retries": 0,
    }
    cookies = _cookies_path()
    if cookies:
        ydl_opts["cookiefile"] = cookies

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        log.warning(f"[viralx9] Falha ao listar uploads de {channel_url}: {e}")
        return []

    return [e for e in (info.get("entries") or []) if e]


def _fetch_video_details(video_url: str) -> dict | None:
    """Lookup completo (view_count, upload_date, title) de 1 vídeo (síncrono)."""
    import yt_dlp

    ydl_opts = {
        "quiet": True, 
        "no_warnings": True, 
        "skip_download": True,
        "socket_timeout": 8,
        "retries": 0,
    }
    cookies = _cookies_path()
    if cookies:
        ydl_opts["cookiefile"] = cookies

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(video_url, download=False)
    except Exception as e:
        log.debug(f"[viralx9] Falha ao detalhar {video_url}: {e}")
        return None


def _hours_since(upload_date: str) -> float | None:
    """upload_date no formato yt-dlp: YYYYMMDD."""
    try:
        dt = datetime.datetime.strptime(upload_date, "%Y%m%d")
    except (ValueError, TypeError):
        return None
    delta = datetime.datetime.now() - dt
    return max(delta.total_seconds() / 3600.0, 0.5)


async def _translate_and_classify(title: str, nicho: str, pipeline) -> tuple[str, str, bool, float]:
    """Traduz o título p/ PT-BR E classifica relevância ao nicho numa única chamada.

    Retorna (tema_pt_br, idioma, relevante, custo_usd). Em falha de LLM: mantém o
    título original e considera relevante (não descarta por erro). Se o nicho não
    tiver descrição em NICHE_TOPICS, não filtra (relevante=True).
    """
    topic = NICHE_TOPICS.get(nicho)
    rel_clause = ""
    rel_field = ""
    if topic:
        rel_clause = (
            f'\nEste vídeo veio de um canal do nicho "{nicho}", cujo TEMA é: {topic}\n'
            "Decida se o vídeo é REALMENTE sobre esse tema (true) ou se é off-topic (false)."
        )
        rel_field = ', "relevante": true|false'

    prompt = (
        "Você traduz e adapta títulos de vídeos do YouTube para o público brasileiro"
        + (" e avalia relevância de nicho" if topic else "")
        + ".\n"
        f"Título original: {title!r}\n"
        f"{rel_clause}\n\n"
        "Responda APENAS em JSON: "
        '{"tema": "adaptação curta e natural em PT-BR, mantendo o gancho", '
        '"idioma": "código ISO de 2 letras do idioma original (en, de, ja, ko, zh, es, ...)"'
        + rel_field + "}"
    )
    try:
        resp = await invoke_with_fallback(
            CognitiveRole.FAST,
            LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                system="Você é um tradutor/adaptador de títulos virais e classificador de nicho. Responda apenas JSON.",
                temperature=0.3,
                max_tokens=200,
            ),
            pipeline.model_router,
            pipeline.api_keys,
        )
        cost = getattr(resp, "cost_usd", 0.0) or 0.0
        data = parse_llm_json(resp.text)
        tema = (data.get("tema") or "").strip() or title
        idioma = (data.get("idioma") or "??").strip().lower()
        # Com descrição de nicho: default True se o campo vier ausente (não descarta
        # por omissão). Sem descrição: nunca filtra.
        relevante = bool(data.get("relevante", True)) if topic else True
        return tema, idioma, relevante, cost
    except Exception as e:
        log.warning(f"[viralx9] Falha ao traduzir/classificar '{title}': {e}")
        return title, "??", True, 0.0


async def mine_canal(
    canal: dict, nicho: str, vistos: set[str], pipeline, medians_cache: dict, throttle_context: dict
) -> tuple[list[dict], float]:
    """Mina 1 canal. `canal` = {url, regiao}. Retorna (candidatos, custo_usd)."""
    import time
    cost = 0.0
    url = canal.get("url", "")
    regiao = canal.get("regiao", "us")
    if not url:
        return [], cost

    entries = await asyncio.to_thread(_fetch_channel_uploads, url)
    if not entries:
        return [], cost

    # Filtra apenas vídeos novos (que não estão em vistos) antes de qualquer lookup detalhado
    novos_entries = []
    for e in entries[:DETAIL_LOOKUP]:
        video_id = e.get("id")
        if video_id and video_id not in vistos:
            novos_entries.append(e)

    if not novos_entries:
        # Se todos os vídeos recentes já foram vistos, não faz NENHUM lookup detalhado no YouTube!
        return [], cost

    # Verifica se temos mediana em cache e se está válida (7 dias de TTL)
    cached = medians_cache.get(url)
    fresh_cache_time = 7 * 24 * 3600
    use_cache = cached and (time.time() - cached.get("timestamp", 0) < fresh_cache_time)

    detailed: list[dict] = []
    
    if use_cache:
        # Usa mediana do cache, faz lookup detalhado APENAS para os novos vídeos
        mediana_canal = cached["median"]
        nome_canal = cached.get("nome") or canal.get("nome", "canal")
        
        details = await asyncio.gather(
            *(asyncio.to_thread(_fetch_video_details, e.get("url") or e.get("id", "")) for e in novos_entries)
        )
        detailed = [d for d in details if d]
    else:
        # Sem cache ou expirado: verifica se temos cota disponível no ciclo atual para detalhar e calcular
        if throttle_context.get("uncached_allowed", 0) <= 0:
            log.debug(f"[viralx9] Canal sem cache de mediana pulado neste ciclo para evitar rate limit: {url}")
            return [], cost
            
        # Consome cota de recálculo
        throttle_context["uncached_allowed"] -= 1
        
        # Faz lookup completo de 10 vídeos para recalcular baseline
        to_detail = entries[:DETAIL_LOOKUP]
        details = await asyncio.gather(
            *(asyncio.to_thread(_fetch_video_details, e.get("url") or e.get("id", "")) for e in to_detail)
        )
        
        views: list[int] = []
        all_detailed = []
        for d in details:
            if not d:
                continue
            vc = d.get("view_count")
            if isinstance(vc, int) and vc > 0:
                views.append(vc)
                all_detailed.append(d)

        if len(views) < 3:
            # Amostra insuficiente p/ baseline confiável
            return [], cost

        mediana_canal = statistics.median(views)
        if mediana_canal <= 0:
            return [], cost

        nome_canal = all_detailed[0].get("uploader") or all_detailed[0].get("channel") or canal.get("url", "canal")
        
        # Atualiza o cache
        medians_cache[url] = {
            "median": mediana_canal,
            "nome": nome_canal,
            "timestamp": time.time()
        }
        
        # Filtra os detalhados apenas para os novos entries
        novos_ids = {e.get("id") for e in novos_entries if e.get("id")}
        detailed = [d for d in all_detailed if d.get("id") in novos_ids]

    candidatos: list[dict] = []
    for d in detailed:
        video_id = d.get("id")
        if not video_id or video_id in vistos:
            continue

        hours = _hours_since(d.get("upload_date"))
        if hours is None or hours / 24.0 > FRESHNESS_DAYS:
            continue  # fora da janela de frescor

        view_count = d.get("view_count", 0)
        outlier = view_count / mediana_canal
        if outlier < OUTLIER_THRESHOLD:
            continue

        velocity = view_count / hours
        title = d.get("title") or "(sem título)"

        tema_pt, idioma, relevante, t_cost = await _translate_and_classify(title, nicho, pipeline)
        cost += t_cost
        if not relevante:
            # Off-topic p/ o nicho (canal amplo que postou fora do tema). Marca como
            # visto p/ não re-gastar LLM nas próximas rodadas e segue.
            vistos.add(video_id)
            log.info(f"[viralx9] Off-topic descartado ({nicho}): {title!r}")
            continue

        regiao_emoji = {"us": "🇺🇸", "eu": "🇪🇺", "asia": "🌏"}.get(regiao, "🌐")
        dias_no_ar = max(round(hours / 24.0), 0)
        justificativa = (
            f"{regiao_emoji} {regiao.upper()} · 🔥 {outlier:.1f}x a mediana de @{nome_canal} · "
            f"{velocity:,.0f} views/h · {dias_no_ar}d no ar"
        )

        candidatos.append(
            {
                "tema": tema_pt,
                "tema_original": title,
                "idioma_original": idioma,
                "nicho": nicho,
                "justificativa": justificativa,
                "video_id": video_id,
                "video_url": d.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
                "canal": nome_canal,
                "canal_url": canal.get("url", ""),
                "regiao": regiao,
                "outlier": round(outlier, 2),
                "velocity": round(velocity, 1),
            }
        )

    return candidatos, cost


async def mine_nicho(
    nicho: str, canais: list[dict], vistos: set[str], pipeline, medians_cache: dict, throttle_context: dict
) -> tuple[list[dict], float]:
    """Mina todos os canais (seed) de um nicho. Retorna (candidatos, custo_usd).
    Sequencial p/ não saturar yt-dlp/IP."""
    candidatos: list[dict] = []
    cost = 0.0
    for canal in canais:
        try:
            found, c_cost = await mine_canal(canal, nicho, vistos, pipeline, medians_cache, throttle_context)
            candidatos.extend(found)
            cost += c_cost
        except Exception as e:
            log.error(f"[viralx9] Erro minerando canal {canal} ({nicho}): {e}")
    return candidatos, cost


