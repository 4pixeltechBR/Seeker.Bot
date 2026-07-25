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
from prometheus_client import start_http_server
from aiogram.types import Message, CallbackQuery, BotCommand
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config.models import CognitiveRole
from src.core.pipeline import SeekerPipeline
from src.providers.base import cleanup_client_pool
from src.skills.vision.afk_protocol import AFKProtocol
from src.core.reasoning.ooda_loop import OODALoop
from src.core.logging_secure import setup_secure_logging

# Goal Engine
from src.core.goals import GoalScheduler, GoalNotifier, discover_goals
from src.channels.email.client import EmailClient
from src.skills.sense_news.prompts import NICHES
# SherlockNews helpers live in commands/sherlock.py

# Knowledge Vault (Obsidian)
from src.skills.knowledge_vault import KnowledgeVault

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
    """Registra comandos no menu azul do Telegram (BotCommand list).

    IMPORTANTE: este menu é o que aparece quando o usuário digita `/` no chat
    do Telegram. Só liste comandos que estão implementados em
    src/channels/telegram/commands/*.py. Para inventário completo, ver
    docs/HANDLERS_INVENTORY.md.

    Manter ordenado alfabeticamente (exceto /start que fica primeiro).
    """
    commands = [
        BotCommand(command="/start", description="▶️ Menu de ajuda + inventário de comandos"),
        # === Recuperação/Boot ===
        BotCommand(command="/config", description="⚙️ Painel de configuração (Skills, Providers, Restart)"),
        BotCommand(command="/restart", description="🔄 Reinicia o bot (admin)"),
        # === Diagnóstico do Sistema ===
        BotCommand(command="/status", description="📊 Painel de providers, memória e metas"),
        BotCommand(command="/saude", description="🏥 Dashboard de saúde dos goals (detalhado)"),
        BotCommand(command="/dashboard", description="📊 Dashboard completo do sistema (saúde, RL, custos, breakers)"),
        BotCommand(command="/perf", description="⚡ Dashboard de performance e latência"),
        BotCommand(command="/perf_detailed", description="⚡ Métricas detalhadas por fase"),
        BotCommand(command="/cascade_status", description="🔄 Status detalhado da API Cascade (6 tiers)"),
        BotCommand(command="/recovery", description="🛡️ Status de circuit breakers e degradação"),
        BotCommand(command="/rate", description="⏱️ Exibe status dos rate limiters"),
        # === Memória e Sessão ===
        BotCommand(command="/memory", description="🧠 Fatos aprendidos na sessão"),
        BotCommand(command="/god", description="⚡ Arma God Mode para a próxima mensagem"),
        BotCommand(command="/cancelar", description="❌ Cancela operação atual (vault, transcrição)"),
        # === Decaimento e Limpeza ===
        BotCommand(command="/decay", description="🧹 Roda limpeza de confiança manual"),
        BotCommand(command="/data_stats", description="💾 Estatísticas do armazém de dados"),
        BotCommand(command="/data_clean", description="🧹 Executa limpeza de dados antigos"),
        # === Custos ===
        BotCommand(command="/budget", description="💰 Gastos de hoje por provedor"),
        BotCommand(command="/budget_monthly", description="💰 Gastos do mês por provedor"),
        BotCommand(command="/forecast", description="📈 Previsões de custos para próximos 7 e 30 dias"),
        # === RL (Aprendizado por Reforço) ===
        BotCommand(command="/bandit", description="🎯 LinUCB em shadow mode (progresso de RL)"),
        BotCommand(command="/bandit_stats", description="🎯 Estatísticas do LinUCB (atalho para /bandit)"),
        BotCommand(command="/rl_tune", description="🧠 Tuning de parâmetros do LinUCB"),
        BotCommand(command="/rl_stats", description="📈 Estatísticas do LinUCB (conversão, arm stats)"),
        BotCommand(command="/rl_activate", description="🟢 Ativa o aprendizado por reforço (produção)"),
        BotCommand(command="/rl_deactivate", description="🔴 Desativa o aprendizado por reforço (shadow)"),
        BotCommand(command="/habits", description="🎯 Padrões de decisão aprendidos"),
        BotCommand(command="/audit_sara", description="🩺 Audit integrado do S.A.R.A"),
        # === Tarefas Agendadas (scheduler_conversacional) ===
        BotCommand(command="/agendar", description="📅 Agenda nova tarefa (wizard conversacional)"),
        BotCommand(command="/listar", description="📋 Lista tarefas agendadas do chat"),
        BotCommand(command="/detalhe", description="🔍 Ver detalhes de tarefa (/detalhe <ID>)"),
        BotCommand(command="/pausar", description="⏸ Pausa tarefa (/pausar <ID>)"),
        BotCommand(command="/reativar", description="▶️ Reativa tarefa (/reativar <ID>)"),
        BotCommand(command="/remover", description="🗑 Remove tarefa (/remover <ID>)"),
        BotCommand(command="/executar", description="⚡ Executa tarefa agora (/executar <ID>)"),
        # === Knowledge / Obsidian / Pesquisa ===
        BotCommand(command="/obsidian", description="📝 Salva conteúdo no cofre do Obsidian"),
        BotCommand(command="/cofre", description="🔍 Pesquisa no cofre do Obsidian"),
        BotCommand(command="/research", description="🔬 Pesquisa profunda sobre um tópico"),
        BotCommand(command="/research_schedule", description="🗓️ Agenda pesquisa recorrente"),
        # === Email ===
        BotCommand(command="/test_email", description="🧪 Força execução do Email Monitor (diagnóstico)"),
        # === ViralX9 (YouTube trending mining) ===
        BotCommand(command="/x9", description="🔭 ViralX9: ativar/desativar nichos de mineração"),
        BotCommand(command="/vx9_pausar", description="⏸ Pausar nicho do ViralX9"),
        BotCommand(command="/vx9_ativar", description="▶️ Ativar nicho do ViralX9"),
        BotCommand(command="/vx9_remover", description="🗑 Remover nicho do ViralX9"),
        BotCommand(command="/swarm_status", description="🐝 Status do Ruflo Swarm (multi-agente)"),
        # === Radar de Eventos ===
        # === Dev / Ferramentas ===
        BotCommand(command="/criar_skill", description="🛠️ Cria dinamicamente uma nova skill (Patcher L3)"),
        BotCommand(command="/git_backup", description="💾 Faz backup manual do código no GitHub privado"),
        BotCommand(command="/bug", description="🐛 Analisa bug com contexto e sugestões"),
        BotCommand(command="/bug_approve", description="✅ Aprova e aplica correções sugeridas"),
        BotCommand(command="/bug_cancel", description="❌ Cancela análise de bug"),
        # === Pesquisa direta ===
        BotCommand(command="/search", description="🔍 Busca direta e forçada na web"),
        BotCommand(command="/deep", description="🕵️ Pesquisa profunda autônoma (Kimi)"),
        # === Sherlock / Knowledge ===
        BotCommand(command="/sherlock", description="🕵️ SherlockNews: Painel Interativo de Monitoramento IA"),
        BotCommand(command="/configure_news", description="📰 Personaliza nichos do SenseNews"),
        # === Visão / Desktop ===
        BotCommand(command="/print", description="🖼️ Screenshot rápido da tela sem análise"),
        BotCommand(command="/watch", description="👁️ Ativa vigilância de tela (modo AFK)"),
        BotCommand(command="/watchoff", description="🚫 Desativa vigilância de tela"),
        # === Google Drive ===
        BotCommand(command="/drive", description="📁 Google Drive: listar, criar, enviar e baixar arquivos"),
        # === Transcrição ===
        BotCommand(command="/transcrever", description="🎙️ Transcreve o próximo áudio enviado"),
        # === Instagram ===
        BotCommand(command="/instascraper", description="📥 InstaScraper: Baixa vídeo do Instagram para o chat"),
        # === Vendas / CRM ===
        # === LLM (controle de modelo) ===
        BotCommand(command="/switch", description="🔄 Alterna entre modelos LLM (opinião, performance)"),
        BotCommand(command="/feedback", description="💬 Envia feedback/problema sobre o bot"),
        # === Terminal / MCP / WhatsApp (v3.9-3.12) ===
        BotCommand(command="/terminal", description="🖥️ Executa comando shell no host (estilo Hermes)"),
        BotCommand(command="/mcp", description="🔌 MCP: lista/invoca tools de servidores MCP (filesystem, github, etc.)"),
        BotCommand(command="/wa", description="📱 Status rápido do WhatsApp Vault"),
        BotCommand(command="/wa_config", description="⚙️ Painel de configuração do WhatsApp (hot-reload YAML)"),
        BotCommand(command="/wa_resend", description="🔄 Re-processa uma mensagem WhatsApp específica"),
        # === Promptograph (auditoria e geracao de system prompts) ===
        BotCommand(command="/validate", description="📋 Audita system prompt (13 boas praticas, nota A+ a F)"),
        BotCommand(command="/generate", description="✨ Gera system prompt (5 presets ou custom wizard)"),
    ]
    await bot.set_my_commands(commands)


