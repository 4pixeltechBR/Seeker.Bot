"""
Seeker.Bot — Telegram Bot
src/channels/telegram/bot.py

Executar: python -m src
"""

import json
import asyncio
import logging
import os
import html

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, BotCommand, BufferedInputFile, User
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config.models import build_default_router, CognitiveRole
from src.core.pipeline import SeekerPipeline, PipelineResult
from src.core.router.cognitive_load import CognitiveDepth
from src.channels.telegram.formatter import md_to_telegram_html, split_message, MAX_MSG_LENGTH, format_cost_line
from src.providers.base import _rate_limiters, cleanup_client_pool
from src.skills.vision.afk_protocol import AFKProtocol
from src.core.reasoning.ooda_loop import OODALoop, OODAIteration
from src.core.logging_secure import setup_secure_logging

# Goal Engine
from src.core.goals import GoalScheduler, GoalNotifier, discover_goals
from src.channels.email.client import EmailClient
from src.skills.sense_news.prompts import NICHES
# SherlockNews helpers live in commands/sherlock.py

# Knowledge Vault (Obsidian)
from src.skills.knowledge_vault import KnowledgeVault, ObsidianWriter, VaultSearcher, extract_from_audio

# Setup secure logging (masks secrets automatically)
setup_secure_logging()
log = logging.getLogger("seeker.telegram")


TYPING_INTERVAL = 4





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


async def setup_commands(bot: Bot):
    commands = [
        BotCommand(command="/start", description="Menu de ajuda e inicialização"),
        BotCommand(command="/status", description="Painel de providers, memória e metas"),
        BotCommand(command="/saude", description="Dashboard de saúde dos goals (detalhado)"),
        BotCommand(command="/perf", description="Dashboard de performance e latência"),
        BotCommand(command="/perf_detailed", description="Métricas detalhadas por fase"),
        BotCommand(command="/cascade_status", description="Status detalhado da API Cascade (6 tiers)"),
        BotCommand(command="/recovery", description="Status de circuit breakers e degradação"),
        BotCommand(command="/memory", description="Fatos aprendidos na sessão"),
        BotCommand(command="/god", description="Arma God Mode para a próxima mensagem"),
        BotCommand(command="/search", description="Busca direta e forçada na web"),
        BotCommand(command="/rate", description="Exibe status dos rate limiters"),
        BotCommand(command="/decay", description="Roda limpeza de confiança manual"),
        BotCommand(command="/budget", description="Gastos de hoje por provedor"),
        BotCommand(command="/budget_monthly", description="Gastos do mês por provedor"),
        BotCommand(command="/data_stats", description="Estatisticas do armazem de dados"),
        BotCommand(command="/data_clean", description="Executa limpeza de dados antigos"),
        BotCommand(command="/dashboard", description="Dashboard financeiro com status atual"),
        BotCommand(command="/forecast", description="Previsoes de custos para proximos 7 e 30 dias"),
        BotCommand(command="/habits", description="Padrões de decisão aprendidos"),
        BotCommand(command="/print", description="Screenshot rápido da tela sem analise"),
        BotCommand(command="/watch", description="Ativa vigilância de tela (modo AFK)"),
        BotCommand(command="/watchoff", description="Desativa vigilância de tela"),
        BotCommand(command="/scout", description="Dispara campanha B2B Scout (leads qualificados)"),
        BotCommand(command="/git_backup", description="Faz backup manual do código no GitHub privado"),
        BotCommand(command="/crm", description="Lista histórico de leads qualificados"),
        BotCommand(command="/configure_news", description="Personaliza nichos do SenseNews"),
        BotCommand(command="/agendar", description="📅 Agenda nova tarefa (wizard conversacional)"),
        BotCommand(command="/listar", description="📋 Lista tarefas agendadas do chat"),
        BotCommand(command="/detalhe", description="🔍 Ver detalhes de tarefa (/detalhe <ID>)"),
        BotCommand(command="/pausar", description="⏸ Pausa tarefa (/pausar <ID>)"),
        BotCommand(command="/reativar", description="▶️ Reativa tarefa (/reativar <ID>)"),
        BotCommand(command="/remover", description="🗑 Remove tarefa (/remover <ID>)"),
        BotCommand(command="/executar", description="⚡ Executa tarefa agora (/executar <ID>)"),
        BotCommand(command="/bug", description="🐛 Analisa bug com contexto e sugestões"),
        BotCommand(command="/bug_approve", description="✅ Aprova e aplica correções sugeridas"),
        BotCommand(command="/bug_cancel", description="❌ Cancela análise de bug"),
        BotCommand(command="/sherlock", description="🕵️ SherlockNews: Painel Interativo de Monitoramento IA"),
        BotCommand(command="/obsidian", description="📝 Salva conteúdo no cofre do Obsidian"),
        BotCommand(command="/cofre", description="🔍 Pesquisa no cofre do Obsidian"),
        BotCommand(command="/drive", description="📁 Google Drive: listar, criar, enviar e baixar arquivos"),
    ]
    await bot.set_my_commands(commands)


