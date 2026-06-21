"""
instascraper — Comando Telegram para download de vídeos do Instagram.

Funciona como o SaveAsBot: o usuário digita /instascraper, o bot pede o link,
baixa o vídeo e envia o arquivo diretamente no chat para download.

Suporta Reels, posts (/p/) e vídeos IGTV (/tv/).
"""
import logging
import asyncio
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, FSInputFile
from aiogram.enums import ParseMode

log = logging.getLogger("seeker.telegram.instascraper")

instascraper_router = Router()

# Mapa user_id -> estado de conversa
# {"step": "waiting_url"}
instascraper_states: dict[int, dict] = {}

# Padrões de URL que o Instagram usa para vídeos individuais
INSTAGRAM_VIDEO_PATTERNS = ("/reel/", "/p/", "/tv/", "instagram.com")


def _looks_like_instagram_url(text: str) -> bool:
    """Heurística rápida para validar que o usuário mandou uma URL do Instagram."""
    text = text.strip().lower()
    return "instagram.com" in text and any(p in text for p in ("/reel/", "/p/", "/tv/"))


# ── Comando principal ──────────────────────────────────────────────────────────

@instascraper_router.message(F.text.startswith("/instascraper"))
async def cmd_instascraper(message: Message):
    """
    Entrada do comando. Se o usuário mandou a URL junto (/instascraper <url>),
    dispara o download direto. Se não, pede o link.
    """
    args = message.text.split(maxsplit=1)
    user_id = message.from_user.id

    if len(args) > 1 and _looks_like_instagram_url(args[1]):
        # Modo express: /instascraper https://instagram.com/reel/xxx
        await _handle_download(message, args[1].strip())
    else:
        # Modo interativo: pede o link
        instascraper_states[user_id] = {"step": "waiting_url"}
        await message.answer(
            "📥 <b>InstaScraper</b>\n\n"
            "Manda o link do vídeo do Instagram que você quer baixar.\n\n"
            "<i>Aceito Reels, posts e IGTV — ex:\n"
            "https://www.instagram.com/reel/ABC123/</i>",
            parse_mode=ParseMode.HTML,
        )


# ── Interceptador de resposta (step = waiting_url) ─────────────────────────────

@instascraper_router.message(
    lambda msg: (
        msg.from_user
        and msg.from_user.id in instascraper_states
        and instascraper_states[msg.from_user.id].get("step") == "waiting_url"
    )
)
async def intercept_insta_url(message: Message):
    """Recebe a URL enviada pelo usuário e inicia o download."""
    user_id = message.from_user.id
    url = (message.text or "").strip()

    if not _looks_like_instagram_url(url):
        await message.answer(
            "⚠️ Isso não parece uma URL do Instagram.\n\n"
            "Manda o link completo, ex:\n"
            "<code>https://www.instagram.com/reel/ABC123/</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Limpa o estado antes de processar (evita duplicatas)
    instascraper_states.pop(user_id, None)
    await _handle_download(message, url)


# ── Lógica de download e envio ─────────────────────────────────────────────────

async def _handle_download(message: Message, url: str):
    """
    Baixa o vídeo via InstaScraper.download_single_post e envia pelo Telegram.
    Roda o download em thread separada para não bloquear o event loop.
    """
    status = await message.answer(
        f"⏳ <b>Baixando vídeo...</b>\n"
        f"<code>{url}</code>\n\n"
        "<i>Aguarde, isso pode levar alguns segundos.</i>",
        parse_mode=ParseMode.HTML,
    )

    async def _do_download() -> Path | None:
        from src.skills.instascraper.insta_scraper import InstaScraper
        scraper = InstaScraper()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, scraper.download_single_post, url)

    try:
        video_path: Path | None = await _do_download()
    except Exception as exc:
        log.error(f"[instascraper] Erro no download de {url}: {exc}", exc_info=True)
        await status.edit_text(
            f"❌ <b>Falha ao baixar o vídeo</b>\n\n"
            f"Detalhe: <code>{exc}</code>\n\n"
            "<i>Verifique se o link é válido e se o post não é de conta privada.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    if not video_path or not video_path.exists():
        await status.edit_text(
            "❌ <b>Não foi possível baixar o vídeo.</b>\n\n"
            "Possíveis causas:\n"
            "• Post não é um vídeo (foto ou carrossel sem vídeo)\n"
            "• Conta privada ou post deletado\n"
            "• Sessão do Instagram expirou (cookies desatualizados)",
            parse_mode=ParseMode.HTML,
        )
        return

    # Atualiza status antes de enviar (upload pode demorar)
    await status.edit_text(
        "📤 <b>Vídeo baixado! Enviando para o chat...</b>",
        parse_mode=ParseMode.HTML,
    )

    try:
        file_size_mb = video_path.stat().st_size / (1024 * 1024)
        caption = (
            f"🎬 <b>Vídeo do Instagram</b>\n"
            f"📦 {file_size_mb:.1f} MB\n"
            f"🔗 <a href='{url}'>Link original</a>"
        )

        if file_size_mb <= 50:
            # Até 50 MB → send_video (player nativo no Telegram)
            await message.answer_video(
                FSInputFile(video_path),
                caption=caption,
                parse_mode=ParseMode.HTML,
                supports_streaming=True,
            )
        else:
            # Acima de 50 MB → send_document (evita timeout do Telegram)
            await message.answer_document(
                FSInputFile(video_path),
                caption=caption,
                parse_mode=ParseMode.HTML,
            )

        # Remove status de "enviando"
        await status.delete()

        log.info(f"[instascraper] Vídeo enviado com sucesso: {video_path.name} ({file_size_mb:.1f} MB)")

    except Exception as exc:
        log.error(f"[instascraper] Falha ao enviar vídeo para o Telegram: {exc}", exc_info=True)
        await status.edit_text(
            f"⚠️ <b>Vídeo baixado mas falhou ao enviar</b>\n\n"
            f"O arquivo está salvo localmente em:\n"
            f"<code>{video_path}</code>\n\n"
            f"Erro: <code>{exc}</code>",
            parse_mode=ParseMode.HTML,
        )
    finally:
        # Limpeza: remove o arquivo local após envio bem-sucedido para poupar disco
        try:
            if video_path and video_path.exists():
                video_path.unlink()
                log.debug(f"[instascraper] Arquivo temporário removido: {video_path}")
        except Exception:
            pass  # Não crítico
