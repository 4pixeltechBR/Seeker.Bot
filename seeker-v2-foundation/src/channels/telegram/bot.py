"""
Seeker.Bot — Telegram Bot
src/channels/telegram/bot.py

Executar: python -m src
"""

import asyncio
import logging
import os
import html

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties

from config.models import build_default_router, CognitiveRole
from src.core.pipeline import SeekerPipeline
from src.core.router.cognitive_load import CognitiveDepth
from src.channels.telegram.formatter import md_to_telegram_html
from src.providers.base import _rate_limiters, cleanup_client_pool

log = logging.getLogger("seeker.telegram")

MAX_MSG_LENGTH = 4096
TYPING_INTERVAL = 4


def split_message(text: str, max_length: int = MAX_MSG_LENGTH) -> list[str]:
    if len(text) <= max_length:
        return [text]
    parts = []
    remaining = text
    while remaining:
        if len(remaining) <= max_length:
            parts.append(remaining)
            break
        cut = remaining.rfind("\n\n", 0, max_length)
        if cut == -1 or cut < max_length // 2:
            cut = remaining.rfind("\n", 0, max_length)
        if cut == -1 or cut < max_length // 2:
            cut = max_length
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return parts


def format_cost_line(result) -> str:
    parts = []
    if result.total_cost_usd > 0:
        parts.append(f"${result.total_cost_usd:.4f}")
    parts.append(f"{result.total_latency_ms}ms")
    parts.append(f"{result.llm_calls} calls")
    if result.arbitrage and result.arbitrage.has_conflicts:
        parts.append(f"⚠️ {len(result.arbitrage.conflict_zones)} conflitos")
    if result.verdict:
        parts.append(result.verdict.to_footer())
    return " · ".join(parts)


async def keep_typing(bot: Bot, chat_id: int, stop: asyncio.Event):
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=TYPING_INTERVAL)
        except asyncio.TimeoutError:
            continue


