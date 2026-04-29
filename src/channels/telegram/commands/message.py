import logging
import re
import asyncio
from aiogram import Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ParseMode, ChatAction
from src.core.pipeline import SeekerPipeline
from src.skills.knowledge_vault import extract_from_audio

log = logging.getLogger("seeker.telegram.message")

def setup_message_handlers(dp: Dispatcher, pipeline: SeekerPipeline, vault, _obsidian_wait_users, _check_obsidian_state, _process_and_reply):
    @dp.message(F.photo)
    async def handle_vault_photo(message: Message):
        """Handler de fotos com debouncer para media groups. Encaminha para o pipeline se nÃ£o tiver /obsidian."""
            
        caption = message.caption or ""
        # Verifica se Ã© para o obsidian direto via legenda, reply ou state
        is_obsidian = "/obsidian" in caption.lower() or "/cofre" in caption.lower()
        if not is_obsidian and message.reply_to_message:
            is_obsidian = message.reply_to_message.text and ("/obsidian" in message.reply_to_message.text.lower() or "/cofre" in message.reply_to_message.text.lower())
        
        if not is_obsidian:
            is_obsidian = _check_obsidian_state(message.from_user.id)
            
        # LÃ³gica de Debouncer para Media Groups
        mg_id = message.media_group_id
        if mg_id:
            if "vault_debouncer" not in dp:
                dp["vault_debouncer"] = {}
                
            is_first = mg_id not in dp["vault_debouncer"]
            if is_first:
                dp["vault_debouncer"][mg_id] = []
                asyncio.create_task(process_photo_group(mg_id, message, caption, is_obsidian))
            
            # Adiciona a foto ao grupo
            file_info = await message.bot.get_file(message.photo[-1].file_id)
            photo_file = await message.bot.download_file(file_info.file_path)
            
            # Se a chave sumiu (download lento), recria
            if mg_id not in dp["vault_debouncer"]:
                dp["vault_debouncer"][mg_id] = []
                asyncio.create_task(process_photo_group(mg_id, message, caption, is_obsidian))
                
            dp["vault_debouncer"][mg_id].append(photo_file.read())
        else:
            # Foto Ãºnica
            file_info = await message.bot.get_file(message.photo[-1].file_id)
            photo_file = await message.bot.download_file(file_info.file_path)
            
            if is_obsidian:
                status_msg = await message.answer("â³ Lendo print e salvando no Obsidian...")
                resp = await vault.process_images([photo_file.read()], user_hint=caption.replace("/obsidian", "").replace("/cofre", ""))
                await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
            else:
                await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
                try:
                    from src.skills.knowledge_vault.extractors import extract_from_images
                    raw_text = await extract_from_images([photo_file.read()], vault.vlm_client)
                    user_input = f"{caption}\n\n[Imagem ExtraÃ­da]:\n{raw_text}".strip()
                    await _process_and_reply(message, user_input, pipeline, dp)
                except Exception as e:
                    await message.reply(f"âŒ Erro ao analisar imagem: {e}")

    async def process_photo_group(mg_id: str, message: Message, caption: str, is_obsidian: bool):
        """Aguarde 1.5s para agrupar todas as fotos do media group"""
        await asyncio.sleep(1.5)
        photos = dp["vault_debouncer"].pop(mg_id, [])
        if not photos:
            return
            
        if is_obsidian:
            status_msg = await message.answer(f"â³ Processando {len(photos)} prints no Obsidian...")
            resp = await vault.process_images(photos, user_hint=caption.replace("/obsidian", "").replace("/cofre", ""))
            await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
        else:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            try:
                from src.skills.knowledge_vault.extractors import extract_from_images
                raw_text = await extract_from_images(photos, vault.vlm_client)
                user_input = f"{caption}\n\n[{len(photos)} Imagens ExtraÃ­das]:\n{raw_text}".strip()
                await _process_and_reply(message, user_input, pipeline, dp)
            except Exception as e:
                await message.reply(f"âŒ Erro ao analisar grupo de imagens: {e}")

    @dp.message(F.voice | F.audio)
    async def handle_audio(message: Message):

        file_id = message.voice.file_id if message.voice else message.audio.file_id
        file_info = await message.bot.get_file(file_id)

        await message.bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)

        # Download
        audio_file = await message.bot.download_file(file_info.file_path)
        audio_bytes = audio_file.read()

        caption = (message.caption or "").lower()
        is_obsidian = "/obsidian" in caption or "/cofre" in caption
        
        if not is_obsidian:
            is_obsidian = _check_obsidian_state(message.from_user.id)

        if is_obsidian:
            # Ãudio com /obsidian â†’ SEMPRE IDEIA VICTOR (sem transcriÃ§Ã£o prÃ©via necessÃ¡ria)
            status_msg = await message.reply("ðŸ’¡ <b>Capturando ideia...</b>", parse_mode=ParseMode.HTML)
            resp = await vault.process_audio_idea(audio_bytes)
            await status_msg.edit_text(resp, parse_mode=ParseMode.HTML)
            return

        # Sem /obsidian â†’ transcreve e processa no pipeline conversacional normalmente
        from src.skills.stt_groq import transcribe_audio_groq
        user_input = await transcribe_audio_groq(audio_bytes)

        if not user_input:
            await message.reply("âŒ Falha ao transcrever o Ã¡udio. (Verifique a GROQ_API_KEY).")
            return

        await message.reply(f"ðŸŽ¤ <i>TranscriÃ§Ã£o recebida:</i>\n\n\"{user_input}\"", parse_mode=ParseMode.HTML)
        await _process_and_reply(message, user_input, pipeline, dp)

    @dp.message(F.text)
    async def handle_message(message: Message):

        user_input = message.text.strip()
        if not user_input:
            return

        if user_input.lower() == "/cancelar":
            if message.from_user.id in _obsidian_wait_users:
                _obsidian_wait_users.discard(message.from_user.id)
                await message.reply("âŒ Modo Cofre cancelado.")
                return

        # Intercepta se estiver no estado do obsidian
        if _check_obsidian_state(message.from_user.id):
            url_match = re.search(r"https?://[^\s]+", user_input)
            if url_match:
                url = url_match.group(0)
                status_msg = await message.answer(f"â³ Processando link: {url}...")
                try:
                    if "youtube.com" in url or "youtu.be" in url:
                        resp = await vault.process_youtube(url, user_hint=user_input.replace(url, "").strip())
                    else:
                        resp = await vault.process_site(url, user_hint=user_input.replace(url, "").strip())
                    await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    log.error(f"[obsidian] Erro ao processar URL em wait_state: {e}", exc_info=True)
                    await status_msg.edit_text(f"âŒ Erro ao processar link: {e}")
            else:
                status_msg = await message.answer("ðŸ“ Salvando nota no Cofre...")
                try:
                    resp = await vault.process_text(user_input)
                    await status_msg.edit_text(resp, parse_mode=ParseMode.HTML)
                except Exception as e:
                    log.error(f"[obsidian] Erro ao salvar texto em wait_state: {e}", exc_info=True)
                    await status_msg.edit_text(f"âŒ Erro ao salvar nota: {e}")
            return

        await _process_and_reply(message, user_input, pipeline, dp)

    async def _process_and_reply(message: Message, user_input: str, pipeline: SeekerPipeline, dp: Dispatcher) -> None:

        # Check for active bug analyzer wizard
        try:
            from src.skills.bug_analyzer import BugAnalyzer, BugAnalyzerTelegramInterface

            bug_analyzer = BugAnalyzer(pipeline.cascade_adapter, pipeline.model_router)
            bug_ui = BugAnalyzerTelegramInterface(bug_analyzer)

            if bug_ui.is_in_wizard(message.chat.id):
                # Bug wizard ativo â€” processar input no wizard
                # Get real chat history from SessionManager
                session_id = f"telegram:{message.chat.id}"
                user_id = str(message.from_user.id)
                chat_history = pipeline.session.get_recent_messages(session_id, user_id, limit=5)

                response, is_complete = await bug_ui.process_bug_input(
                    message.chat.id,
                    user_input,
                    chat_history
                )
                await message.answer(response, parse_mode=ParseMode.HTML)
                return
        except Exception as e:
            log.debug(f"[bug_analyzer] Erro ao verificar wizard: {e}")

        # Check for active scheduler wizard
        try:
            from src.skills.scheduler_conversacional.store import SchedulerStore
            from src.skills.scheduler_conversacional.wizard import SchedulerWizard

            store = SchedulerStore(pipeline.memory._db)
            await store.init()
            wizard = SchedulerWizard(store)

            session = await wizard.get_session(message.chat.id)
            if session:
                # Wizard ativo â€” processar input no wizard
                user_id = str(message.from_user.id)

                # Handle special commands in wizard
                if user_input.lower() in ["cancelar", "cancel"]:
                    msg = await wizard.cancel_wizard(message.chat.id)
                    await message.answer(msg, parse_mode=ParseMode.HTML)
                    return
                elif user_input.lower() in ["voltar", "back"]:
                    success, msg, updated = await wizard.back_step(message.chat.id)
                    await message.answer(msg, parse_mode=ParseMode.HTML)
                    return
                else:
                    # Normal wizard input
                    success, msg, updated = await wizard.collect_input(message.chat.id, user_input)
                    await message.answer(msg, parse_mode=ParseMode.HTML)

                    # Se wizard completou, notificar
                    if updated and hasattr(updated, 'state'):
                        from src.skills.scheduler_conversacional.models import WizardState
                        if updated.state == WizardState.COMPLETED:
                            task = await store.list_tasks(message.chat.id)
                            if task:
                                last_task = task[-1]
                                await message.answer(
                                    f"âœ… Tarefa <b>{last_task.title}</b> agendada!\n"
                                    f"PrÃ³xima execuÃ§Ã£o: {last_task.next_run_at.strftime('%d/%m %H:%M')}" if last_task.next_run_at else "em breve",
                                    parse_mode=ParseMode.HTML
                                )
                    return
        except Exception as e:
            log.debug(f"[wizard] Erro ao verificar wizard: {e}")
            # Continua com processamento normal

        # God mode check
        god_users: set = dp.get("god_mode_users", set())
        if message.from_user.id in god_users:
            user_input = f"god mode â€” {user_input}"
            god_users.discard(message.from_user.id)
            dp["god_mode_users"] = god_users

        # Session ID baseado no chat (suporta mÃºltiplos chats futuramente)
        session_id = f"telegram:{message.chat.id}"

        # â”€â”€ RL: envia feedback da resposta anterior ao Reward Collector â”€â”€
        # A mensagem atual DO Victor Ã© o sinal comportamental da resposta anterior.
        # Delay entre resposta do bot e nova mensagem do Victor indica engajamento.
        _rl_key = f"rl_last_{message.chat.id}"
        _last_rl = dp.get(_rl_key)
        if _last_rl:
            try:
                _delay = time.time() - _last_rl["response_ts"]
                pipeline.observe_follow_up(
                    decision_id=_last_rl["decision_id"],
                    message=user_input,
                    response_delay_seconds=_delay,
                )
                # Fecha o evento apÃ³s receber o feedback
                pipeline.reward_collector.close_event(_last_rl["decision_id"])
            except Exception:
                pass  # RL nunca deve quebrar o fluxo principal

        # OODA Loop for structured decision-making
        ooda_loop = dp.get("ooda_loop")

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(
            keep_typing(message.bot, message.chat.id, stop_typing)
        )

        # â”€â”€ InjeÃ§Ã£o de contexto de URL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Se a mensagem contÃ©m um link, tenta scrape para injetar o conteÃºdo no
        # contexto do LLM. Evita resposta vazia quando o usuÃ¡rio pede anÃ¡lise de URL.
        _url_match = re.search(r"https?://[^\s]+", user_input)
        if _url_match:
            _url = _url_match.group(0)
            _BLOCKED_DOMAINS = ("linkedin.com", "instagram.com", "twitter.com", "x.com", "facebook.com")
            if any(d in _url for d in _BLOCKED_DOMAINS):
                # Sites auth-gated: nÃ£o scrapeÃ¡veis. Informa ao usuÃ¡rio claramente.
                stop_typing.set()
                await typing_task
                await message.reply(
                    f"âš ï¸ <b>Acesso bloqueado</b>\n\n"
                    f"O site <code>{_url[:60]}...</code> requer autenticaÃ§Ã£o e nÃ£o permite leitura automÃ¡tica.\n\n"
                    f"<b>Alternativas:</b>\n"
                    f"â€¢ Cole o texto do post diretamente aqui\n"
                    f"â€¢ Use <code>/obsidian {_url}</code> para tentar via busca web enriquecida\n"
                    f"â€¢ Copie os trechos mais importantes e me envie",
                    parse_mode=ParseMode.HTML
                )
                return
            else:
                # Outros sites: tenta scrape e injeta no contexto
                try:
                    from src.core.search.web import fetch_page_text
                    _page_content = await fetch_page_text(_url, max_chars=8000)
                    if _page_content and len(_page_content.strip()) > 100:
                        user_input = (
                            f"{user_input}\n\n"
                            f"[CONTEÃšDO EXTRAÃDO DO LINK - use para responder]\n"
                            f"URL: {_url}\n"
                            f"---\n{_page_content[:6000]}\n---"
                        )
                except Exception as _url_e:
                    log.debug(f"[url_scrape] Falha ao extrair {_url}: {_url_e}")
        # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

        try:
            result = await pipeline.process(
                user_input,
                session_id=session_id,
                afk_protocol=dp.get("afk_protocol")
            )

            # OODA Loop logging: Record the decision cycle
            if ooda_loop:
                # Simulate OODA cycle with pipeline result as success marker
                import time
                from src.core.reasoning.ooda_loop import ObservationData, OrientationModel, Decision, ActionResult, LoopResult

                ooda_iteration = OODAIteration(
                    iteration_id=f"telegram_{message.message_id}",
                    user_input=user_input,
                    observation=ObservationData(user_input=user_input),
                    orientation=OrientationModel(
                        confidence=0.9,
                        reasoning=result.routing_reason,
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
                ooda_loop.history.append(ooda_iteration)

            badge = {
                CognitiveDepth.REFLEX: "âš¡",
                CognitiveDepth.DELIBERATE: "ðŸ§ ",
                CognitiveDepth.DEEP: "ðŸ”¬",
            }.get(result.depth, "")
            if "god" in result.routing_reason.lower():
                badge = "ðŸ”´ GOD MODE"

            footer = format_cost_line(result)
            memory_footer = pipeline.format_memory_footer()
            formatted = md_to_telegram_html(result.response)
            if not formatted.strip():
                formatted = result.response
            response_text = f"{badge}\n\n{formatted}" if badge else formatted
            response_text += f"\n\n<i>{footer}</i>"
            response_text += memory_footer

            if result.image_bytes:
                from aiogram.types import BufferedInputFile
                photo = BufferedInputFile(result.image_bytes, filename="screenshot.png")
                # Telegram caption has a limit of 1024 characters
                caption = response_text[:1024]
                try:
                    await message.answer_photo(photo, caption=caption, parse_mode=ParseMode.HTML)
                except Exception:
                    await message.answer_photo(photo, caption=html.escape(caption)[:1024])
                
                # Envia o restante se o texto for muito longo para o caption
                if len(response_text) > 1024:
                    remaining = response_text[1024:]
                    for part in split_message(remaining):
                        await message.answer(part, parse_mode=ParseMode.HTML)
                return
            
            # â”€â”€ Obsidian Confirmation Button (removido do fluxo automÃ¡tico) â”€â”€
            # O botÃ£o foi desativado para nÃ£o aparecer em toda conversa.
            # Use /obsidian explicitamente para salvar no Cofre.
            kb = None

            for part in split_message(response_text):
                    try:
                        # Se for a Ãºltima parte e tiver teclado, envia junto
                        is_last = part == split_message(response_text)[-1]
                        await message.answer(part, parse_mode=ParseMode.HTML, reply_markup=kb if (is_last and kb) else None)
                    except Exception:
                        await message.answer(html.escape(part)[:MAX_MSG_LENGTH])

            # â”€â”€ RL: guarda decision_id para o prÃ³ximo feedback â”€â”€â”€â”€â”€â”€â”€â”€
            dp[f"rl_last_{message.chat.id}"] = {
                "decision_id": result.decision_id,
                "response_ts": time.time(),
            }

        except Exception as e:
            log.error(f"Erro: {e}", exc_info=True)
            await message.answer(f"âŒ Erro: {str(e)[:200]}")
        finally:
            stop_typing.set()
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass


    if not allowed_users:
        return True
    if message.from_user and message.from_user.id in allowed_users:
        return True
    return False


    if not allowed_users:
        return True
    if query.from_user and query.from_user.id in allowed_users:
        return True
    return False


async def main():
    # â”€â”€ Load .env â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "config", ".env"
    )
    load_dotenv(env_path) if os.path.exists(env_path) else load_dotenv()

    log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO"))
    log_fmt = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Console handler (mantÃ©m comportamento original)
    logging.basicConfig(level=log_level, format=log_fmt._fmt, datefmt=log_fmt.datefmt)

    # File handler â€” persistÃªncia para o self_improvement_loop
    from logging.handlers import RotatingFileHandler
    _log_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "logs",
    )
    os.makedirs(_log_dir, exist_ok=True)
    _file_handler = RotatingFileHandler(
        os.path.join(_log_dir, "seeker.log"),
        maxBytes=5 * 1024 * 1024,    # 5 MB por arquivo
        backupCount=3,                # mantÃ©m seeker.log.1, .2, .3
        encoding="utf-8",
    )
    _file_handler.setLevel(log_level)
    _file_handler.setFormatter(log_fmt)
    logging.getLogger().addHandler(_file_handler)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN nÃ£o configurado", exc_info=True)
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

    # â”€â”€ Init pipeline â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    pipeline = SeekerPipeline(api_keys)
    await pipeline.init()

    # â”€â”€ Reset heartbeat file (watchdog init) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Limpar arquivo de heartbeat antigo para evitar que watchdog
    # mate o bot logo apÃ³s iniciar pensando que estÃ¡ travado
    try:
        hb_path = "logs/bot_heartbeat.txt"
        if os.path.exists(hb_path):
            os.remove(hb_path)
        log.debug("[startup] Heartbeat file limpo para novo ciclo")
    except Exception as e:
        log.warning(f"[startup] Erro ao limpar heartbeat: {e}")

    # â”€â”€ Init API Cascade Health Checks (Sprint 7.1) â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        await pipeline.cascade_adapter.start_health_checks(interval_seconds=30)
        log.info("  API Cascade health checks iniciados (interval=30s)")
    except Exception as e:
        log.warning(f"Erro ao iniciar health checks: {e}")

    # â”€â”€ Init bot â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # â”€â”€ Init OODA Loop (for structured decision-making + auditability) â”€â”€
    dp["ooda_loop"] = OODALoop()

    try:
        await setup_commands(bot)
    except Exception as e:
        log.warning(f"setup_commands falhou (nÃ£o crÃ­tico): {e}")

    setup_handlers(dp, pipeline, allowed_users)

    # â”€â”€ Init Autonomous Skills (Goal Engine) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    
    # â”€â”€ Email (opcional â€” falha nÃ£o impede boot) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    email_client = None
    email_recipients = []
    try:
        email_client = EmailClient.from_env()
        raw = os.getenv("EMAIL_RECIPIENTS", "")
        email_recipients = [e.strip() for e in raw.split(",") if e.strip()]
    except Exception as e:
        log.warning(f"Email indisponÃ­vel, continuando sem: {e}")

    # â”€â”€ Notifier (sempre sobe â€” Telegram funciona mesmo sem email) â”€â”€
    notifier = GoalNotifier(
        bot=bot,
        admin_chats=allowed_users,
        email_client=email_client,
        email_recipients=email_recipients,
    )

    # â”€â”€ Scheduler + Auto-discovery de Goals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    scheduler = GoalScheduler(notifier)
    dp["scheduler"] = scheduler
    pipeline._scheduler = scheduler  # Guarda referÃªncia para commands acessarem

    try:
        deny_list = {
            g.strip().lower()
            for g in os.getenv("GOAL_DENY_LIST", "").split(",")
            if g.strip()
        }
        goals = discover_goals(pipeline, deny_list=deny_list)
        pipeline._goals = goals  # TambÃ©m guarda goals no pipeline
        for goal in goals:
            # Injeta notifier em goals que suportam (como RemoteExecutor)
            if hasattr(goal, 'notifier') and goal.notifier is None:
                goal.notifier = notifier
            scheduler.register(goal)
    except Exception as e:
        log.error(f"[scheduler] Falha no discovery de goals: {e}", exc_info=True)

    if scheduler._goals:
        await scheduler.start()
        log.info(f"  Goal Engine ativado ({len(scheduler._goals)} goals)")
    else:
        log.warning("  Nenhum goal registrado â€” rodando sÃ³ pipeline conversacional.")

    from src.core.habits.tracker import HabitTracker
    habit_tracker = HabitTracker()
    afk_protocol = AFKProtocol(bot, allowed_users, habit_tracker=habit_tracker)
    dp["afk_protocol"] = afk_protocol
    pipeline.afk_protocol = afk_protocol  # Injeta no pipeline

    log.info("Seeker.Bot iniciado")
    log.info("  MemÃ³ria persistente ativa")
    log.info("  Session context ativo")
    log.info("  Embeddings persistidos")
    log.info("  Aguardando mensagens...")

    # Workaround para "Logged out" error apÃ³s logOut() API call
    # Se bot.me() falha, cria um User fake para permitir polling
    try:
        test_me = await bot.me()
        log.info(f"Bot verificado: @{test_me.username}")
    except Exception as e:
        if "Logged out" in str(e):
            log.warning("Bot retornou 'Logged out' em bot.me(), mas continuando com polling...")
            # Cria um User fake para permitir que dispatcher inicie
            # Nota: polling ainda funcionarÃ¡ porque bot.me() foi cacheado internamente
            fake_user = User(
                id=int(token.split(":")[0]),  # Extrai bot ID do token
                is_bot=True,
                first_name="SeekerBot",
                username="SeekerBR1_bot"
            )
            bot._me = fake_user  # Cache do aiogram
            log.warning("Usando User fake para bypass de session check")
        else:
            raise

    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        # Cleanup Goal Engine
        scheduler = dp.get("scheduler")
        if scheduler:
            await scheduler.stop()

        # Cleanup: API Cascade health checks (Sprint 7.1)
        try:
            pipeline.cascade_adapter.stop_health_checks()
        except Exception as e:
            log.warning(f"Erro ao parar health checks: {e}")

        # Cleanup: pipeline (cancela decay, aguarda tasks, fecha memÃ³ria)
        await pipeline.close()
        await cleanup_client_pool()
        log.info("Shutdown completo")


if __name__ == "__main__":
    asyncio.run(main())