async def check_storage_health(notifier: GoalNotifier):
    """
    Pilar 3: HealthCheck de Storage. 
    Verifica se o storage principal (GDRIVE_PATH) está acessível e alerta no Telegram se falhar.
    """
    gdrive_path = os.getenv("GDRIVE_PATH")
    if not gdrive_path:
        return True # Sem configuração de drive, opera normal local

    if not os.path.exists(gdrive_path):
        log.error(f"[health] GDRIVE_PATH definido mas INACESSÍVEL: {gdrive_path}")
        try:
            await notifier.notify_admin(
                "<b>🚨 ALERTA DE PERSISTÊNCIA (Pilar 3)</b>\n\n"
                f"A unidade de storage <code>{gdrive_path}</code> está <b>inacessível</b>.\n\n"
                "⚠️ O sistema de salvamento de dossiês foi interrompido para evitar perda de dados.\n"
                "💡 <i>Certifique-se que o Google Drive Desktop está aberto e a unidade I: montada.</i>"
            )
        except Exception as e:
            log.warning(f"Falha ao enviar alerta de storage: {e}")
        return False
    
    log.info(f"[health] Storage verificado: {gdrive_path} (ONLINE)")
    return True


def setup_handlers(dp: Dispatcher, pipeline: SeekerPipeline, allowed_users: set[int]):
    
    # Adiciona dependências no dispatcher
    dp["pipeline"] = pipeline
    dp["allowed_users"] = allowed_users
    
    from src.channels.telegram.commands.sherlock import sherlock_router
    dp.include_router(sherlock_router)

    from src.channels.telegram.commands.instascraper import instascraper_router
    dp.include_router(instascraper_router)

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
        gemini_key=os.getenv("GEMINI_API_KEY", ""),
        google_key=os.getenv("GOOGLE_SEARCH_API_KEY", ""),
        google_cx=os.getenv("GOOGLE_SEARCH_CX", ""),
    )
    vault = KnowledgeVault(pipeline.cascade_adapter, vlm_client=vlm, web_searcher=web_searcher)
    dp["vault_debouncer"] = {}  # Para agrupamento de mídias

    # Variaveis de estado local
    _obsidian_wait_users = set()
    _transcribe_wait_users = set()
    _bug_context = {}
    
    def _check_obsidian_state(uid: int) -> bool:
        if uid in _obsidian_wait_users:
            _obsidian_wait_users.discard(uid)
            return True
        return False

    def _check_transcribe_state(uid: int) -> bool:
        if uid in _transcribe_wait_users:
            _transcribe_wait_users.discard(uid)
            return True
        return False

    # Import and call factories
    from src.channels.telegram.commands.system import setup_system_handlers
    from src.channels.telegram.commands.tasks import setup_tasks_handlers
    from src.channels.telegram.commands.vision import setup_vision_handlers
    from src.channels.telegram.commands.vault import setup_vault_handlers
    from src.channels.telegram.commands.development import setup_development_handlers
    from src.channels.telegram.commands.message import setup_message_handlers

    setup_system_handlers(dp, pipeline)
    setup_tasks_handlers(dp, pipeline)
    setup_vision_handlers(dp, pipeline)
    setup_vault_handlers(dp, pipeline, vault, _obsidian_wait_users)
    setup_development_handlers(dp, pipeline, _bug_context)

    from src.channels.telegram.commands.config import setup_config_handlers
    setup_config_handlers(dp, pipeline)

    try:
        from src.channels.telegram.commands.whatsapp_config import setup_whatsapp_config_handlers
        setup_whatsapp_config_handlers(dp, pipeline)
        log.info("[bot] whatsapp config handlers registered")
    except ImportError:
        log.warning("[bot] whatsapp config handler not loaded (ImportError)")
    except Exception as e:
        log.error(f"[bot] Error registering whatsapp config: {e}", exc_info=True)

    try:
        from src.channels.telegram.commands.whatsapp import setup_whatsapp_handlers
        setup_whatsapp_handlers(dp, pipeline)
        log.info("[bot] whatsapp handlers registered (/wa, /wa_resend)")
    except ImportError:
        log.warning("[bot] whatsapp handler not loaded (ImportError)")
    except Exception as e:
        log.error(f"[bot] Error registering whatsapp handlers: {e}", exc_info=True)

    from src.channels.telegram.commands.drive import setup_drive_handlers
    setup_drive_handlers(dp, pipeline)

    try:
        from src.channels.telegram.commands.dashboard import setup_dashboard_handlers
        setup_dashboard_handlers(dp, pipeline)
    except ImportError:
        log.warning("[bot] dashboard handler não carregado (ImportError)")
    except Exception as e:
        log.error(f"[bot] Erro ao registrar dashboard handlers: {e}", exc_info=True)

    # IMPORTANTE: radar e custom_extension devem ser registrados ANTES do setup_message_handlers
    # porque message.py registra um catch-all F.text que engole qualquer comando
    # registrado depois dele. No aiogram 3 o primeiro handler com filtro correspondente ganha.
    try:
        from src.channels.telegram.commands.radar import setup_radar_handlers
        setup_radar_handlers(dp, pipeline)
    except ImportError:
        log.warning("[bot] radar handler não carregado (ImportError)")
    except Exception as e:
        log.error(f"[bot] Erro ao registrar radar handlers: {e}", exc_info=True)

    try:
    except ImportError:
        log.warning("[bot] custom_extension handler não carregado (ImportError)")
    except Exception as e:
        log.error(f"[bot] Erro ao registrar custom_extension handlers: {e}", exc_info=True)

    try:
        from src.channels.telegram.commands.research import setup_research_handlers
        setup_research_handlers(dp, pipeline)
    except ImportError:
        log.warning("[bot] research handler não carregado (ImportError)")
    except Exception as e:
        log.error(f"[bot] Erro ao registrar research handlers: {e}", exc_info=True)

    try:
        from src.channels.telegram.commands.terminal import setup_terminal_handlers
        setup_terminal_handlers(dp, pipeline)
        log.info("[bot] terminal handlers registrados com sucesso")
    except ImportError:
        log.warning("[bot] terminal handler não carregado (ImportError)")
    except Exception as e:
        log.error(f"[bot] Erro ao registrar terminal handlers: {e}", exc_info=True)

    try:
        from src.channels.telegram.commands.mcp import setup_mcp_handlers
        setup_mcp_handlers(dp, pipeline)
        log.info("[bot] mcp handlers registrados com sucesso")
    except ImportError:
        log.warning("[bot] mcp handler não carregado (ImportError)")
    except Exception as e:
        log.error(f"[bot] Erro ao registrar mcp handlers: {e}", exc_info=True)

    try:
        from src.channels.telegram.commands.validate import setup_validate_handlers
        setup_validate_handlers(dp, pipeline)
        log.info("[bot] validate handlers registrados com sucesso")
    except ImportError:
        log.warning("[bot] validate handler não carregado (ImportError)")
    except Exception as e:
        log.error(f"[bot] Erro ao registrar validate handlers: {e}", exc_info=True)

    try:
        from src.channels.telegram.commands.generate import setup_generate_handlers
        setup_generate_handlers(dp, pipeline)
        log.info("[bot] generate handlers registrados com sucesso")
    except ImportError:
        log.warning("[bot] generate handler não carregado (ImportError)")
    except Exception as e:
        log.error(f"[bot] Erro ao registrar generate handlers: {e}", exc_info=True)

    # DEVE SER O ÚLTIMO: registra o catch-all F.text que processa mensagens livres
    setup_message_handlers(dp, pipeline, vault, _obsidian_wait_users, _check_obsidian_state, _transcribe_wait_users, _check_transcribe_state)


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
            "/config — ⚙️ painel de configurações (Skills, Providers)\n"
            "/god — força análise profunda na próxima\n"
            "/search [query] — busca direta na web\n"
            "/print — screenshot rápido do desktop\n"
            "/watch — ativa vigilância AFK (2 min)\n"
            "/watchoff — desativa vigilância\n"
            "/sherlock [modelo] — monitora lançamento de modelo\n"
            "/obsidian — 📝 salva conteúdo no cofre Obsidian\n"
            "/cofre [termo] — 🔍 pesquisa no cofre\n\n"
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
            "<b>🚀 Utilitários:</b>\n"            "/git_backup — backup manual no GitHub\n"
            "/configure_news — personaliza notícias\n"
            "/drive — 📁 acesso ao Google Drive\n"
            "/instascraper — 📥 baixa vídeo do Instagram para o chat (link de Reel/post)"
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
            await message.answer("❌ Erro na busca: consulta inválida")
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

    @dp.message(F.text.startswith("/deep "))
    async def cmd_deep_research(message: Message):
        query = message.text[6:].strip()
        if not query:
            await message.answer("Uso: /deep [tópico para investigação profunda]")
            return

        await message.answer(
            f"🕵️‍♂️ <b>S.A.R.A RESEARCH ATIVADO</b>\n\n"
            f"<i>Iniciando investigação autônoma sobre:</i>\n"
            f"<code>{html.escape(query)}</code>\n\n"
            f"⏳ <i>Ista pode levar de 30 a 90 segundos. O agente irá navegar na web, ler artigos e cruzar fontes antes de responder.</i>",
            parse_mode=ParseMode.HTML
        )

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(
            keep_typing(message.bot, message.chat.id, stop_typing)
        )
        
        try:
            from src.providers.base import LLMRequest, invoke_with_fallback
            
            prompt = (
                f"Sua missão é atuar como um investigador sênior de inteligência. "
                f"Pesquise profundamente sobre o tópico abaixo. Use a ferramenta $web_search "
                f"quantas vezes forem necessárias para cobrir todos os ângulos, fatos recentes e divergências.\n\n"
                f"TÓPICO:\n{query}\n\n"
                f"Entregue um dossiê completo, estruturado e cite os links/fontes que você encontrou. "
                f"Seja analítico, fuja do óbvio."
            )
            
            req = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                system="Você é um Agente de Pesquisa Autônomo. Use $web_search sem hesitar para encontrar fatos no mundo real.",
                max_tokens=8192,
                temperature=0.3
            )
            
            resp = await invoke_with_fallback(
                CognitiveRole.RESEARCH,
                req,
                pipeline.model_router,
                pipeline.api_keys
            )
            
            # Divide e envia a resposta (pode ser longa)
            final_text = resp.text
            final_text += f"\n\n💰 <i>Custo da Pesquisa: ${resp.cost_usd:.4f} | Tempo: {resp.latency_ms / 1000:.1f}s</i>"
            
            from src.channels.telegram.formatter import split_message, md_to_telegram_html
            chunks = split_message(md_to_telegram_html(final_text))
            for chunk in chunks:
                await message.answer(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                
        except asyncio.TimeoutError:
            await message.answer("⏱️ Timeout: A pesquisa foi muito profunda e excedeu o tempo limite (90s). Tente um tópico mais restrito.")
        except Exception as e:
            log.error(f"[deep] Erro na pesquisa autônoma: {e}", exc_info=True)
            await message.answer(f"❌ Erro durante a investigação: {str(e)[:100]}")
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
                "❌ Erro ao executar Email Monitor",
                parse_mode=ParseMode.HTML
            )

    # SherlockNews is handled by sherlock_router (registered above via dp.include_router)