def setup_handlers(dp: Dispatcher, pipeline: SeekerPipeline, allowed_users: set[int]):
    
    # Adiciona dependências no dispatcher
    dp["pipeline"] = pipeline
    dp["allowed_users"] = allowed_users
    
    from src.channels.telegram.commands.sherlock import sherlock_router
    dp.include_router(sherlock_router)

    # --- AUTH MIDDLEWARE (covers every message + callback_query) ---
    from src.channels.telegram.middlewares.auth import AuthMiddleware
    _auth = AuthMiddleware(allowed_users)
    dp.message.middleware(_auth)
    dp.callback_query.middleware(_auth)

    # Initialize Knowledge Vault com VLM + WebSearcher para enriquecimento
    from src.skills.vision.vlm_client import VLMClient
    from src.core.search.web import WebSearcher
    vlm = VLMClient()
    web_searcher = WebSearcher(
        tavily_key=os.getenv("TAVILY_API_KEY", ""),
        brave_key=os.getenv("BRAVE_API_KEY", ""),
    )
    vault = KnowledgeVault(pipeline.cascade_adapter, vlm_client=vlm, web_searcher=web_searcher)
    dp["vault_debouncer"] = {}  # Para agrupamento de mídias

    # Variaveis de estado local
    _obsidian_wait_users = set()
    _bug_context = {}
    
    def _check_obsidian_state(uid: int) -> bool:
        return uid in _obsidian_wait_users

    # Import and call factories
    from src.channels.telegram.commands.system import setup_system_handlers
    from src.channels.telegram.commands.tasks import setup_tasks_handlers
    try:
        from src.channels.telegram.commands.sales import setup_sales_handlers
        has_sales = True
    except ImportError:
        has_sales = False

    from src.channels.telegram.commands.vision import setup_vision_handlers
    from src.channels.telegram.commands.vault import setup_vault_handlers
    from src.channels.telegram.commands.development import setup_development_handlers
    from src.channels.telegram.commands.message import setup_message_handlers

    setup_system_handlers(dp, pipeline)
    setup_tasks_handlers(dp, pipeline)
    if has_sales:
        setup_sales_handlers(dp, pipeline)
    setup_vision_handlers(dp, pipeline)
    setup_vault_handlers(dp, pipeline, vault, _obsidian_wait_users)
    setup_development_handlers(dp, pipeline, _bug_context)
    setup_message_handlers(dp, pipeline, vault, _obsidian_wait_users, _check_obsidian_state)

    from src.channels.telegram.commands.drive import setup_drive_handlers
    setup_drive_handlers(dp, pipeline)



    @dp.message(F.text == "/start")
    async def cmd_start(message: Message):

        user_id = message.from_user.id
        user_niches = await pipeline.memory.get_user_niches(user_id)

        # Mensagem inicial comum
        help_text = (
            "<b>🌌 Seeker.Bot — Seu agente inteligente</b>\n\n"
            "Manda qualquer mensagem que eu decido a profundidade.\n"
            "⚡ <i>reflex</i> · 🧠 <i>deliberate</i> · 🔬 <i>deep</i>\n\n"
            "<b>⚙️ Operação:</b>\n"
            "/god — força análise profunda na próxima\n"
            "/search [query] — busca direta na web\n"
            "/print — screenshot rápido do desktop\n"
            "/watch — ativa vigilância AFK (2 min)\n"
            "/watchoff — desativa vigilância\n"
            "/sherlock [modelo] — monitora lançamento de modelo\n\n"
            "<b>📊 Sistema & Performance:</b>\n"
            "/status — painel de providers e metas\n"
            "/saude — dashboard detalhado de goals\n"
            "/perf — dashboard de performance (latência, cost)\n"
            "/perf_detailed — métricas detalhadas por fase\n"
            "/memory — fatos aprendidos sobre você\n"
            "/rate — status dos rate limiters\n"
            "/habits — padrões de decisão aprendidos\n"
            "/decay — limpeza manual de memória\n\n"
            "<b>🤖 Aprendizado (RL):</b>\n"
            "/bandit — progresso do LinUCB (shadow mode)\n\n"
            "<b>🚀 Produção:</b>\n"
            "/scout — campanha B2B (leads qualificados)\n"
            "/crm — histórico de leads\n"
            "/git_backup — backup manual no GitHub\n"
            "/configure_news — personaliza notícias\n"
            "/drive — 📁 acesso ao Google Drive"
        )

        await message.answer(help_text, parse_mode=ParseMode.HTML)

        # Se primeira vez (sem preferências), oferece menu de nichos
        if user_niches is None:
            await _show_niches_menu(message, user_id)

    async def _show_niches_menu(message: Message, user_id: int):
        """Mostra menu de seleção de nichos para SenseNews"""
        niche_names = list(NICHES.keys())

        # Cria keyboard com botões para cada nicho
        buttons = []
        for niche in niche_names:
            buttons.append([
                InlineKeyboardButton(
                    text=f"✓ {niche}",
                    callback_data=f"niche_toggle:{niche}"
                )
            ])

        # Botão "Confirmar"
        buttons.append([
            InlineKeyboardButton(text="✅ Confirmar Seleção", callback_data="niches_done")
        ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await message.answer(
            "<b>📰 Personalize seu SenseNews</b>\n\n"
            "Escolha quais nichos de notícias te interessam:\n\n"
            "<i>Clique para selecionar/desselecionar, depois confirme.</i>",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

    @dp.callback_query(F.data.startswith("niche_toggle:"))
    async def cb_niche_toggle(query: CallbackQuery):
        """Callback para alternar seleção de nicho"""

        niche = query.data.split(":", 1)[1]
        user_id = query.from_user.id

        # Recupera seleção atual
        selected = await pipeline.memory.get_user_niches(user_id) or []

        # Alterna seleção
        if niche in selected:
            selected.remove(niche)
        else:
            selected.append(niche)

        # Salva estado temporário em storage (callback data ou chat data)
        dp["niche_selection"] = dp.get("niche_selection", {})
        dp["niche_selection"][user_id] = selected

        # Reconstrói keyboard com status atualizado
        niche_names = list(NICHES.keys())
        buttons = []
        for n in niche_names:
            check = "✅" if n in selected else "☐"
            buttons.append([
                InlineKeyboardButton(
                    text=f"{check} {n}",
                    callback_data=f"niche_toggle:{n}"
                )
            ])

        # Botão "Confirmar"
        buttons.append([
            InlineKeyboardButton(text="✅ Confirmar Seleção", callback_data="niches_done")
        ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await query.message.edit_reply_markup(reply_markup=keyboard)
        await query.answer()

    @dp.callback_query(F.data == "niches_done")
    async def cb_niches_done(query: CallbackQuery):
        """Callback para confirmar seleção de nichos"""

        user_id = query.from_user.id

        # Pega seleção temporária
        niche_selection = dp.get("niche_selection", {})
        selected = niche_selection.get(user_id, [])

        if not selected:
            await query.answer("Selecione pelo menos um nicho!", show_alert=True)
            return

        # Salva permanentemente no BD
        telegram_id = str(query.from_user.id)
        success = await pipeline.memory.set_user_niches(user_id, telegram_id, selected)

        if success:
            niche_list = "\n  ".join([f"• {n}" for n in selected])
            await query.message.edit_text(
                f"<b>✅ Preferências Salvas!</b>\n\n"
                f"<b>Seus nichos:</b>\n  {niche_list}\n\n"
                f"Suas notícias personalizadas virão todo dia às 10:00 AM.",
                parse_mode=ParseMode.HTML
            )
            # Limpa seleção temporária
            if user_id in niche_selection:
                del niche_selection[user_id]
        else:
            await query.answer("Erro ao salvar preferências. Tente novamente.", show_alert=True)

    @dp.message(F.text == "/configure_news")
    async def cmd_configure_news(message: Message):
        """Permite usuário reconfigurar preferências de SenseNews"""

        await _show_niches_menu(message, message.from_user.id)

    @dp.message(F.text.startswith("/search "))
    async def cmd_search(message: Message):
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
            await message.answer("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except (AttributeError, TypeError) as e:
            log.error(f"[search] Searcher not properly configured: {e}", exc_info=True,
                      extra={"context": "search_command", "error_type": type(e).__name__})
            await message.answer("❌ Serviço de busca não está disponível")
        except ValueError as e:
            log.error(f"[search] Invalid search query: {e}", exc_info=True,
                      extra={"context": "search_command", "error_type": "ValueError"})
            await message.answer(f"❌ Erro na busca: consulta inválida")
        except asyncio.TimeoutError:
            log.warning("[search] Search operation timeout")
            await message.answer("⏱️ Timeout na busca (>30s). Tente novamente com uma query mais simples.")
        except (RuntimeError, OSError) as e:
            log.error(f"[search] Search service error: {e}", exc_info=True,
                      extra={"context": "search_command", "error_type": type(e).__name__})
            await message.answer(f"❌ Erro na busca: {str(e)[:100]}")
        except Exception as e:
            log.critical(f"[search] Unexpected error in search: {e}", exc_info=True,
                         extra={"context": "search_command", "error_type": type(e).__name__})
            await message.answer("❌ Erro inesperado na busca")
        finally:
            stop_typing.set()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

    @dp.message(F.text == "/test_email")
    async def cmd_test_email(message: Message):
        """Força execução do email_monitor para diagnóstico"""

        await message.answer("🧪 Disparando teste do Email Monitor...", parse_mode=ParseMode.HTML)

        try:
            # Estratégia de busca: pipeline → scheduler → fallback
            email_goal = None

            # 1. Tenta em pipeline._goals (setado no startup)
            if hasattr(pipeline, '_goals') and pipeline._goals:
                for goal in pipeline._goals:
                    if hasattr(goal, 'name') and goal.name == 'email_monitor':
                        email_goal = goal
                        log.debug("[telegram] Email goal encontrado em pipeline._goals")
                        break

            # 2. Fallback: tenta em scheduler._goals
            if not email_goal:
                scheduler = dp.get("scheduler")
                if scheduler and hasattr(scheduler, '_goals'):
                    for goal in scheduler._goals.values():
                        if hasattr(goal, 'name') and goal.name == 'email_monitor':
                            email_goal = goal
                            log.debug("[telegram] Email goal encontrado em scheduler._goals")
                            break

            # 3. Último fallback: tenta pipeline._scheduler
            if not email_goal and hasattr(pipeline, '_scheduler'):
                scheduler = pipeline._scheduler
                if scheduler and hasattr(scheduler, '_goals'):
                    for goal in scheduler._goals.values():
                        if hasattr(goal, 'name') and goal.name == 'email_monitor':
                            email_goal = goal
                            log.debug("[telegram] Email goal encontrado em pipeline._scheduler")
                            break

            if not email_goal:
                # Debug: lista o que encontrou
                goals_available = []
                if hasattr(pipeline, '_goals'):
                    goals_available = [g.name for g in pipeline._goals if hasattr(g, 'name')]

                await message.answer(
                    f"❌ Email Monitor não encontrado.\n"
                    f"Goals disponíveis: {', '.join(goals_available) if goals_available else 'nenhum'}\n"
                    f"Execute `/saude` para verificar.",
                    parse_mode=ParseMode.HTML
                )
                return

            # Reset de hoje para forçar re-execução
            email_goal._last_run_date = ""
            log.info("[telegram] Forçando execução de email_monitor para diagnóstico")

            # Dispara um ciclo do email monitor
            result = await email_goal.run_cycle()

            # Formata resposta
            summary = result.summary or "Ciclo concluído"
            cost = f"💰 Custo: ${result.cost_usd:.4f}" if result.cost_usd > 0 else ""

            response_lines = [
                "✅ <b>Email Monitor Executado</b>\n",
                f"📋 {summary}",
            ]

            if result.notification:
                response_lines.append(f"\n{result.notification}")

            if cost:
                response_lines.append(cost)

            final_response = "\n".join(response_lines)
            await message.answer(final_response, parse_mode=ParseMode.HTML)

            # Envia logs relevantes
            log.info("[telegram] Email monitor test completado com sucesso")

        except (AttributeError, TypeError) as e:
            # Erro estrutural: goal ou método não existe/tipo incorreto
            log.error(
                f"[email_test] Erro estrutural ao testar email: {e}",
                exc_info=True,
                extra={"context": "email_test", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro: Email Monitor não está configurado corretamente. Execute `/saude` para mais detalhes.",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[email_test] Timeout ao executar email monitor (>30s)")
            await message.answer(
                "⏱️ Timeout: o Email Monitor demorou muito tempo para responder.",
                parse_mode=ParseMode.HTML
            )
        except (RuntimeError, ValueError) as e:
            # Erro de execução: problema na lógica do goal
            log.error(
                f"[email_test] Erro de execução: {e}",
                exc_info=True,
                extra={"context": "email_test", "error_type": type(e).__name__}
            )
            await message.answer(
                f"❌ Erro ao executar Email Monitor: {str(e)[:100]}",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            # Catch-all para exceções inesperadas
            log.critical(
                f"[email_test] Erro inesperado: {e}",
                exc_info=True,
                extra={"context": "email_test", "error_type": type(e).__name__}
            )
            await message.answer(
                f"❌ Erro ao executar Email Monitor",
                parse_mode=ParseMode.HTML
            )

    # SherlockNews is handled by sherlock_router (registered above via dp.include_router)


async def main():
    # ── Load .env ─────────────────────────────────────────
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

    # Console handler (mantém comportamento original)
    logging.basicConfig(level=log_level, format=log_fmt._fmt, datefmt=log_fmt.datefmt)

    # File handler — persistência para o self_improvement_loop
    from logging.handlers import RotatingFileHandler
    _log_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "logs",
    )
    os.makedirs(_log_dir, exist_ok=True)
    _file_handler = RotatingFileHandler(
        os.path.join(_log_dir, "seeker.log"),
        maxBytes=5 * 1024 * 1024,    # 5 MB por arquivo
        backupCount=3,                # mantém seeker.log.1, .2, .3
        encoding="utf-8",
    )
    _file_handler.setLevel(log_level)
    _file_handler.setFormatter(log_fmt)
    logging.getLogger().addHandler(_file_handler)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN não configurado", exc_info=True)
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

    # ── Reset heartbeat file (watchdog init) ───────────────
    # Limpar arquivo de heartbeat antigo para evitar que watchdog
    # mate o bot logo após iniciar pensando que está travado
    try:
        hb_path = "logs/bot_heartbeat.txt"
        if os.path.exists(hb_path):
            os.remove(hb_path)
        log.debug("[startup] Heartbeat file limpo para novo ciclo")
    except Exception as e:
        log.warning(f"[startup] Erro ao limpar heartbeat: {e}")

    # ── Init API Cascade Health Checks (Sprint 7.1) ─────────
    try:
        await pipeline.cascade_adapter.start_health_checks(interval_seconds=30)
        log.info("  API Cascade health checks iniciados (interval=30s)")
    except Exception as e:
        log.warning(f"Erro ao iniciar health checks: {e}")

    # ── Init bot ──────────────────────────────────────────
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # ── Init OODA Loop (for structured decision-making + auditability) ──
    dp["ooda_loop"] = OODALoop()

    try:
        await setup_commands(bot)
    except Exception as e:
        log.warning(f"setup_commands falhou (não crítico): {e}")

    setup_handlers(dp, pipeline, allowed_users)

    # ── Init Autonomous Skills (Goal Engine) ──────────────
    
    # ── Email (opcional — falha não impede boot) ──────────
    email_client = None
    email_recipients = []
    try:
        email_client = EmailClient.from_env()
        raw = os.getenv("EMAIL_RECIPIENTS", "")
        email_recipients = [e.strip() for e in raw.split(",") if e.strip()]
    except Exception as e:
        log.warning(f"Email indisponível, continuando sem: {e}")

    # ── Notifier (sempre sobe — Telegram funciona mesmo sem email) ──
    notifier = GoalNotifier(
        bot=bot,
        admin_chats=allowed_users,
        email_client=email_client,
        email_recipients=email_recipients,
    )

    # ── Scheduler + Auto-discovery de Goals ───────────────
    scheduler = GoalScheduler(notifier)
    dp["scheduler"] = scheduler
    pipeline._scheduler = scheduler  # Guarda referência para commands acessarem

    try:
        deny_list = {
            g.strip().lower()
            for g in os.getenv("GOAL_DENY_LIST", "").split(",")
            if g.strip()
        }
        goals = discover_goals(pipeline, deny_list=deny_list)
        pipeline._goals = goals  # Também guarda goals no pipeline
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
        log.warning("  Nenhum goal registrado — rodando só pipeline conversacional.")

    from src.core.habits.tracker import HabitTracker
    habit_tracker = HabitTracker()
    afk_protocol = AFKProtocol(bot, allowed_users, habit_tracker=habit_tracker)
    dp["afk_protocol"] = afk_protocol
    pipeline.afk_protocol = afk_protocol  # Injeta no pipeline

    log.info("Seeker.Bot iniciado")
    log.info("  Memória persistente ativa")
    log.info("  Session context ativo")
    log.info("  Embeddings persistidos")
    log.info("  Aguardando mensagens...")

    # Workaround para "Logged out" error após logOut() API call
    # Se bot.me() falha, cria um User fake para permitir polling
    try:
        test_me = await bot.me()
        log.info(f"Bot verificado: @{test_me.username}")
    except Exception as e:
        if "Logged out" in str(e):
            log.warning("Bot retornou 'Logged out' em bot.me(), mas continuando com polling...")
            # Cria um User fake para permitir que dispatcher inicie
            # Nota: polling ainda funcionará porque bot.me() foi cacheado internamente
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

        # Cleanup: pipeline (cancela decay, aguarda tasks, fecha memória)
        await pipeline.close()
        await cleanup_client_pool()
        log.info("Shutdown completo")


if __name__ == "__main__":
    asyncio.run(main())
