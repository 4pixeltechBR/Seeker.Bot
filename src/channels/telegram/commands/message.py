import logging
import re
import asyncio
import time
import html

from aiogram import Dispatcher, F, Router
from aiogram.types import Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode, ChatAction

from src.core.pipeline import SeekerPipeline
from src.core.router.cognitive_load import CognitiveDepth
from src.channels.telegram.formatter import (
    md_to_telegram_html,
    split_message,
    MAX_MSG_LENGTH,
    format_cost_line,
)
from src.core.reasoning.ooda_loop import (
    OODAIteration,
    ObservationData,
    OrientationModel,
    Decision,
    ActionResult,
    LoopResult,
)

log = logging.getLogger("seeker.telegram.message")


class MessageController:
    """
    Controller for processing all text, photo, and audio messages.
    Follows Clean Architecture by decoupling handlers from the setup logic
    and breaking down the massive _process_and_reply method into focused services.
    """

    def __init__(
        self,
        pipeline: SeekerPipeline,
        vault,
        obsidian_wait_users: set,
        check_obsidian_state,
        transcribe_wait_users: set,
        check_transcribe_state,
    ):
        self.pipeline = pipeline
        self.vault = vault
        self._obsidian_wait_users = obsidian_wait_users
        self._check_obsidian_state = check_obsidian_state
        self._transcribe_wait_users = transcribe_wait_users
        self._check_transcribe_state = check_transcribe_state
        self.router = Router(name="message_router")
        self._register_handlers()

    def _register_handlers(self):
        self.router.message.register(self.handle_vault_photo, F.photo)
        self.router.message.register(self.handle_document, F.document)
        self.router.message.register(self.handle_audio, F.voice | F.audio)
        self.router.message.register(self.handle_text, F.text)

    def setup(self, dp: Dispatcher):
        dp.include_router(self.router)

    # ─── 1. IMAGE HANDLING ────────────────────────────────────────────────────────
    async def handle_vault_photo(self, message: Message, **kwargs):
        """Handler de fotos com debouncer para media groups. Encaminha para o pipeline se nÃ£o tiver /obsidian."""
        (
            kwargs.get("dispatcher", message.bot.dispatcher)
            if hasattr(message.bot, "dispatcher")
            else kwargs.get("dp")
        )
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

    async def _download_file_with_retry(self, bot, file_id: str, max_retries: int = 3) -> bytes:
        import aiohttp
        for attempt in range(1, max_retries + 1):
            try:
                file_info = await bot.get_file(file_id)
                file_obj = await bot.download_file(file_info.file_path)
                return file_obj.read()
            except (aiohttp.ClientError, Exception) as e:
                if attempt == max_retries:
                    log.error(f"Falha definitiva ao baixar arquivo {file_id} após {max_retries} tentativas: {e}")
                    raise e
                log.warning(f"Erro ao baixar arquivo {file_id} (Tentativa {attempt}/{max_retries}). Retentando em {2 ** attempt}s... Erro: {e}")
                await asyncio.sleep(2 ** attempt)


    def _is_obsidian_request(self, caption: str, message: Message) -> bool:
        if "/obsidian" in caption.lower() or "/cofre" in caption.lower():
            return True
        if message.reply_to_message and message.reply_to_message.text:
            if (
                "/obsidian" in message.reply_to_message.text.lower()
                or "/cofre" in message.reply_to_message.text.lower()
            ):
                return True
        return self._check_obsidian_state(message.from_user.id)

    async def _process_media_group(
        self, message: Message, caption: str, is_obsidian: bool, mg_id: str
    ):
        if not hasattr(self, "_vault_debouncer"):
            self._vault_debouncer = {}

        is_first = mg_id not in self._vault_debouncer
        if is_first:
            self._vault_debouncer[mg_id] = []
            asyncio.create_task(
                self._debounce_photo_group(mg_id, message, caption, is_obsidian)
            )

        try:
            photo_bytes = await self._download_file_with_retry(message.bot, message.photo[-1].file_id)
        except Exception as e:
            await message.reply(f"❌ Erro de conexão ao baixar imagem (Timeout/Rede): {e}")
            return

        if mg_id not in self._vault_debouncer:
            self._vault_debouncer[mg_id] = []
            asyncio.create_task(
                self._debounce_photo_group(mg_id, message, caption, is_obsidian)
            )

        self._vault_debouncer[mg_id].append(photo_bytes)

    async def _debounce_photo_group(
        self, mg_id: str, message: Message, caption: str, is_obsidian: bool
    ):
        await asyncio.sleep(1.5)
        photos = self._vault_debouncer.pop(mg_id, [])
        if not photos:
            return

        if is_obsidian:
            status_msg = await message.answer(
                f"⏳ Processando {len(photos)} prints no Obsidian..."
            )
            resp = await self.vault.process_images(
                photos, user_hint=caption.replace("/obsidian", "").replace("/cofre", "")
            )
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

    async def _process_single_photo(
        self, message: Message, caption: str, is_obsidian: bool
    ):
        try:
            photo_bytes = await self._download_file_with_retry(message.bot, message.photo[-1].file_id)
        except Exception as e:
            await message.reply(f"❌ Erro de conexão ao baixar imagem (Timeout/Rede): {e}")
            return

        if is_obsidian:
            status_msg = await message.answer(
                "⏳ Lendo print e salvando no Obsidian..."
            )
            resp = await self.vault.process_images(
                [photo_bytes],
                user_hint=caption.replace("/obsidian", "").replace("/cofre", ""),
            )
            await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
        else:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            try:
                from src.skills.knowledge_vault.extractors import extract_from_images

                raw_text = await extract_from_images(
                    [photo_bytes], self.vault.vlm_client
                )
                user_input = f"{caption}\n\n[Imagem ExtraÃ­da]:\n{raw_text}".strip()
                await self._process_and_reply(message, user_input)
            except Exception as e:
                await message.reply(f"❌ Erro ao analisar imagem: {e}")

    # ─── 1.5. DOCUMENT HANDLING ──────────────────────────────────────────────────────
    async def handle_document(self, message: Message):
        """Handler para documentos (PDF, ZIP, MHT). Encaminha para cofre ou pipeline."""
        if not message.document:
            return

        mime_type = message.document.mime_type or ""
        filename = message.document.file_name or ""
        caption = message.caption or ""
        is_obsidian = self._is_obsidian_request(caption, message)

        is_zip = mime_type in ("application/zip", "application/x-zip-compressed") or filename.lower().endswith(".zip")
        is_mht = mime_type in ("message/rfc822", "application/x-mimearchive", "multipart/related") or filename.lower().endswith(".mht")
        is_pdf = mime_type == "application/pdf" or filename.lower().endswith(".pdf")

        if not (is_pdf or is_zip or is_mht):
            await message.reply(
                f"❌ Tipo de documento não suportado: {mime_type} ({filename})\n"
                f"Por enquanto, apenas PDF, ZIP e MHT são suportados."
            )
            return

        try:
            file_bytes = await self._download_file_with_retry(message.bot, message.document.file_id)
        except Exception as e:
            await message.reply(f"❌ Erro de conexão ao baixar documento: {e}")
            return

        # 1. Fluxo do Obsidian (Cofre)
        if is_obsidian:
            user_hint = caption.replace("/obsidian", "").replace("/cofre", "").strip()
            if is_pdf:
                status_msg = await message.answer("⏳ Lendo PDF e salvando no Obsidian...")
                resp = await self.vault.process_pdf(file_bytes, user_hint=user_hint)
            elif is_zip:
                status_msg = await message.answer("⏳ Lendo ZIP e salvando no Obsidian...")
                resp = await self.vault.process_zip(file_bytes, user_hint=user_hint)
            else: # is_mht
                status_msg = await message.answer("⏳ Lendo MHT e salvando no Obsidian...")
                resp = await self.vault.process_mht(file_bytes, user_hint=user_hint)
            await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
            
        # 2. Fluxo de Chat Normal (Extrai e processa com a inteligência cognitiva)
        else:
            if is_pdf:
                status_msg = await message.answer("⏳ Processando PDF...")
                try:
                    from src.skills.knowledge_vault.extractors import extract_from_pdf
                    raw_text = await extract_from_pdf(file_bytes, self.vault.vlm_client)
                    user_input = f"{caption}\n\n[PDF Extraído]:\n{raw_text}".strip()
                    await status_msg.delete()
                    await self._process_and_reply(message, user_input)
                except Exception as e:
                    await status_msg.edit_text(f"❌ Erro ao processar PDF: {e}")
            elif is_zip:
                status_msg = await message.answer("⏳ Processando ZIP...")
                try:
                    from src.skills.knowledge_vault.extractors import extract_from_zip
                    raw_text = await extract_from_zip(file_bytes, self.vault.vlm_client)
                    user_input = f"{caption}\n\n[ZIP Extraído]:\n{raw_text}".strip()
                    await status_msg.delete()
                    await self._process_and_reply(message, user_input)
                except Exception as e:
                    await status_msg.edit_text(f"❌ Erro ao processar ZIP: {e}")
            else: # is_mht
                status_msg = await message.answer("⏳ Processando MHT...")
                try:
                    from src.skills.knowledge_vault.extractors import extract_from_mht
                    raw_text = await extract_from_mht(file_bytes)
                    user_input = f"{caption}\n\n[MHT Extraído]:\n{raw_text}".strip()
                    await status_msg.delete()
                    await self._process_and_reply(message, user_input)
                except Exception as e:
                    await status_msg.edit_text(f"❌ Erro ao processar MHT: {e}")

    # ─── 2. AUDIO HANDLING ────────────────────────────────────────────────────────
    async def handle_audio(self, message: Message):
        file_id = message.voice.file_id if message.voice else message.audio.file_id
        file_info = await message.bot.get_file(file_id)

        await message.bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)

        try:
            audio_bytes = await self._download_file_with_retry(message.bot, file_id)
        except Exception as e:
            await message.reply(f"❌ Erro de conexão ao baixar áudio (Timeout/Rede): {e}")
            return

        caption = (message.caption or "").lower()
        is_obsidian = "/obsidian" in caption or "/cofre" in caption
        if not is_obsidian:
            is_obsidian = self._check_obsidian_state(message.from_user.id)

        if is_obsidian:
            status_msg = await message.reply(
                "💡 <b>Capturando ideia...</b>", parse_mode=ParseMode.HTML
            )
            resp = await self.vault.process_audio_idea(audio_bytes)
            await status_msg.edit_text(resp, parse_mode=ParseMode.HTML)
            return

        is_pure_transcribe = self._check_transcribe_state(message.from_user.id)

        from src.skills.stt_groq import transcribe_audio_groq

        if is_pure_transcribe:
            status_msg = await message.reply(
                "🎙️ <b>Transcrevendo áudio...</b>", parse_mode=ParseMode.HTML
            )
            text = await transcribe_audio_groq(audio_bytes)
            if not text:
                await status_msg.edit_text(
                    "❌ Falha na transcrição. Verifique a chave da API do Groq."
                )
            else:
                from src.channels.telegram.formatter import split_message

                formatted_text = f"📝 <b>Transcrição concluída:</b>\n\n{text}"
                parts = split_message(formatted_text)
                await status_msg.edit_text(parts[0], parse_mode=ParseMode.HTML)
                for part in parts[1:]:
                    await message.answer(part, parse_mode=ParseMode.HTML)
            return

        user_input = await transcribe_audio_groq(audio_bytes)

        if not user_input:
            await message.reply(
                "❌ Falha ao transcrever o Ã¡udio. (Verifique a GROQ_API_KEY)."
            )
            return

        await message.reply(
            f'🎤 <i>TranscriÃ§Ã£o recebida:</i>\n\n"{user_input}"',
            parse_mode=ParseMode.HTML,
        )
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
            if message.from_user.id in self._transcribe_wait_users:
                self._transcribe_wait_users.discard(message.from_user.id)
                await message.reply("❌ Modo Transcrição cancelado.")
                return

        if user_input.lower() == "/transcrever":
            self._transcribe_wait_users.add(message.from_user.id)
            await message.reply(
                "🎙️ <b>Modo Transcrição Ativado!</b>\n\n"
                "Envie o áudio agora e eu retornarei apenas o texto transcrito via Groq.\n\n"
                "<i>(Para cancelar, envie /cancelar)</i>",
                parse_mode=ParseMode.HTML,
            )
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
                resp = await self.vault.process_url(
                    url, user_hint=user_input.replace(url, "").strip()
                )
                await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                log.error(
                    f"[obsidian] Erro ao processar URL em wait_state: {e}",
                    exc_info=True,
                )
                await status_msg.edit_text(f"❌ Erro ao processar link: {e}")
        else:
            status_msg = await message.answer("📝 Salvando nota no Cofre...")
            try:
                resp = await self.vault.process_text(user_input)
                await status_msg.edit_text(resp, parse_mode=ParseMode.HTML)
            except Exception as e:
                log.error(
                    f"[obsidian] Erro ao salvar texto em wait_state: {e}", exc_info=True
                )
                await status_msg.edit_text(f"❌ Erro ao salvar nota: {e}")

    # ─── 4. CORE PROCESSING PIPELINE ──────────────────────────────────────────────
    async def _process_and_reply(self, message: Message, user_input: str) -> None:
        """Main routing pipeline execution com streaming progressivo de estágios."""
        if await self._handle_bug_wizard(message, user_input):
            return

        if await self._handle_scheduler_wizard(message, user_input):
            return

        if await self._handle_nl_cancel_reminder(message, user_input):
            return

        if await self._handle_instagram_download(message, user_input):
            return

        if await self._handle_nl_reminder(message, user_input):
            return

        user_input = await self._inject_url_context(message, user_input)
        if user_input is None:
            return  # Blocked URL

        user_input = self._handle_god_mode(message, user_input)

        session_id = f"telegram:{message.chat.id}"
        self._record_rl_feedback(message, user_input)

        # Envia mensagem placeholder — será editada progressivamente
        # em vez de abrir nova mensagem no final (AI-style streaming)
        placeholder = await message.answer("⏳ <i>Processando...</i>", parse_mode=ParseMode.HTML)

        afk_protocol = getattr(self.pipeline, "afk_protocol", None)

        # Inicia o pipeline como task em background
        pipeline_task = asyncio.create_task(
            self.pipeline.process(user_input, session_id=session_id, afk_protocol=afk_protocol)
        )

        # Estágios visíveis (rotação enquanto pipeline processa)
        # Cada frame fica visível por ~1.5s (throttle Telegram: max ~1 edit/s)
        _STAGES = [
            "🔍 <i>Analisando pergunta...</i>",
            "📡 <i>Consultando modelos...</i>",
            "🧩 <i>Verificando evidências...</i>",
            "🌐 <i>Pesquisando na web...</i>",
            "⚗️ <i>Sintetizando resposta...</i>",
            "🔬 <i>Revisando qualidade...</i>",
        ]
        _THROTTLE_S = 1.5   # Telegram: ~20 edits/min por chat é seguro
        _EDIT_MAX = 40      # Cap de segurança (60s máximo de espera)

        stage_idx = 0
        edits = 0
        last_text = ""

        try:
            while not pipeline_task.done() and edits < _EDIT_MAX:
                # Espera a task terminar OU o timeout de 1.5s expirar
                await asyncio.wait({pipeline_task}, timeout=_THROTTLE_S)

                if pipeline_task.done():
                    break

                # Rotaciona estágio — permanece no último após percorrer todos
                stage_text = _STAGES[min(stage_idx, len(_STAGES) - 1)]
                stage_idx = min(stage_idx + 1, len(_STAGES) - 1)

                if stage_text != last_text:
                    try:
                        await placeholder.edit_text(stage_text, parse_mode=ParseMode.HTML)
                        last_text = stage_text
                    except Exception:
                        pass  # Edit pode falhar se Telegram throttle — não é crítico
                edits += 1

            # Pipeline terminou — obter resultado
            result = await pipeline_task

        except Exception as e:
            pipeline_task.cancel()
            log.error(f"Erro no pipeline: {e}", exc_info=True)
            try:
                await placeholder.edit_text(f"❌ Erro: {str(e)[:200]}")
            except Exception:
                await message.answer(f"❌ Erro: {str(e)[:200]}")
            return

        self._record_ooda_loop(message, user_input, result)
        self._prepare_next_rl_feedback(message, result)

        # Formata resposta final e edita a mensagem placeholder
        await self._format_and_send_response(message, result, stream_msg=placeholder)


    # ─── 5. ISOLATED SUB-SERVICES ─────────────────────────────────────────────────
    async def _handle_bug_wizard(self, message: Message, user_input: str) -> bool:
        try:
            from src.skills.bug_analyzer import (
                BugAnalyzer,
                BugAnalyzerTelegramInterface,
            )

            bug_analyzer = BugAnalyzer(
                self.pipeline.cascade_adapter, self.pipeline.model_router
            )
            bug_ui = BugAnalyzerTelegramInterface(bug_analyzer)

            if bug_ui.is_in_wizard(message.chat.id):
                session_id = f"telegram:{message.chat.id}"
                user_id = str(message.from_user.id)
                chat_history = self.pipeline.session.get_recent_messages(
                    session_id, user_id, limit=5
                )

                response, is_complete = await bug_ui.process_bug_input(
                    message.chat.id, user_input, chat_history
                )
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
                    success, msg, updated = await wizard.collect_input(
                        message.chat.id, user_input
                    )
                    await message.answer(msg, parse_mode=ParseMode.HTML)

                    if updated and hasattr(updated, "state"):
                        from src.skills.scheduler_conversacional.models import (
                            WizardState,
                        )

                        if updated.state == WizardState.COMPLETED:
                            task = await store.list_tasks(message.chat.id)
                            if task:
                                last_task = task[-1]
                                await message.answer(
                                    f"✅ Tarefa <b>{last_task.title}</b> agendada!\n"
                                    f"PrÃ³xima execuÃ§Ã£o: {last_task.next_run_at.strftime('%d/%m %H:%M')}"
                                    if last_task.next_run_at
                                    else "em breve",
                                    parse_mode=ParseMode.HTML,
                                )
                    return True
        except Exception as e:
            log.debug(f"[wizard] Erro ao verificar wizard: {e}")
        return False

    async def _handle_instagram_download(self, message: Message, user_input: str) -> bool:
        """
        Intercepta URLs do Instagram (posts/reels/tv) e baixa o vídeo, enviando-o de volta.
        Retorna True se tratou.
        """
        import re
        url_match = re.search(r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[a-zA-Z0-9_-]+", user_input)
        if not url_match:
            return False
            
        status_msg = await message.answer("⏳ <b>Baixando vídeo do Instagram...</b>", parse_mode=ParseMode.HTML)
        url = url_match.group(0)
        
        try:
            from src.skills.instascraper.insta_scraper import InstaScraper
            scraper = InstaScraper()
            
            # Executa o download em thread para não travar a event loop
            video_path = await asyncio.to_thread(scraper.download_single_post, url)
            
            if not video_path or not video_path.exists():
                await status_msg.edit_text("❌ Falha ao extrair vídeo do Instagram. Certifique-se de que a conta não é privada ou que os cookies estão atualizados.")
                return True
                
            file_size = video_path.stat().st_size
            if file_size > 45 * 1024 * 1024:
                await status_msg.edit_text("⚠️ O vídeo excede o limite do Telegram (50MB). Enviando como arquivo comprimido...")
                try:
                    from aiogram.types import FSInputFile
                    await message.reply_document(FSInputFile(video_path))
                    await status_msg.delete()
                except Exception:
                    await status_msg.edit_text(f"❌ Vídeo excede limite do Telegram. Salvo localmente em: `{video_path.as_posix()}`")
                return True
                
            from aiogram.types import FSInputFile
            await message.reply_video(FSInputFile(video_path))
            await status_msg.delete()
            return True
            
        except Exception as e:
            log.error(f"[instagram_download] Falha no download do Instagram: {e}", exc_info=True)
            await status_msg.edit_text(f"❌ Erro ao baixar vídeo: {e}")
            return True

    async def _handle_nl_cancel_reminder(self, message: Message, user_input: str) -> bool:
        """
        Intercepta cancelamentos de lembretes em linguagem natural (ex: "cancele o lembrete", "remover lembrete", "cancele os dois lembretes").
        Retorna True se tratou.
        """
        text = user_input.lower().strip()
        
        # Expressões de cancelamento/exclusão
        cancel_triggers = ["cancel", "remover", "apagar", "deletar", "excluir", "limpar"]
        is_cancel = any(t in text for t in cancel_triggers)
        is_reminder = any(r in text for r in ["lembrete", "agenda", "compromisso", "aviso"])
        
        # Padrões específicos como "cancele os dois lembretes" ou "cancele tudo"
        is_cancel_all = "os dois lembretes" in text or "todos os lembretes" in text or "cancele os lembretes" in text or "cancele os dois" in text
        
        if not (is_cancel and (is_reminder or is_cancel_all)):
            return False
            
        try:
            import re
            from src.skills.scheduler_conversacional.store import SchedulerStore
            store = SchedulerStore(self.pipeline.memory._db)
            await store.init()
            
            tasks = await store.list_tasks(message.chat.id)
            # Filtra apenas tarefas ativas e do tipo lembrete (notify_only)
            active_reminders = [t for t in tasks if t.is_enabled and t.notify_only]
            
            if not active_reminders:
                await message.reply("Não encontrei nenhum lembrete ativo agendado para este chat.")
                return True
                
            # Caso 1: Cancelar todos/ambos
            if is_cancel_all:
                removed_titles = []
                for t in active_reminders:
                    await store.delete_task(t.id)
                    removed_titles.append(t.title)
                titles_str = ", ".join([f"<b>{t}</b>" for t in removed_titles])
                await message.reply(f"🗑️ Removi os seguintes lembretes: {titles_str}", parse_mode=ParseMode.HTML)
                return True
                
            # Caso 2: Tentar encontrar por ID (ex: "cancele o lembrete a1b2c3d4")
            # Extrai qualquer palavra alfanumérica de 8 caracteres que possa ser o ID
            words = re.findall(r"\b[a-f0-9]{8}\b", text)
            if words:
                target_id = words[0]
                matched_tasks = [t for t in active_reminders if t.id.startswith(target_id)]
                if matched_tasks:
                    task = matched_tasks[0]
                    await store.delete_task(task.id)
                    await message.reply(f"🗑️ Lembrete <b>{task.title}</b> (ID: <code>{task.id[:8]}</code>) foi removido.", parse_mode=ParseMode.HTML)
                    return True
                    
            # Caso 3: Cancelamento fuzzy por título/assunto (ex: "cancele o lembrete de tomar água")
            # Remove verbos de cancelamento e a palavra lembrete/agenda
            clean_text = text
            for w in cancel_triggers + ["lembrete", "lembretes", "agenda", "de", "o", "a", "os", "as"]:
                clean_text = re.sub(rf"\b{w}\b", "", clean_text)
            clean_text = clean_text.strip()
            
            if clean_text:
                # Procura por correspondência parcial no título ou instrução
                matched_tasks = []
                for t in active_reminders:
                    t_title = t.title.lower()
                    t_body = (t.instruction_text or "").lower()
                    if clean_text in t_title or clean_text in t_body:
                        matched_tasks.append(t)
                
                if matched_tasks:
                    if len(matched_tasks) == 1:
                        task = matched_tasks[0]
                        await store.delete_task(task.id)
                        await message.reply(f"🗑️ Lembrete <b>{task.title}</b> foi removido.", parse_mode=ParseMode.HTML)
                    else:
                        # Ambíguo: exibe lista com IDs para o usuário escolher
                        lines = ["Encontrei mais de um lembrete semelhante. Qual deles você deseja cancelar?"]
                        for t in matched_tasks:
                            lines.append(f"- <code>{t.id[:8]}</code>: {t.title}")
                        lines.append("\nDigite `/remover [ID]` para cancelar.")
                        await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)
                    return True
            
            # Se não resolveu fuzzy nem ID, mas o usuário disse para remover lembrete:
            # Lista os lembretes ativos para ele escolher
            lines = ["Quais destes lembretes você deseja cancelar?"]
            for t in active_reminders:
                lines.append(f"- <code>{t.id[:8]}</code>: {t.title}")
            lines.append("\nDigite `/remover [ID]` para cancelar.")
            await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)
            return True
            
        except Exception as e:
            log.error(f"[nl_cancel_reminder] Falha ao cancelar lembrete: {e}", exc_info=True)
            return False

    async def _handle_nl_reminder(self, message: Message, user_input: str) -> bool:
        """
        Intercepta lembretes em linguagem natural ("me lembre daqui a 5 min ...")
        e cria uma tarefa one-shot (ONCE + notify_only). Retorna True se tratou.

        Só age quando há intenção de lembrete E um horário reconhecível; caso
        contrário devolve False para o fluxo cognitivo normal seguir.
        """
        try:
            from src.skills.scheduler_conversacional.reminder_parser import (
                parse_reminder,
                REMINDER_INTENT,
            )

            if not REMINDER_INTENT.search(user_input):
                return False

            spec = parse_reminder(user_input)
            if spec is None:
                return False

            import uuid
            from datetime import datetime, timezone
            from src.skills.scheduler_conversacional.store import SchedulerStore
            from src.skills.scheduler_conversacional.models import (
                ScheduledTask,
                ScheduleType,
            )

            store = SchedulerStore(self.pipeline.memory._db)
            await store.init()

            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            task = ScheduledTask(
                id=str(uuid.uuid4()),
                title=spec.title,
                schedule_type=ScheduleType.ONCE,
                hour=spec.run_at_local.hour,
                minute=spec.run_at_local.minute,
                notify_only=True,
                instruction_text=spec.body,
                next_run_at=spec.run_at_utc,
                chat_id=message.chat.id,
                created_by=str(message.from_user.id),
            )

            # UNIQUE(chat_id, title): se colidir, torna o título único
            try:
                await store.create_task(task)
            except Exception:
                task.title = f"{spec.title} ({spec.run_at_local:%H:%M})"
                await store.create_task(task)

            # Tempo relativo amigável
            delta = spec.run_at_utc - now_utc
            mins = max(1, int(delta.total_seconds() // 60))
            if mins < 60:
                quando = f"daqui a ~{mins} min"
            elif mins < 1440:
                quando = f"daqui a ~{mins // 60}h{mins % 60:02d}"
            else:
                quando = f"em {spec.run_at_local:%d/%m}"

            await message.answer(
                f"🔔 <b>Lembrete agendado</b>\n\n"
                f"📝 {spec.body}\n"
                f"⏰ {spec.run_at_local:%d/%m %H:%M} ({quando})\n"
                f"🆔 <code>{task.id[:8]}</code>",
                parse_mode=ParseMode.HTML,
            )
            return True
        except Exception as e:
            log.debug(f"[nl_reminder] Falha ao criar lembrete: {e}")
            return False

    def _handle_god_mode(self, message: Message, user_input: str) -> str:
        # Avoid relying on Dispatcher global state; use instance state or pipeline
        if not hasattr(self, "_god_mode_users"):
            self._god_mode_users = set()

        if message.from_user.id in self._god_mode_users:
            user_input = f"god mode â€” {user_input}"
            self._god_mode_users.discard(message.from_user.id)
        return user_input

    async def _inject_url_context(
        self, message: Message, user_input: str
    ) -> str | None:
        url_match = re.search(r"https?://[^\s]+", user_input)
        if not url_match:
            return user_input

        url = url_match.group(0)
        BLOCKED_DOMAINS = (
            "linkedin.com",
            "instagram.com",
            "twitter.com",
            "x.com",
            "facebook.com",
        )

        if any(d in url for d in BLOCKED_DOMAINS):
            await message.reply(
                f"⚠️ <b>Acesso bloqueado</b>\n\n"
                f"O site <code>{url[:60]}...</code> requer autenticaÃ§Ã£o e nÃ£o permite leitura automÃ¡tica.\n\n"
                f"<b>Alternativas:</b>\n"
                f"• Cole o texto do post diretamente aqui\n"
                f"• Use <code>/obsidian {url}</code> para tentar via busca web enriquecida\n"
                f"• Copie os trechos mais importantes e me envie",
                parse_mode=ParseMode.HTML,
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
                orientation=OrientationModel(
                    confidence=0.9, reasoning=result.routing_reason
                ),
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

    async def _format_and_send_response(self, message: Message, result, stream_msg=None):
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

        # Build feedback buttons (Phase 2: RL Integration)
        feedback_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="👎 Ruim", callback_data=f"fb:-1:{result.decision_id}"),
                    InlineKeyboardButton(text="😐 Neutro", callback_data=f"fb:0:{result.decision_id}"),
                    InlineKeyboardButton(text="👍 Bom", callback_data=f"fb:+1:{result.decision_id}"),
                ]
            ]
        )

        if result.image_bytes:
            photo = BufferedInputFile(result.image_bytes, filename="screenshot.png")
            caption = response_text[:1024]
            try:
                await message.answer_photo(
                    photo, caption=caption, parse_mode=ParseMode.HTML,
                    reply_markup=feedback_keyboard
                )
            except Exception:
                await message.answer_photo(photo, caption=html.escape(caption)[:1024])

            if len(response_text) > 1024:
                remaining = response_text[1024:]
                for part in split_message(remaining):
                    await message.answer(part, parse_mode=ParseMode.HTML)
            # Remove placeholder se havia stream_msg
            if stream_msg:
                try:
                    await stream_msg.delete()
                except Exception:
                    pass
            return

        parts = list(split_message(response_text))
        first_sent = False

        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            markup = feedback_keyboard if is_last else None

            # Primeiro chunk: edita o placeholder (streaming effect)
            if not first_sent and stream_msg:
                try:
                    await stream_msg.edit_text(part, parse_mode=ParseMode.HTML, reply_markup=markup)
                    first_sent = True
                    continue
                except Exception as e:
                    log.warning(f"[message] Falha ao editar placeholder (fallback para answer normal): {e}")
                    # Não define first_sent=True nem chama continue, caindo no answer normal abaixo

            # Chunks restantes ou fallback: answer normal
            try:
                await message.answer(part, parse_mode=ParseMode.HTML, reply_markup=markup)
                first_sent = True
            except Exception as e:
                log.error(f"[message] Falha no fallback HTML answer: {e}")
                try:
                    await message.answer(html.escape(part)[:MAX_MSG_LENGTH])
                    first_sent = True
                except Exception as final_err:
                    log.critical(f"[message] Falha critica no envio de mensagem: {final_err}")




# Factory function to preserve bot.py setup flow compatibility
def setup_message_handlers(
    dp: Dispatcher,
    pipeline: SeekerPipeline,
    vault,
    _obsidian_wait_users,
    _check_obsidian_state,
    _transcribe_wait_users,
    _check_transcribe_state,
):
    controller = MessageController(
        pipeline,
        vault,
        _obsidian_wait_users,
        _check_obsidian_state,
        _transcribe_wait_users,
        _check_transcribe_state,
    )
    controller.setup(dp)
    # Inject god_mode_users compatibility
    god_users = dp.get("god_mode_users")
    if god_users is None:
        god_users = set()
        dp["god_mode_users"] = god_users
    controller._god_mode_users = god_users