async def main():
    # ── Singleton lock (prevenir 2 bots fazendo polling do mesmo token) ──
    from src.core.singleton_lock import acquire_bot_lock
    if not acquire_bot_lock():
        log.error("Outra instância do bot está ativa. Saindo para evitar TelegramConflictError.")
        raise SystemExit(2)

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

    # Inicializa servidor de métricas Prometheus na porta 9090
    try:
        start_http_server(9090)
        log.info("Servidor de métricas Prometheus iniciado na porta 9090")
    except OSError as e:
        log.warning(f"Não foi possível iniciar o servidor Prometheus: {e}")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN não configurado", exc_info=True)
        raise SystemExit(1)

    api_keys = {
        "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
        "gemini": os.getenv("GEMINI_API_KEY", ""),
        "groq": os.getenv("GROQ_API_KEY", ""),
        "kimi": os.getenv("KIMI_API_KEY", ""),
        "mistral": os.getenv("MISTRAL_API_KEY", ""),
        "nvidia": os.getenv("NVIDIA_API_KEY", ""),
        "cerebras": os.getenv("CEREBRAS_API_KEY", ""),
        "openrouter": os.getenv("OPENROUTER_API_KEY", ""),
        "zai": os.getenv("ZAI_API_KEY", ""),
        "xai": os.getenv("XAI_API_KEY", ""),
    }

    _gemini_key = api_keys.get("gemini", "")
    # Google mudou o formato das chaves Gemini em jun/2026: novo formato começa
    # com "AQ." (substituiu o "AIza..." antigo). Aceitar ambos os formatos.
    if _gemini_key and not (_gemini_key.startswith("AIza") or _gemini_key.startswith("AQ.")):
        log.warning(
            "GEMINI_API_KEY tem prefixo '%s' que não é reconhecido. "
            "Formatos válidos: 'AIza...' (legado, descontinuado em 19/06/2026) "
            "ou 'AQ.' (novo Interactions API). "
            "Gere nova chave em https://aistudio.google.com/app/apikey",
            _gemini_key[:6],
        )

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
        pipeline=pipeline,
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
        
        # Pilar 3: HealthCheck de Storage ativo no startup
        asyncio.create_task(check_storage_health(notifier))
    else:
        log.warning("  Nenhum goal registrado — rodando só pipeline conversacional.")

    from src.core.habits.tracker import HabitTracker
    habit_tracker = HabitTracker()
    afk_protocol = AFKProtocol(bot, allowed_users, habit_tracker=habit_tracker)
    dp["afk_protocol"] = afk_protocol
    pipeline.afk_protocol = afk_protocol  # Injeta no pipeline

    # ── Servidor RPC Local ────────────────────────────────
    from src.core.execution.rpc import RPCServer
    rpc_server = RPCServer()
    await rpc_server.start()

    # Inicia tarefas em background das ferramentas portadas (Sprint 7.2)
    try:
        from src.core.execution.adapters.manager import start_background_tasks
        await start_background_tasks()
        log.info("Tarefas em background das ferramentas portadas iniciadas com sucesso.")
    except Exception as e:
        log.warning(f"Erro ao iniciar tarefas em background das ferramentas portadas: {e}")

    log.info("Seeker.Bot iniciado")
    log.info("  Memória persistente ativa")
    log.info("  Session context ativo")
    log.info("  Embeddings persistidos")
    log.info("  Aguardando mensagens...")

    # Validação final: se o bot não consegue responder getMe, aborta com erro claro.
    # Antes havia um bypass que criava um User fake em "Logged out", o que mascarava
    # token revogado pelo BotFather e fazia o bot rodar sem conseguir entregar mensagens.
    # Agora falhamos de forma explícita.
    try:
        test_me = await bot.me()
        log.info(f"Bot verificado: @{test_me.username}")
    except Exception as e:
        log.error(
            f"Falha ao validar o bot via getMe: {type(e).__name__}: {e}. "
            f"Causas prováveis: token inválido/revogado pelo BotFather, "
            f"conflito com outra instância usando o mesmo token, "
            f"ou bloqueio regional do Telegram."
        )
        raise SystemExit(2) from e

    hb_stop_event = asyncio.Event()
    hb_task = None
    try:
        from src.channels.telegram.heartbeat import start_heartbeat_loop
        hb_task = asyncio.create_task(start_heartbeat_loop(pipeline, hb_stop_event))

        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        # Encerra heartbeat task
        if hb_task:
            hb_stop_event.set()
            try:
                await asyncio.wait_for(hb_task, timeout=5.0)
            except Exception as e:
                log.warning(f"Erro ao parar heartbeat loop: {e}")

        # Encerra RPCServer
        try:
            await rpc_server.stop()
        except Exception as e:
            log.warning(f"Erro ao parar RPCServer: {e}")

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
        
        # Cleanup: fecha a sessão do bot para evitar vazamento de aiohttp.ClientSession
        if bot and getattr(bot, "session", None):
            try:
                await bot.session.close()
            except Exception as e:
                log.warning(f"Erro ao fechar bot.session: {e}")
                
        log.info("Shutdown completo")


if __name__ == "__main__":
    asyncio.run(main())
