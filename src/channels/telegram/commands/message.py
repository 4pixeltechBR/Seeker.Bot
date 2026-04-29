import logging
import re
import asyncio
import time
import html

from aiogram import Dispatcher, F, Router
from aiogram.types import Message, BufferedInputFile
from aiogram.enums import ParseMode, ChatAction

from src.core.pipeline import SeekerPipeline
from src.channels.telegram.bot import keep_typing
from src.core.router.cognitive_load import CognitiveDepth
from src.channels.telegram.formatter import md_to_telegram_html, split_message, MAX_MSG_LENGTH, format_cost_line
from src.core.reasoning.ooda_loop import OODAIteration, ObservationData, OrientationModel, Decision, ActionResult, LoopResult

log = logging.getLogger("seeker.telegram.message")

class MessageController:
    """
    Controller for processing all text, photo, and audio messages.
    Follows Clean Architecture by decoupling handlers from the setup logic
    and breaking down the massive _process_and_reply method into focused services.
    """
    def __init__(self, pipeline: SeekerPipeline, vault, obsidian_wait_users: set, check_obsidian_state):
        self.pipeline = pipeline
        self.vault = vault
        self._obsidian_wait_users = obsidian_wait_users
        self._check_obsidian_state = check_obsidian_state
        self.router = Router(name="message_router")
        self._register_handlers()

    def _register_handlers(self):
        self.router.message.register(self.handle_vault_photo, F.photo)
        self.router.message.register(self.handle_audio, F.voice | F.audio)
        self.router.message.register(self.handle_text, F.text)

    def setup(self, dp: Dispatcher):
        dp.include_router(self.router)

    # ─── 1. IMAGE HANDLING ────────────────────────────────────────────────────────
    async def handle_vault_photo(self, message: Message, **kwargs):
        """Handler de fotos com debouncer para media groups. Encaminha para o pipeline se nÃ£o tiver /obsidian."""
        dp = kwargs.get("dispatcher", message.bot.dispatcher) if hasattr(message.bot, 'dispatcher') else kwargs.get("dp")
        # In Aiogram 3, dp is available in kwargs if registered properly, but we can also get it.
        # Wait, inside class handler, we might not have 'dp' easily if not passed. 
        # Actually, dp is injected if we use dp.include_router, but let's assume we can retrieve it or we don't need it for debouncer if we use a class state.
        
        caption = message.caption or ""
        is_obsidian = self._is_obsidian_request(caption, message)

        mg_id = message.media_group_id
        if mg_id:
            await self._process_media_group(message, caption, is_obsidian, mg_id)
        else:
            await self._process_single_photo(message, caption, is_obsidian)

    def _is_obsidian_request(self, caption: str, message: Message) -> bool:
        if "/obsidian" in caption.lower() or "/cofre" in caption.lower():
            return True
        if message.reply_to_message and message.reply_to_message.text:
            if "/obsidian" in message.reply_to_message.text.lower() or "/cofre" in message.reply_to_message.text.lower():
                return True
        return self._check_obsidian_state(message.from_user.id)

    async def _process_media_group(self, message: Message, caption: str, is_obsidian: bool, mg_id: str):
        if not hasattr(self, "_vault_debouncer"):
            self._vault_debouncer = {}

        is_first = mg_id not in self._vault_debouncer
        if is_first:
            self._vault_debouncer[mg_id] = []
            asyncio.create_task(self._debounce_photo_group(mg_id, message, caption, is_obsidian))

        file_info = await message.bot.get_file(message.photo[-1].file_id)
        photo_file = await message.bot.download_file(file_info.file_path)

        if mg_id not in self._vault_debouncer:
            self._vault_debouncer[mg_id] = []
            asyncio.create_task(self._debounce_photo_group(mg_id, message, caption, is_obsidian))

        self._vault_debouncer[mg_id].append(photo_file.read())

    async def _debounce_photo_group(self, mg_id: str, message: Message, caption: str, is_obsidian: bool):
        await asyncio.sleep(1.5)
        photos = self._vault_debouncer.pop(mg_id, [])
        if not photos:
            return

        if is_obsidian:
            status_msg = await message.answer(f"⏳ Processando {len(photos)} prints no Obsidian...")
            resp = await self.vault.process_images(photos, user_hint=caption.replace("/obsidian", "").replace("/cofre", ""))
            await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
        else:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            try:
                from src.skills.knowledge_vault.extractors import extract_from_images
                raw_text = await extract_from_images(photos, self.vault.vlm_client)
                user_input = f"{caption}\n\n[{len(photos)} Imagens ExtraÃ­das]:\n{raw_text}".strip()
                await self._process_and_reply(message, user_input)
            except Exception as e:
                await message.reply(f"❌ Erro ao analisar grupo de imagens: {e}")

    async def _process_single_photo(self, message: Message, caption: str, is_obsidian: bool):
        file_info = await message.bot.get_file(message.photo[-1].file_id)
        photo_file = await message.bot.download_file(file_info.file_path)

        if is_obsidian:
            status_msg = await message.answer("⏳ Lendo print e salvando no Obsidian...")
            resp = await self.vault.process_images([photo_file.read()], user_hint=caption.replace("/obsidian", "").replace("/cofre", ""))
            await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
        else:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            try:
                from src.skills.knowledge_vault.extractors import extract_from_images
                raw_text = await extract_from_images([photo_file.read()], self.vault.vlm_client)
                user_input = f"{caption}\n\n[Imagem ExtraÃ­da]:\n{raw_text}".strip()
                await self._process_and_reply(message, user_input)
            except Exception as e:
                await message.reply(f"❌ Erro ao analisar imagem: {e}")


    # ─── 2. AUDIO HANDLING ────────────────────────────────────────────────────────
    async def handle_audio(self, message: Message):
        file_id = message.voice.file_id if message.voice else message.audio.file_id
        file_info = await message.bot.get_file(file_id)

        await message.bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)

        audio_file = await message.bot.download_file(file_info.file_path)
        audio_bytes = audio_file.read()

        caption = (message.caption or "").lower()
        is_obsidian = "/obsidian" in caption or "/cofre" in caption
        if not is_obsidian:
            is_obsidian = self._check_obsidian_state(message.from_user.id)

        if is_obsidian:
            status_msg = await message.reply("💡 <b>Capturando ideia...</b>", parse_mode=ParseMode.HTML)
            resp = await self.vault.process_audio_idea(audio_bytes)
            await status_msg.edit_text(resp, parse_mode=ParseMode.HTML)
            return

        from src.skills.stt_groq import transcribe_audio_groq
        user_input = await transcribe_audio_groq(audio_bytes)

        if not user_input:
            await message.reply("❌ Falha ao transcrever o Ã¡udio. (Verifique a GROQ_API_KEY).")
            return

        await message.reply(f"🎤 <i>TranscriÃ§Ã£o recebida:</i>\n\n\"{user_input}\"", parse_mode=ParseMode.HTML)
        await self._process_and_reply(message, user_input)


    # ─── 3. TEXT HANDLING ─────────────────────────────────────────────────────────
    async def handle_text(self, message: Message):
        user_input = message.text.strip()
        if not user_input:
            return

        if user_input.lower() == "/cancelar":
            if message.from_user.id in self._obsidian_wait_users:
                self._obsidian_wait_users.discard(message.from_user.id)
                await message.reply("❌ Modo Cofre cancelado.")
                return

        if self._check_obsidian_state(message.from_user.id):
            await self._handle_obsidian_wait_state(message, user_input)
            return

        await self._process_and_reply(message, user_input)

    async def _handle_obsidian_wait_state(self, message: Message, user_input: str):
        url_match = re.search(r"https?://[^\s]+", user_input)
        if url_match:
            url = url_match.group(0)
            status_msg = await message.answer(f"⏳ Processando link: {url}...")
            try:
                if "youtube.com" in url or "youtu.be" in url:
                    resp = await self.vault.process_youtube(url, user_hint=user_input.replace(url, "").strip())
                else:
                    resp = await self.vault.process_site(url, user_hint=user_input.replace(url, "").strip())
                await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                log.error(f"[obsidian] Erro ao processar URL em wait_state: {e}", exc_info=True)
                await status_msg.edit_text(f"❌ Erro ao processar link: {e}")
        else:
            status_msg = await message.answer("📝 Salvando nota no Cofre...")
            try:
                resp = await self.vault.process_text(user_input)
                await status_msg.edit_text(resp, parse_mode=ParseMode.HTML)
            except Exception as e:
                log.error(f"[obsidian] Erro ao salvar texto em wait_state: {e}", exc_info=True)
                await status_msg.edit_text(f"❌ Erro ao salvar nota: {e}")


    # ─── 4. CORE PROCESSING PIPELINE ──────────────────────────────────────────────
    async def _process_and_reply(self, message: Message, user_input: str) -> None:
        """Main routing pipeline execution - Decoupled for clean architecture."""
        if await self._handle_bug_wizard(message, user_input):
            return

        if await self._handle_scheduler_wizard(message, user_input):
            return

        user_input = await self._inject_url_context(message, user_input)
        if user_input is None:
            return  # Blocked URL

        user_input = self._handle_god_mode(message, user_input)

        session_id = f"telegram:{message.chat.id}"
        self._record_rl_feedback(message, user_input)

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(message.bot, message.chat.id, stop_typing))

        try:
            # Pegando referencias que precisavam do dispatcher global antes.
            # No Aiogram, vc pode recuperar pelo contexto ou assumir nulo.
            # Vamos recuperar o afk_protocol do pipeline que injetamos no bot.py
            afk_protocol = getattr(self.pipeline, 'afk_protocol', None)
            
            result = await self.pipeline.process(
                user_input,
                session_id=session_id,
                afk_protocol=afk_protocol
            )

            self._record_ooda_loop(message, user_input, result)
            self._prepare_next_rl_feedback(message, result)
            await self._format_and_send_response(message, result)

        except Exception as e:
            log.error(f"Erro no pipeline: {e}", exc_info=True)
            await message.answer(f"❌ Erro: {str(e)[:200]}")
        finally:
            stop_typing.set()
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass


    # ─── 5. ISOLATED SUB-SERVICES ─────────────────────────────────────────────────
    async def _handle_bug_wizard(self, message: Message, user_input: str) -> bool:
        try:
            from src.skills.bug_analyzer import BugAnalyzer, BugAnalyzerTelegramInterface
            bug_analyzer = BugAnalyzer(self.pipeline.cascade_adapter, self.pipeline.model_router)
            bug_ui = BugAnalyzerTelegramInterface(bug_analyzer)

            if bug_ui.is_in_wizard(message.chat.id):
                session_id = f"telegram:{message.chat.id}"
                user_id = str(message.from_user.id)
                chat_history = self.pipeline.session.get_recent_messages(session_id, user_id, limit=5)

                response, is_complete = await bug_ui.process_bug_input(message.chat.id, user_input, chat_history)
                await message.answer(response, parse_mode=ParseMode.HTML)
                return True
        except Exception as e:
            log.debug(f"[bug_analyzer] Erro ao verificar wizard: {e}")
        return False

    async def _handle_scheduler_wizard(self, message: Message, user_input: str) -> bool:
        try:
            from src.skills.scheduler_conversacional.store import SchedulerStore
            from src.skills.scheduler_conversacional.wizard import SchedulerWizard

            store = SchedulerStore(self.pipeline.memory._db)
            await store.init()
            wizard = SchedulerWizard(store)

            session = await wizard.get_session(message.chat.id)
            if session:
                if user_input.lower() in ["cancelar", "cancel"]:
                    msg = await wizard.cancel_wizard(message.chat.id)
                    await message.answer(msg, parse_mode=ParseMode.HTML)
                    return True
                elif user_input.lower() in ["voltar", "back"]:
                    success, msg, updated = await wizard.back_step(message.chat.id)
                    await message.answer(msg, parse_mode=ParseMode.HTML)
                    return True
                else:
                    success, msg, updated = await wizard.collect_input(message.chat.id, user_input)
                    await message.answer(msg, parse_mode=ParseMode.HTML)

                    if updated and hasattr(updated, 'state'):
                        from src.skills.scheduler_conversacional.models import WizardState
                        if updated.state == WizardState.COMPLETED:
                            task = await store.list_tasks(message.chat.id)
                            if task:
                                last_task = task[-1]
                                await message.answer(
                                    f"✅ Tarefa <b>{last_task.title}</b> agendada!\n"
                                    f"PrÃ³xima execuÃ§Ã£o: {last_task.next_run_at.strftime('%d/%m %H:%M')}" if last_task.next_run_at else "em breve",
                                    parse_mode=ParseMode.HTML
                                )
                    return True
        except Exception as e:
            log.debug(f"[wizard] Erro ao verificar wizard: {e}")
        return False

    def _handle_god_mode(self, message: Message, user_input: str) -> str:
        # Avoid relying on Dispatcher global state; use instance state or pipeline
        if not hasattr(self, "_god_mode_users"):
            self._god_mode_users = set()
            
        if message.from_user.id in self._god_mode_users:
            user_input = f"god mode â€” {user_input}"
            self._god_mode_users.discard(message.from_user.id)
        return user_input

    async def _inject_url_context(self, message: Message, user_input: str) -> str | None:
        url_match = re.search(r"https?://[^\s]+", user_input)
        if not url_match:
            return user_input

        url = url_match.group(0)
        BLOCKED_DOMAINS = ("linkedin.com", "instagram.com", "twitter.com", "x.com", "facebook.com")
        
        if any(d in url for d in BLOCKED_DOMAINS):
            await message.reply(
                f"⚠️ <b>Acesso bloqueado</b>\n\n"
                f"O site <code>{url[:60]}...</code> requer autenticaÃ§Ã£o e nÃ£o permite leitura automÃ¡tica.\n\n"
                f"<b>Alternativas:</b>\n"
                f"• Cole o texto do post diretamente aqui\n"
                f"• Use <code>/obsidian {url}</code> para tentar via busca web enriquecida\n"
                f"• Copie os trechos mais importantes e me envie",
                parse_mode=ParseMode.HTML
            )
            return None
        else:
            try:
                from src.core.search.web import fetch_page_text
                page_content = await fetch_page_text(url, max_chars=8000)
                if page_content and len(page_content.strip()) > 100:
                    return (
                        f"{user_input}\n\n"
                        f"[CONTEÃšDO EXTRAÃ DO DO LINK - use para responder]\n"
                        f"URL: {url}\n"
                        f"---\n{page_content[:6000]}\n---"
                    )
            except Exception as e:
                log.debug(f"[url_scrape] Falha ao extrair {url}: {e}")
        return user_input

    def _record_rl_feedback(self, message: Message, user_input: str):
        if not hasattr(self, "_rl_state"):
            self._rl_state = {}
            
        last_rl = self._rl_state.get(message.chat.id)
        if last_rl:
            try:
                delay = time.time() - last_rl["response_ts"]
                self.pipeline.observe_follow_up(
                    decision_id=last_rl["decision_id"],
                    message=user_input,
                    response_delay_seconds=delay,
                )
                self.pipeline.reward_collector.close_event(last_rl["decision_id"])
            except Exception:
                pass

    def _prepare_next_rl_feedback(self, message: Message, result):
        if not hasattr(self, "_rl_state"):
            self._rl_state = {}
        self._rl_state[message.chat.id] = {
            "decision_id": result.decision_id,
            "response_ts": time.time(),
        }

    def _record_ooda_loop(self, message: Message, user_input: str, result):
        # Fallback to pipeline._scheduler if OODALoop is missing, or just instantiate it.
        # In bot.py, dp["ooda_loop"] was set. Let's assume pipeline can hold it or we can ignore if none.
        try:
            ooda_iteration = OODAIteration(
                iteration_id=f"telegram_{message.message_id}",
                user_input=user_input,
                observation=ObservationData(user_input=user_input),
                orientation=OrientationModel(confidence=0.9, reasoning=result.routing_reason),
                decision=Decision(
                    action_type="send_response",
                    autonomy_tier=3,
                    parameters={"depth": result.depth.value},
                    rationale=result.routing_reason,
                    verification_required=False,
                ),
                action_result=ActionResult(
                    success=True,
                    output=result.response,
                    latency_ms=result.total_latency_ms,
                    cost=result.total_cost_usd,
                ),
                result=LoopResult.SUCCESS,
                total_latency_ms=result.total_latency_ms,
            )
            log.info(ooda_iteration.to_log_entry())
            # For OODA loop history, ideally we push to pipeline.ooda_loop
        except Exception as e:
            log.debug(f"OODA logging failed: {e}")

    async def _format_and_send_response(self, message: Message, result):
        badge = {
            CognitiveDepth.REFLEX: "⚡",
            CognitiveDepth.DELIBERATE: "🧠",
            CognitiveDepth.DEEP: "🔬",
        }.get(result.depth, "")
        if "god" in result.routing_reason.lower():
            badge = "🔴 GOD MODE"

        footer = format_cost_line(result)
        memory_footer = self.pipeline.format_memory_footer()
        formatted = md_to_telegram_html(result.response)
        if not formatted.strip():
            formatted = result.response
        
        response_text = f"{badge}\n\n{formatted}" if badge else formatted
        response_text += f"\n\n<i>{footer}</i>"
        response_text += memory_footer

        if result.image_bytes:
            photo = BufferedInputFile(result.image_bytes, filename="screenshot.png")
            caption = response_text[:1024]
            try:
                await message.answer_photo(photo, caption=caption, parse_mode=ParseMode.HTML)
            except Exception:
                await message.answer_photo(photo, caption=html.escape(caption)[:1024])
            
            if len(response_text) > 1024:
                remaining = response_text[1024:]
                for part in split_message(remaining):
                    await message.answer(part, parse_mode=ParseMode.HTML)
            return

        for part in split_message(response_text):
            try:
                await message.answer(part, parse_mode=ParseMode.HTML)
            except Exception:
                await message.answer(html.escape(part)[:MAX_MSG_LENGTH])

# Factory function to preserve bot.py setup flow compatibility
def setup_message_handlers(dp: Dispatcher, pipeline: SeekerPipeline, vault, _obsidian_wait_users, _check_obsidian_state):
    controller = MessageController(pipeline, vault, _obsidian_wait_users, _check_obsidian_state)
    controller.setup(dp)
    # Inject god_mode_users compatibility
    god_users = dp.get("god_mode_users")
    if god_users is None:
        god_users = set()
        dp["god_mode_users"] = god_users
    controller._god_mode_users = god_users