def setup_handlers(dp: Dispatcher, pipeline: SeekerPipeline, allowed_users: set[int]):

    @dp.message(F.text == "/start")
    async def cmd_start(message: Message):
        if not _is_allowed(message, allowed_users):
            return
        await message.answer(
            "Seeker.Bot ativo.\n\n"
            "Manda qualquer mensagem — eu decido a profundidade.\n"
            "⚡ reflex · 🧠 deliberate · 🔬 deep\n\n"
            "/god — força análise profunda na próxima\n"
            "/search [query] — busca direta na web\n"
            "/status — providers e memória\n"
            "/memory — o que eu lembro sobre você\n"
            "/rate — uso dos rate limiters\n"
            "/decay — roda confidence decay manualmente"
        )

    @dp.message(F.text.startswith("/search "))
    async def cmd_search(message: Message):
        if not _is_allowed(message, allowed_users):
            return
        query = message.text[8:].strip()
        if not query:
            await message.answer("Uso: /search sua pergunta aqui")
            return

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(
            keep_typing(message.bot, message.chat.id, stop_typing)
        )
        try:
            results = await pipeline.searcher.search(query, max_results=5)
            if not results.results:
                await message.answer(f"Nenhum resultado para: {query}")
                return
            lines = [f"<b>🔍 {html.escape(query)}</b>\n"]
            for r in results.results:
                lines.append(
                    f"<b>{r.position}.</b> <a href=\"{r.url}\">"
                    f"{html.escape(r.title[:60])}</a>\n"
                    f"  <i>{html.escape(r.snippet[:150])}</i>\n"
                )
            lines.append(f"\n<i>via {results.backend}</i>")
            await message.answer("\n".join(lines), parse_mode=ParseMode.HTML,
                                 disable_web_page_preview=True)
        except Exception as e:
            await message.answer(f"❌ Erro: {e}")
        finally:
            stop_typing.set()
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

    @dp.message(F.text == "/status")
    async def cmd_status(message: Message):
        if not _is_allowed(message, allowed_users):
            return
        router = pipeline.model_router
        lines = ["<b>Seeker.Bot — Status</b>\n"]
        for role in CognitiveRole:
            try:
                model = router.get(role)
                lines.append(f"<b>{role.value}</b>: {model.display_name}")
            except ValueError:
                lines.append(f"<b>{role.value}</b>: ⚠️ não configurado")
        lines.append(f"\n<b>Providers na arbitragem:</b>")
        for m in router.get_all_for_arbitrage():
            lines.append(f"  → {m.display_name} ({m.provider})")
        try:
            stats = await pipeline.memory.get_episode_stats()
            facts = await pipeline.memory.get_facts(limit=999)
            lines.append(f"\n<b>Memória:</b>")
            lines.append(f"  {stats['total_episodes']} episódios | {len(facts)} fatos")
            lines.append(f"  Custo acumulado: ${stats['total_cost_usd']:.4f}")
            if stats['avg_latency_ms']:
                lines.append(f"  Latência média: {stats['avg_latency_ms']}ms")
            # Session info
            active = pipeline.session.active_sessions
            if active:
                lines.append(f"  Sessões ativas: {len(active)}")
        except Exception:
            lines.append(f"\n<b>Memória:</b> inicializando...")
        await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

    @dp.message(F.text == "/memory")
    async def cmd_memory(message: Message):
        if not _is_allowed(message, allowed_users):
            return
        try:
            facts = await pipeline.memory.get_facts(min_confidence=0.3, limit=20)
            if not facts:
                await message.answer("Memória vazia — ainda estou aprendendo sobre você.")
                return
            lines = ["<b>🧠 Memória Semântica</b>\n"]
            for f in facts:
                bar = "█" * int(f['confidence'] * 10) + "░" * (10 - int(f['confidence'] * 10))
                lines.append(
                    f"[{bar}] {f['confidence']:.0%} <i>({f['category']})</i>\n"
                    f"  {html.escape(f['fact'][:100])}"
                )
            await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)
        except Exception as e:
            await message.answer(f"❌ Erro: {e}")

    @dp.message(F.text == "/god")
    async def cmd_god(message: Message):
        if not _is_allowed(message, allowed_users):
            return
        await message.answer(
            "🔴 God Mode armado.\n"
            "Próxima mensagem será processada com profundidade máxima."
        )
        dp["god_mode_users"] = dp.get("god_mode_users", set()) | {message.from_user.id}

    @dp.message(F.text == "/rate")
    async def cmd_rate(message: Message):
        if not _is_allowed(message, allowed_users):
            return
        if not _rate_limiters:
            await message.answer("Nenhum rate limiter ativo ainda.")
            return
        lines = ["<b>⏱ Rate Limiters</b>\n"]
        for key, limiter in sorted(_rate_limiters.items()):
            if limiter.rpm <= 0:
                lines.append(f"  <b>{key}</b>: sem limite")
            else:
                used = limiter.current_usage
                total = limiter.rpm
                bar_len = 15
                filled = int((used / total) * bar_len) if total > 0 else 0
                bar = "█" * filled + "░" * (bar_len - filled)
                lines.append(f"  <b>{key.split(':')[0]}</b>")
                lines.append(f"  [{bar}] {used}/{total} RPM")
        await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

    @dp.message(F.text == "/decay")
    async def cmd_decay(message: Message):
        if not _is_allowed(message, allowed_users):
            return
        if not pipeline.decay_engine:
            await message.answer("Decay engine não inicializado.")
            return
        try:
            await message.answer("⏳ Rodando decay...")
            stats = await pipeline.decay_engine.run()
            await message.answer(
                f"<b>Confidence Decay</b>\n\n"
                f"  Fatos avaliados: {stats['total']}\n"
                f"  Decayed: {stats['decayed']}\n"
                f"  Removidos: {stats['removed']}\n"
                f"  Sessões limpas: {stats['sessions_cleaned']}",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            await message.answer(f"❌ Erro: {e}")

    @dp.message(F.text)
    async def handle_message(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        user_input = message.text.strip()
        if not user_input:
            return

        # God mode check
        god_users: set = dp.get("god_mode_users", set())
        if message.from_user.id in god_users:
            user_input = f"god mode — {user_input}"
            god_users.discard(message.from_user.id)
            dp["god_mode_users"] = god_users

        # Session ID baseado no chat (suporta múltiplos chats futuramente)
        session_id = f"telegram:{message.chat.id}"

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(
            keep_typing(message.bot, message.chat.id, stop_typing)
        )

        try:
            result = await pipeline.process(user_input, session_id=session_id)

            badge = {
                CognitiveDepth.REFLEX: "⚡",
                CognitiveDepth.DELIBERATE: "🧠",
                CognitiveDepth.DEEP: "🔬",
            }.get(result.depth, "")
            if "god" in result.routing_reason.lower():
                badge = "🔴 GOD MODE"

            footer = format_cost_line(result)
            formatted = md_to_telegram_html(result.response)
            response_text = f"{badge}\n\n{formatted}" if badge else formatted
            response_text += f"\n\n<i>{footer}</i>"

            for part in split_message(response_text):
                try:
                    await message.answer(part, parse_mode=ParseMode.HTML)
                except Exception:
                    await message.answer(html.escape(part)[:MAX_MSG_LENGTH])

        except Exception as e:
            log.error(f"Erro: {e}", exc_info=True)
            await message.answer(f"❌ Erro: {str(e)[:200]}")
        finally:
            stop_typing.set()
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass


def _is_allowed(message: Message, allowed_users: set[int]) -> bool:
    if not allowed_users:
        return True
    if message.from_user and message.from_user.id in allowed_users:
        return True
    return False


async def main():
    # ── Load .env ─────────────────────────────────────────
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "config", ".env"
    )
    load_dotenv(env_path) if os.path.exists(env_path) else load_dotenv()

    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN não configurado")
        raise SystemExit(1)

    api_keys = {
        "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
        "gemini": os.getenv("GEMINI_API_KEY", ""),
        "groq": os.getenv("GROQ_API_KEY", ""),
        "mistral": os.getenv("MISTRAL_API_KEY", ""),
        "nvidia": os.getenv("NVIDIA_API_KEY", ""),
    }

    allowed_raw = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    allowed_users: set[int] = set()
    if allowed_raw:
        for uid in allowed_raw.split(","):
            uid = uid.strip()
            if uid.isdigit():
                allowed_users.add(int(uid))
        log.info(f"Acesso restrito a: {allowed_users}")
    else:
        log.info("Acesso aberto")

    # ── Init pipeline ─────────────────────────────────────
    pipeline = SeekerPipeline(api_keys)
    await pipeline.init()

    # ── Init bot ──────────────────────────────────────────
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    setup_handlers(dp, pipeline, allowed_users)

    log.info("Seeker.Bot iniciado")
    log.info("  Memória persistente ativa")
    log.info("  Session context ativo")
    log.info("  Embeddings persistidos")
    log.info("  Aguardando mensagens...")

    try:
        await dp.start_polling(bot)
    finally:
        # Cleanup: fecha memória e pool de conexões
        await pipeline.memory.close()
        await cleanup_client_pool()
        log.info("Shutdown completo")


if __name__ == "__main__":
    asyncio.run(main())
