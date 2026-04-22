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
from src.channels.telegram.formatter import md_to_telegram_html
from src.providers.base import _rate_limiters, cleanup_client_pool
from src.skills.vision.afk_protocol import AFKProtocol
from src.core.reasoning.ooda_loop import OODALoop, OODAIteration
from src.core.logging_secure import setup_secure_logging

# Goal Engine
from src.core.goals import GoalScheduler, GoalNotifier, discover_goals
from src.channels.email.client import EmailClient
from src.skills.sense_news.prompts import NICHES
from src.skills.sherlock_news.targets_manager import add_target, list_targets # SherlockNews

# Knowledge Vault (Obsidian)
from src.skills.knowledge_vault import KnowledgeVault, ObsidianWriter, VaultSearcher, extract_from_audio

# Setup secure logging (masks secrets automatically)
setup_secure_logging()
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


def format_cost_line(result: PipelineResult) -> str:
    parts = []
    if result.total_cost_usd > 0:
        parts.append(f"${result.total_cost_usd:.4f}")
    parts.append(f"{result.total_latency_ms}ms")
    parts.append(f"{result.llm_calls} calls")
    if result.facts_used > 0:
        parts.append(f"🧠 {result.facts_used} fatos")
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
        BotCommand(command="/sherlock", description="🕵️ SherlockNews: Adiciona modelo para monitorar (/sherlock <nome>)"),
        BotCommand(command="/obsidian", description="📝 Salva conteúdo no cofre do Obsidian"),
        BotCommand(command="/cofre", description="🔍 Pesquisa no cofre do Obsidian")
    ]
    await bot.set_my_commands(commands)


def setup_handlers(dp: Dispatcher, pipeline: SeekerPipeline, allowed_users: set[int]):
    
    # Initialize Knowledge Vault
    from src.skills.vision.vlm_client import VLMClient
    vlm = VLMClient()
    vault = KnowledgeVault(pipeline.cascade_adapter, vlm_client=vlm)
    dp["vault_debouncer"] = {} # Para agrupamento de mídias

    @dp.message(F.text == "/start")
    async def cmd_start(message: Message):
        if not _is_allowed(message, allowed_users):
            return

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
            "/configure_news — personaliza notícias"
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
        if not _is_allowed_callback(query, allowed_users):
            return

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
        if not _is_allowed_callback(query, allowed_users):
            return

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
        if not _is_allowed(message, allowed_users):
            return

        await _show_niches_menu(message, message.from_user.id)

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

    @dp.message(F.text.startswith("/crm"))
    async def cmd_crm(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        args = message.text.split()
        limit = 5  # Default: 5 últimos leads
        if len(args) > 1 and args[1].isdigit():
            limit = int(args[1])
            
        leads = await pipeline.memory.get_leads(limit=limit)
        
        if not leads:
            await message.answer("📭 Nenhum lead qualificado no CRM ainda.")
            return
            
        header = f"🎯 <b>CRM SEEKER — ÚLTIMOS {len(leads)} LEADS</b>\n\n"
        out = [header]
        
        for i, lead in enumerate(leads, 1):
            name = lead.get("name", "Desconhecido")
            score = lead.get("score", 0)
            city = lead.get("city", "GO")
            contacts = json.loads(lead.get("contact_info", "{}"))
            
            # Formata contatos
            c_links = []
            if contacts.get("whatsapp"): c_links.append("WA")
            if contacts.get("instagram"): c_links.append("IG")
            if contacts.get("website"): c_links.append("WEB")
            c_str = " | ".join(c_links) if c_links else "S/ Contato"
            
            out.append(
                f"<b>{i}. {name}</b> ({city})\n"
                f"Score: <code>{score}</code> | {c_str}\n"
                f"Sinais: <i>{lead.get('hiring_signs', 'N/A')[:100]}...</i>\n"
            )
            
        final_text = "\n".join(out)
        await message.answer(final_text, parse_mode=ParseMode.HTML)

    @dp.message(F.text == "/test_email")
    async def cmd_test_email(message: Message):
        """Força execução do email_monitor para diagnóstico"""
        if not _is_allowed(message, allowed_users):
            return

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
                    for goal in scheduler._goals:
                        if hasattr(goal, 'name') and goal.name == 'email_monitor':
                            email_goal = goal
                            log.debug("[telegram] Email goal encontrado em scheduler._goals")
                            break

            # 3. Último fallback: tenta pipeline._scheduler
            if not email_goal and hasattr(pipeline, '_scheduler'):
                scheduler = pipeline._scheduler
                if scheduler and hasattr(scheduler, '_goals'):
                    for goal in scheduler._goals:
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

    @dp.message(F.text.startswith("/scout"))
    async def cmd_scout(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        await message.answer("🎯 Disparando campanha Scout B2B...", parse_mode=ParseMode.HTML)

        try:
            # Tenta obter Scout skill do pipeline
            scout_goal = None
            if hasattr(pipeline, '_goals'):
                for goal in pipeline._goals:
                    if hasattr(goal, 'name') and goal.name == 'scout_hunter':
                        scout_goal = goal
                        break

            if not scout_goal:
                await message.answer(
                    "❌ Scout skill não foi encontrada ou não está ativa.\n"
                    "Execute `/saude` para verificar o status dos goals.",
                    parse_mode=ParseMode.HTML
                )
                return

            # Dispara um ciclo da Scout
            result = await scout_goal.run_cycle()

            # Formata resposta
            summary = result.summary or "Campanha concluída"
            cost = f"💰 Custo: ${result.cost_usd:.4f}" if result.cost_usd > 0 else ""

            response_lines = [
                "✅ <b>Scout Campaign Executada</b>\n",
                f"📋 {summary}",
            ]

            if result.data:
                data = result.data
                if data.get('campaign_id'):
                    response_lines.append(f"🆔 Campaign ID: <code>{data['campaign_id'][:12]}</code>")
                if data.get('total_scraped'):
                    response_lines.append(f"📊 Leads Raspados: {data['total_scraped']}")
                if data.get('qualified'):
                    response_lines.append(f"✅ Qualificados: {data['qualified']}")
                if data.get('written'):
                    response_lines.append(f"📝 Com Copy: {data['written']}")
                if data.get('rejected'):
                    response_lines.append(f"❌ Rejeitados: {data['rejected']}")

            if cost:
                response_lines.append(cost)

            final_response = "\n".join(response_lines)
            await message.answer(final_response, parse_mode=ParseMode.HTML)

        except (AttributeError, TypeError) as e:
            log.error(
                f"[scout] Scout skill não está configurado corretamente: {e}",
                exc_info=True,
                extra={"context": "scout_campaign", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Scout skill não está disponível.\nExecute `/saude` para verificar.",
                parse_mode=ParseMode.HTML
            )
        except KeyError as e:
            log.error(
                f"[scout] Dados de campanha incompletos: {e}",
                exc_info=True,
                extra={"context": "scout_campaign", "error_type": "KeyError"}
            )
            await message.answer(
                "❌ Erro: Dados da campanha incompletos. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[scout] Scout campaign timeout (>120s)")
            await message.answer(
                "⏱️ Timeout: Scout campaign demorou muito. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except (RuntimeError, ValueError) as e:
            log.error(
                f"[scout] Erro de execução da campanha: {e}",
                exc_info=True,
                extra={"context": "scout_campaign", "error_type": type(e).__name__}
            )
            await message.answer(
                f"❌ Erro ao executar Scout: {str(e)[:100]}",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[scout] Erro inesperado em scout campaign: {e}",
                exc_info=True,
                extra={"context": "scout_campaign", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Scout campaign falhou de forma inesperada",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text.startswith("/sherlock"))
    async def cmd_sherlock(message: Message):
        """🕵️ SherlockNews: Gerencia modelos monitorados"""
        if not _is_allowed(message, allowed_users):
            return

        args = message.text[9:].strip()
        
        if not args:
            # Lista alvos atuais
            targets = list_targets()
            if not targets:
                await message.answer("🕵️ SherlockNews: Nenhum modelo sendo monitorado no momento.\nUse <code>/sherlock <nome></code> para adicionar.", parse_mode=ParseMode.HTML)
            else:
                targets_str = "\n".join([f"• <code>{t}</code>" for t in targets])
                await message.answer(f"🕵️ <b>SherlockNews: Alvos Ativos</b>\n\n{targets_str}\n\n<i>Eu verifico o status deles todo dia às 08:00.</i>", parse_mode=ParseMode.HTML)
            return

        # Adiciona novo alvo
        if add_target(args):
            await message.answer(f"🕵️ <b>SherlockNews: Alvo Adicionado!</b>\n\nModelo: <code>{args}</code>\n<i>Vou te avisar assim que detectar o lançamento oficial.</i>", parse_mode=ParseMode.HTML)
        else:
            await message.answer("❌ Erro ao adicionar modelo ao SherlockNews.")

    @dp.message(F.text == "/git_backup")
    async def cmd_git_backup(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        await message.answer("📦 Iniciando backup de código no GitHub...", parse_mode=ParseMode.HTML)

        try:
            # Encontra o goal git_backup
            git_backup_goal = None
            if hasattr(pipeline, '_goals'):
                for goal in pipeline._goals:
                    if hasattr(goal, 'name') and goal.name == 'git_backup':
                        git_backup_goal = goal
                        break

            if not git_backup_goal:
                await message.answer(
                    "❌ Git backup skill não foi encontrada ou não está ativa.\n"
                    "Execute `/saude` para verificar o status dos goals.",
                    parse_mode=ParseMode.HTML
                )
                return

            # Dispara um ciclo do git_backup
            result = await git_backup_goal.run_cycle()

            # Formata resposta
            summary = result.summary or "Backup concluído"
            cost = f"💰 Custo: ${result.cost_usd:.4f}" if result.cost_usd > 0 else ""

            response_lines = [
                "✅ <b>GitHub Backup Executado</b>\n",
                f"📋 {summary}",
            ]

            if result.data:
                data = result.data
                if data.get('status'):
                    response_lines.append(f"🔄 Status: {data['status']}")
                if data.get('pushed'):
                    response_lines.append(f"📤 Pushed: {data['pushed']}")
                if data.get('commit'):
                    response_lines.append(f"🔗 Commit: <code>{data['commit'][:12]}</code>")
                if data.get('repo'):
                    response_lines.append(f"📦 Repo: <code>{data['repo']}</code>")

            if cost:
                response_lines.append(cost)

            final_response = "\n".join(response_lines)
            await message.answer(final_response, parse_mode=ParseMode.HTML)

        except (AttributeError, TypeError) as e:
            log.error(
                f"[git_backup] Git backup skill não configurado: {e}",
                exc_info=True,
                extra={"context": "git_backup", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Git backup skill não está disponível.\nExecute `/saude` para verificar.",
                parse_mode=ParseMode.HTML
            )
        except (FileNotFoundError, OSError) as e:
            log.error(
                f"[git_backup] Erro de acesso ao repositório: {e}",
                exc_info=True,
                extra={"context": "git_backup", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao acessar repositório Git. Verifique credenciais.",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[git_backup] Git backup timeout (>60s)")
            await message.answer(
                "⏱️ Timeout: Backup no GitHub demorou muito. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except (RuntimeError, ValueError) as e:
            log.error(
                f"[git_backup] Erro de execução do backup: {e}",
                exc_info=True,
                extra={"context": "git_backup", "error_type": type(e).__name__}
            )
            await message.answer(
                f"❌ Erro ao executar backup: {str(e)[:100]}",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[git_backup] Erro inesperado: {e}",
                exc_info=True,
                extra={"context": "git_backup", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Backup falhou de forma inesperada",
                parse_mode=ParseMode.HTML
            )

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
            # Métricas de uso de memória semântica
            mem_stats = pipeline.get_memory_stats()
            if mem_stats["responses"] > 0:
                lines.append(
                    f"  Uso de fatos: {mem_stats['with_facts']}/{mem_stats['responses']} "
                    f"respostas ({mem_stats['usage_rate_pct']}%) · "
                    f"média {mem_stats['avg_facts_per_response']} fatos/resp"
                )
            # Session info
            active = pipeline.session.active_sessions
            if active:
                lines.append(f"  Sessões ativas: {len(active)}")
            
            # Goal Engine status
            scheduler = dp.get("scheduler")
            if scheduler:
                lines.append(f"\n{scheduler.get_status_report()}")

            # OODA Loop statistics (FASE 4)
            ooda_loop = dp.get("ooda_loop")
            if ooda_loop:
                ooda_stats = ooda_loop.get_stats()
                if ooda_stats["total_iterations"] > 0:
                    lines.append(f"\n<b>🔄 OODA Loop:</b>")
                    lines.append(f"  {ooda_stats['total_iterations']} iterações")
                    lines.append(
                        f"  Success rate: {ooda_stats['success_rate']:.0%} "
                        f"| Bloqueadas: {ooda_stats['blocked_count']}"
                    )
                    lines.append(f"  Latência média: {ooda_stats['avg_latency_ms']:.0f}ms")

        except Exception:
            lines.append(f"\n<b>Memória:</b> inicializando...")
        await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

    @dp.message(F.text == "/saude")
    async def cmd_saude(message: Message):
        if not _is_allowed(message, allowed_users):
            return
        try:
            scheduler = dp.get("scheduler")
            if not scheduler:
                await message.answer("❌ Goal scheduler não inicializado.", parse_mode=ParseMode.HTML)
                return

            dashboard = scheduler.get_health_dashboard()
            lines = ["<b>📊 Health Dashboard dos Goals</b>\n"]

            # Global summary
            lines.append(f"<b>🌍 Global:</b>")
            lines.append(
                f"  Total: {dashboard['summary']['total_goals']} goals | "
                f"Taxa média: {dashboard['summary']['avg_success_rate']:.1f}% | "
                f"Custo: ${dashboard['summary']['total_cost_today']:.4f}"
            )

            # Budget
            spent = dashboard["global_budget"]["spent"]
            limit = dashboard["global_budget"]["limit"]
            pct = spent / limit * 100 if limit > 0 else 0
            emoji = "🔴" if pct > 80 else ("🟡" if pct > 50 else "🟢")
            lines.append(f"\n<b>💰 Budget Global:</b> {emoji} ${spent:.4f}/${limit} ({pct:.0f}%)")

            # Per-goal metrics
            lines.append(f"\n<b>📈 Goals Detalhados:</b>")
            for goal_name, metrics in sorted(dashboard["goals"].items()):
                m = metrics["metrics"]
                status_emoji = {
                    "RUNNING": "🟢",
                    "IDLE": "⏸",
                    "PAUSED": "🟡",
                    "ERROR": "🔴",
                }.get(metrics["status"], "⚪")

                # Trend sparkline
                trend_emoji = m.get("trend", "➡️")

                # Success rate with recent comparison
                recent = m.get("recent_5_success_rate", 0)
                rate = m["success_rate"]
                rate_str = f"{rate:.0f}% ({recent:.0f}% recent)"

                lines.append(
                    f"  {status_emoji} <b>{goal_name}</b> {trend_emoji}\n"
                    f"    ✅ Taxa: {rate_str} | "
                    f"⏱️ Latência: {m['avg_latency']:.2f}s | "
                    f"💵 Total: ${m['total_cost']:.4f}\n"
                    f"    📊 Ciclos: {m['total_cycles']} | "
                    f"🔴 Falhas: {m['consecutive_failures']}"
                )

                # Budget per-goal
                budget = metrics["budget"]
                budget_pct = budget["spent_today"] / budget["limit"] * 100 if budget["limit"] > 0 else 0
                budget_emoji = "🔴" if budget_pct > 80 else ("🟡" if budget_pct > 50 else "🟢")
                lines.append(f"    {budget_emoji} Budget: ${budget['spent_today']:.4f}/${budget['limit']} ({budget_pct:.0f}%)")

            # Friction metrics
            friction = dashboard["friction_metrics"]
            if sum(friction.values()) > 0:
                lines.append(f"\n<b>🛡️ Fricção Controlada:</b>")
                if friction["rethinks_blocked"] > 0:
                    lines.append(f"  🛑 Rethinks: {friction['rethinks_blocked']}")
                if friction["sara_edits"] > 0:
                    lines.append(f"  🛠️ SARA Edits: {friction['sara_edits']}")
                if friction["rate_limits"] > 0:
                    lines.append(f"  🚷 Rate Limits: {friction['rate_limits']}")

            # Last update timestamp
            import datetime
            ts = datetime.datetime.fromtimestamp(dashboard["timestamp"])
            lines.append(f"\n<i>Atualizado em: {ts.strftime('%H:%M:%S')}</i>")

            msg = "\n".join(lines)

            # Split if too long
            for part in split_message(msg):
                await message.answer(part, parse_mode=ParseMode.HTML)

        except (AttributeError, TypeError) as e:
            log.error(
                f"[saude] Goal scheduler not properly initialized: {e}",
                exc_info=True,
                extra={"context": "health_dashboard", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Goal scheduler não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[saude] Invalid health dashboard data: {e}",
                exc_info=True,
                extra={"context": "health_dashboard", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao processar dados de saúde",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[saude] Unexpected error in health dashboard: {e}",
                exc_info=True,
                extra={"context": "health_dashboard", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao carregar dashboard de saúde",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/perf")
    async def cmd_perf(message: Message):
        """Dashboard de performance do sistema"""
        if not _is_allowed(message, allowed_users):
            return
        try:
            report = pipeline.format_perf_report()
            await message.answer(report, parse_mode=ParseMode.HTML)
        except AttributeError as e:
            log.error(
                f"[perf] Performance reporter not available: {e}",
                exc_info=True,
                extra={"context": "perf_report", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de performance não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (ValueError, KeyError) as e:
            log.error(
                f"[perf] Invalid performance data: {e}",
                exc_info=True,
                extra={"context": "perf_report", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao gerar relatório de performance",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[perf] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "perf_report", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao gerar relatório",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/perf_detailed")
    async def cmd_perf_detailed(message: Message):
        """Métricas detalhadas de performance por fase + Sprint 11 Optimizations"""
        if not _is_allowed(message, allowed_users):
            return
        try:
            # Relatório Sprint 11 (Cascade + Cache + Batch)
            sprint11_report = pipeline.get_sprint11_report()

            # Dashboard geral
            dashboard = pipeline.get_performance_dashboard()
            goals = dashboard["goals"]

            lines = [sprint11_report]

            if goals:
                # Formata por goal
                lines.append("<b>📊 GOALS PERFORMANCE</b>\n")
                for goal_id, metrics in list(goals.items())[:5]:  # Top 5 goals
                    lines.append(
                        f"<b>{goal_id}</b>\n"
                        f"  Cycles: {metrics['cycles']} | Success: {metrics['success_rate']}\n"
                        f"  Cost: {metrics['total_cost']} | Avg Latency: {metrics['avg_latency_ms']}ms\n"
                    )

            detailed = "".join(lines)

            # Dividir em chunks se muito grande
            for part in split_message(detailed):
                await message.answer(part, parse_mode=ParseMode.HTML)

        except (AttributeError, TypeError) as e:
            log.error(
                f"[perf_detailed] Performance dashboard not available: {e}",
                exc_info=True,
                extra={"context": "perf_detailed", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Dashboard de performance não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[perf_detailed] Invalid performance data: {e}",
                exc_info=True,
                extra={"context": "perf_detailed", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao processar métricas de performance",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[perf_detailed] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "perf_detailed", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao carregar métricas detalhadas",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/cascade_status")
    async def cmd_cascade_status(message: Message):
        """Status detalhado da API Cascade — 6 tiers com health checks"""
        if not _is_allowed(message, allowed_users):
            return
        try:
            # Health status de cada tier
            health = pipeline.cascade_adapter.get_health_status()
            cost_analysis = pipeline.cascade_adapter.get_cost_analysis()

            # Formatar status dos tiers
            lines = ["<b>🔀 API CASCADE STATUS (6 Tiers)</b>\n"]
            lines.append(f"<b>Timestamp:</b> {health['timestamp'][:19]}\n")
            lines.append(f"<b>Overall Health:</b> {health['overall_health']}\n\n")

            lines.append("<b>📊 TIER BREAKDOWN:</b>\n")
            for tier_name, tier_status in health["tiers"].items():
                health_emoji = "✅" if tier_status["is_healthy"] else "⚠️"
                lines.append(
                    f"{health_emoji} <b>{tier_name.upper()}</b>\n"
                    f"  Success Rate: {tier_status['success_rate']}\n"
                    f"  Avg Latency: {tier_status['avg_latency_ms']}ms\n"
                    f"  Cost/Call: {tier_status['avg_cost_usd']}\n"
                    f"  Fallbacks: {tier_status['fallback_count']}\n"
                )
                if tier_status["last_error"]:
                    lines.append(f"  Last Error: {tier_status['last_error'][:50]}...\n")

            lines.append("\n<b>💰 COST ANALYSIS:</b>\n")
            lines.append(f"Total Calls: {cost_analysis['total_calls']}\n")
            lines.append(f"Total Cost: ${cost_analysis['total_cost_usd']}\n")
            lines.append(f"Avg Cost/Call: ${cost_analysis['average_cost_per_call']}\n")
            lines.append(f"Savings vs NIM: {cost_analysis['estimated_savings_vs_nim']}\n")

            # Error breakdown
            if cost_analysis.get("error_breakdown"):
                lines.append("\n<b>🔴 ERROR BREAKDOWN:</b>\n")
                for tier_name, errors in cost_analysis["error_breakdown"].items():
                    if errors:
                        lines.append(f"<b>{tier_name}:</b> {errors}\n")

            status_msg = "".join(lines)

            # Dividir em chunks se muito grande
            for part in split_message(status_msg):
                await message.answer(part, parse_mode=ParseMode.HTML)

        except (AttributeError, TypeError) as e:
            log.error(
                f"[cascade_status] Cascade adapter not available: {e}",
                exc_info=True,
                extra={"context": "cascade_status", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Cascade adapter não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[cascade_status] Invalid cascade health data: {e}",
                exc_info=True,
                extra={"context": "cascade_status", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao processar status da cascata",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[cascade_status] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "cascade_status", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao gerar status da cascata",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text.in_({"/bandit", "/bandit_stats"}))
    async def cmd_bandit(message: Message):
        """Status do LinUCB Cascade Bandit e progresso de aprendizado"""
        if not _is_allowed(message, allowed_users):
            return
        try:
            bandit = pipeline.cascade_bandit
            stats  = bandit.get_stats()
            rl_stats = pipeline.get_rl_stats()

            # Progresso para ativar modo ACTIVE
            updates = stats["total_updates"]
            needed  = 100
            pct     = min(100, int(updates / needed * 100))
            bar_filled = int(pct / 10)
            progress_bar = "█" * bar_filled + "░" * (10 - bar_filled)

            # Divergência: quando o bandit discordaria do router
            divergences = stats["divergences"]
            predicts    = stats["total_predicts"]
            div_pct     = round((divergences / predicts * 100) if predicts > 0 else 0, 1)

            # Reward médio do collector
            avg_reward = round(rl_stats.get("avg_reward", 0.0), 3) if rl_stats.get("total_events", 0) > 0 else 0.0

            # Top features aprendidas (só se tiver updates suficientes)
            features_section = ""
            if updates >= 10:
                try:
                    top = bandit.top_features_by_arm()
                    lines = []
                    for arm, feats in top.items():
                        top2 = ", ".join(f"{n}={v:+.2f}" for n, v in feats[:2])
                        lines.append(f"  <b>{arm}</b>: {top2}")
                    features_section = "\n\n<b>📐 Top features aprendidas:</b>\n" + "\n".join(lines)
                except Exception:
                    pass

            # Status de prontidão
            if stats["ready_for_active"]:
                status_line = "🟢 <b>PRONTO para modo ACTIVE</b> (A/B test 50%)"
            elif updates >= 50:
                status_line = f"🟡 Coletando ({pct}% — faltam {needed - updates} updates)"
            else:
                status_line = f"🔵 Fase inicial ({pct}% — faltam {needed - updates} updates)"

            msg = (
                f"<b>🤖 LinUCB Cascade Bandit</b>\n"
                f"Modo: <code>{stats['mode'].upper()}</code>\n\n"
                f"<b>📊 Progresso para A/B test:</b>\n"
                f"[{progress_bar}] {pct}% ({updates}/{needed} updates)\n"
                f"{status_line}\n\n"
                f"<b>🔍 Atividade:</b>\n"
                f"  Predições: {predicts}\n"
                f"  Divergências do router: {divergences} ({div_pct}%)\n"
                f"  Alpha (exploração): {stats['alpha']:.3f}\n"
                f"  Concorda com router: {stats['agreement_rate']:.0%}\n\n"
                f"<b>🎯 Updates por arm:</b>\n"
                f"  reflex:     {stats['updates_per_arm'].get('reflex', 0)}\n"
                f"  deliberate: {stats['updates_per_arm'].get('deliberate', 0)}\n"
                f"  deep:       {stats['updates_per_arm'].get('deep', 0)}\n\n"
                f"<b>💰 Reward médio:</b> {avg_reward:+.3f} "
                f"(eventos: {rl_stats.get('total_events', 0)})"
                f"{features_section}\n\n"
                f"<i>Shadow mode: o bandit aprende mas não interfere nas respostas ainda.</i>"
            )

            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[bandit] Erro ao gerar status: {e}", exc_info=True)
            await message.answer("❌ Erro ao gerar status do bandit", parse_mode=ParseMode.HTML)

    @dp.message(F.text == "/recovery")
    async def cmd_recovery(message: Message):
        """Status de recuperação de erros, circuit breakers e degradação"""
        if not _is_allowed(message, allowed_users):
            return
        try:
            report = pipeline.error_recovery.format_recovery_report()

            # Dividir em chunks se muito grande
            for part in split_message(report):
                await message.answer(part, parse_mode=ParseMode.HTML)
        except AttributeError as e:
            log.error(
                f"[recovery] Error recovery system not configured: {e}",
                exc_info=True,
                extra={"context": "recovery_status", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de recuperação não está disponível",
                parse_mode=ParseMode.HTML
            )
        except ValueError as e:
            log.error(
                f"[recovery] Invalid recovery data: {e}",
                exc_info=True,
                extra={"context": "recovery_status", "error_type": "ValueError"}
            )
            await message.answer(
                "❌ Erro ao formatar relatório de recuperação",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[recovery] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "recovery_status", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao recuperar status",
                parse_mode=ParseMode.HTML
            )

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
        except KeyError as e:
            log.error(f"[memory] Missing expected key in fact data: {e}", exc_info=True,
                      extra={"context": "memory_command", "error_type": "KeyError"})
            await message.answer("❌ Erro ao recuperar memória: estrutura de dados inválida")
        except (AttributeError, TypeError) as e:
            log.error(f"[memory] Memory service not properly configured: {e}", exc_info=True,
                      extra={"context": "memory_command", "error_type": type(e).__name__})
            await message.answer("❌ Sistema de memória não está disponível")
        except (OSError, IOError) as e:
            log.error(f"[memory] Database error: {e}", exc_info=True,
                      extra={"context": "memory_command", "error_type": type(e).__name__})
            await message.answer("❌ Erro ao acessar memória (problema com banco de dados)")
        except Exception as e:
            log.critical(f"[memory] Unexpected error: {e}", exc_info=True,
                         extra={"context": "memory_command", "error_type": type(e).__name__})
            await message.answer("❌ Erro inesperado ao recuperar memória")

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
        except KeyError as e:
            log.error(
                f"[decay] Missing stats key: {e}",
                exc_info=True,
                extra={"context": "decay_cleanup", "error_type": "KeyError"}
            )
            await message.answer(
                "❌ Erro: Estatísticas de decay incompletas"
            )
        except (RuntimeError, asyncio.TimeoutError) as e:
            log.error(
                f"[decay] Decay execution error: {e}",
                exc_info=True,
                extra={"context": "decay_cleanup", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao executar decay. Tente novamente."
            )
        except Exception as e:
            log.critical(
                f"[decay] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "decay_cleanup", "error_type": type(e).__name__}
            )
            await message.answer("❌ Erro inesperado ao executar decay")

    @dp.message(F.text == "/budget")
    async def cmd_budget(message: Message):
        """Mostra resumo de gastos do dia"""
        if not _is_allowed(message, allowed_users):
            return
        try:
            relatorio = pipeline.cost_tracker.formatar_relatorio_custos()
            await message.answer(relatorio, parse_mode=ParseMode.HTML)
        except AttributeError as e:
            log.error(
                f"[budget] Cost tracker not available: {e}",
                exc_info=True,
                extra={"context": "budget_report", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de custos não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[budget] Invalid cost data: {e}",
                exc_info=True,
                extra={"context": "budget_report", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao recuperar dados de custos",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[budget] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "budget_report", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao recuperar custos",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/budget_monthly")
    async def cmd_budget_monthly(message: Message):
        """Mostra resumo de gastos do mês"""
        if not _is_allowed(message, allowed_users):
            return
        try:
            resumo = pipeline.cost_tracker.obter_resumo_mensal()

            linhas = ["<b>Gastos - Resumo Mensal</b>\n"]
            linhas.append(f"Mes: {resumo['mes']}")
            linhas.append(f"Total: ${resumo['custo_total']:.2f}")
            linhas.append(f"Limite: ${resumo['limite']:.2f}")
            linhas.append(f"Porcentagem: {resumo['porcentagem_limite']:.0f}%\n")

            linhas.append("<b>Por Provedor:</b>")
            for prov, custo in sorted(
                resumo['provedores'].items(),
                key=lambda x: x[1],
                reverse=True
            ):
                if custo > 0:
                    linhas.append(f"  {prov}: ${custo:.4f}")

            await message.answer(
                "\n".join(linhas),
                parse_mode=ParseMode.HTML
            )
        except AttributeError as e:
            log.error(
                f"[budget_monthly] Cost tracker not available: {e}",
                exc_info=True,
                extra={"context": "budget_monthly", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de custos não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[budget_monthly] Invalid monthly data: {e}",
                exc_info=True,
                extra={"context": "budget_monthly", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao recuperar dados mensais",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[budget_monthly] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "budget_monthly", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao recuperar orçamento mensal",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/data_stats")
    async def cmd_data_stats(message: Message):
        """Mostra estatísticas do armazém de dados"""
        if not _is_allowed(message, allowed_users):
            return
        try:
            stats = await pipeline.data_store.estatisticas()

            linhas = ["<b>Armazem de Dados - Estatisticas</b>\n"]
            linhas.append(f"Total de fatos: {stats['total_fatos']}")
            linhas.append(f"Confianca media: {stats['confianca_media']:.2f}")
            linhas.append(f"Categorias: {len(stats['categorias'])}\n")

            linhas.append("<b>Por Categoria:</b>")
            for cat, qtd in stats['quantidade_por_categoria'].items():
                linhas.append(f"  {cat}: {qtd}")

            await message.answer(
                "\n".join(linhas),
                parse_mode=ParseMode.HTML
            )
        except AttributeError as e:
            log.error(
                f"[data_stats] Data store not available: {e}",
                exc_info=True,
                extra={"context": "data_stats", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de armazenamento não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, TypeError) as e:
            log.error(
                f"[data_stats] Invalid stats format: {e}",
                exc_info=True,
                extra={"context": "data_stats", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao recuperar estatísticas",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[data_stats] Data stats query timeout")
            await message.answer(
                "⏱️ Timeout ao recuperar estatísticas. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[data_stats] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "data_stats", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao recuperar estatísticas",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/data_clean")
    async def cmd_data_clean(message: Message):
        """Executa limpeza de dados antigos"""
        if not _is_allowed(message, allowed_users):
            return
        try:
            await message.answer("Executando limpeza de dados...")
            resultado = await pipeline.data_gerenciador.limpar_dados(simular=False)

            linhas = ["<b>Limpeza de Dados Concluida</b>\n"]
            linhas.append(f"Total deletado: {resultado['total_deletados']}")
            linhas.append(f"  Idade maxima: {resultado['por_motivo']['idade_maxima']}")
            linhas.append(f"  Confianca baixa: {resultado['por_motivo']['confianca_baixa']}")
            linhas.append(f"  Nunca utilizado: {resultado['por_motivo']['nunca_utilizado']}")

            await message.answer(
                "\n".join(linhas),
                parse_mode=ParseMode.HTML
            )
        except AttributeError as e:
            log.error(
                f"[data_clean] Data manager not available: {e}",
                exc_info=True,
                extra={"context": "data_cleanup", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de gerenciamento não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, TypeError) as e:
            log.error(
                f"[data_clean] Invalid cleanup result: {e}",
                exc_info=True,
                extra={"context": "data_cleanup", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao processar resultados da limpeza",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[data_clean] Data cleanup timeout")
            await message.answer(
                "⏱️ Limpeza de dados está demorando. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[data_clean] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "data_cleanup", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado na limpeza de dados",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/dashboard")
    async def cmd_dashboard(message: Message):
        """Mostra dashboard financeiro com status atual"""
        if not _is_allowed(message, allowed_users):
            return
        try:
            relatorio = await pipeline.analytics_reporter.gerar_relatorio_diario()
            await message.answer(relatorio.conteudo_html, parse_mode=ParseMode.HTML)
        except AttributeError as e:
            log.error(
                f"[dashboard] Analytics reporter not available: {e}",
                exc_info=True,
                extra={"context": "dashboard", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de análise não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (ValueError, KeyError) as e:
            log.error(
                f"[dashboard] Invalid report data: {e}",
                exc_info=True,
                extra={"context": "dashboard", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao gerar dashboard",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[dashboard] Dashboard generation timeout")
            await message.answer(
                "⏱️ Geração de dashboard está demorando. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[dashboard] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "dashboard", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao carregar dashboard",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/forecast")
    async def cmd_forecast(message: Message):
        """Mostra previsoes de custos para proximos 7 e 30 dias"""
        if not _is_allowed(message, allowed_users):
            return
        try:
            previsoes = await pipeline.analytics_forecaster.obter_resumo_previsoes()

            linhas = ["<b>Previsoes de Custos</b>\n"]
            linhas.append("<b>Proximos 7 Dias</b>")
            linhas.append(f"Total: ${previsoes['previsao_7d']['total']:.2f}")
            linhas.append(f"Media/Dia: ${previsoes['previsao_7d']['media_diaria']:.2f}")
            linhas.append(f"Range: ${previsoes['previsao_7d']['min']:.2f} - ${previsoes['previsao_7d']['max']:.2f}\n")

            linhas.append("<b>Proximos 30 Dias</b>")
            linhas.append(f"Total: ${previsoes['previsao_30d']['total']:.2f}")
            linhas.append(f"Media/Dia: ${previsoes['previsao_30d']['media_diaria']:.2f}")
            linhas.append(f"Range: ${previsoes['previsao_30d']['min']:.2f} - ${previsoes['previsao_30d']['max']:.2f}\n")

            if previsoes['data_alerta_mensal']:
                linhas.append("<b>Alerta de Limite</b>")
                linhas.append(f"Previsto para: {previsoes['data_alerta_mensal']}")
                linhas.append(f"Em {previsoes['dias_ate_alerta']} dias")

            await message.answer(
                "\n".join(linhas),
                parse_mode=ParseMode.HTML
            )
        except AttributeError as e:
            log.error(
                f"[forecast] Analytics forecaster not available: {e}",
                exc_info=True,
                extra={"context": "forecast", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de previsões não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError, TypeError) as e:
            log.error(
                f"[forecast] Invalid forecast data: {e}",
                exc_info=True,
                extra={"context": "forecast", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao calcular previsões",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[forecast] Forecast calculation timeout")
            await message.answer(
                "⏱️ Cálculo de previsões está demorando. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[forecast] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "forecast", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao calcular previsões",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/habits")
    async def cmd_habits(message: Message):
        if not _is_allowed(message, allowed_users):
            return
        afk = dp.get("afk_protocol")
        if afk and afk.habits:
            await message.answer(afk.habits.get_report(), parse_mode=ParseMode.HTML)
        else:
            await message.answer("Habit Tracker não inicializado.")

    @dp.message(F.text == "/watch")
    async def cmd_watch(message: Message):
        if not _is_allowed(message, allowed_users):
            return
        scheduler = dp.get("scheduler")
        if not scheduler:
            await message.answer("Scheduler não inicializado.")
            return
        # Procura o goal desktop_watch
        watch_goal = scheduler._goals.get("desktop_watch")
        if not watch_goal:
            await message.answer("Desktop Watch não está registrado.")
            return
        watch_goal.enable()
        await message.answer(
            "👁️ <b>Desktop Watch ATIVADO</b>\n\n"
            "Estou monitorando sua tela a cada 2 minutos.\n"
            "Você será notificado se algo precisar de atenção.\n\n"
            "<i>Use /watchoff para desativar.</i>",
            parse_mode=ParseMode.HTML,
        )

    @dp.message(F.text == "/watchoff")
    async def cmd_watchoff(message: Message):
        if not _is_allowed(message, allowed_users):
            return
        scheduler = dp.get("scheduler")
        if not scheduler:
            await message.answer("Scheduler não inicializado.")
            return
        watch_goal = scheduler._goals.get("desktop_watch")
        if not watch_goal:
            await message.answer("Desktop Watch não está registrado.")
            return
        scans = watch_goal._scans_total
        alerts = watch_goal._alerts_sent
        watch_goal.disable()
        await message.answer(
            "👁️ <b>Desktop Watch DESATIVADO</b>\n\n"
            f"Sessão: {scans} scans, {alerts} alertas.\n"
            "<i>Use /watch para reativar.</i>",
            parse_mode=ParseMode.HTML,
        )

    @dp.message(F.text == "/print")
    async def cmd_print(message: Message):
        if not _is_allowed(message, allowed_users):
            return
        status_msg = await message.answer("📸 Capturando tela...")
        try:
            from src.skills.vision.screenshot import capture_desktop
            from aiogram.types import BufferedInputFile
            
            screenshot_bytes = await capture_desktop()
            if not screenshot_bytes:
                await status_msg.edit_text("Falha ao capturar a tela.")
                return
                
            photo = BufferedInputFile(screenshot_bytes, filename="print.png")
            await message.bot.send_photo(
                chat_id=message.chat.id,
                photo=photo,
                caption="📸 Aqui está a sua tela atual."
            )
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(f"Erro no print: {e}")


    # ────────────────────────────────────────────────────────────────
    # Remote Executor Approval Callbacks (L0_MANUAL actions)
    # ────────────────────────────────────────────────────────────────

    @dp.callback_query(F.data.startswith("exec_approve:"))
    async def handle_executor_approve(callback: CallbackQuery):
        """Aprova uma ação L0_MANUAL do Remote Executor"""
        if not _is_allowed_callback(callback, allowed_users):
            return

        approval_id = callback.data.split(":", 1)[1]
        user_id = callback.from_user.id

        scheduler = dp.get("scheduler")
        if not scheduler:
            await callback.answer("❌ Scheduler não disponível", show_alert=True)
            return

        # Localiza o RemoteExecutor goal
        remote_executor_goal = scheduler._goals.get("remote_executor")
        if not remote_executor_goal:
            await callback.answer("❌ Remote Executor goal não encontrado", show_alert=True)
            return

        try:
            # Responde à aprovação
            afk_protocol = remote_executor_goal.afk_protocol
            approved = await afk_protocol.respond_to_approval(approval_id, approved=True)

            if approved:
                # Registrar métrica de aprovação
                tracker = getattr(pipeline, 'sprint11_tracker', None)
                if tracker:
                    tracker.record_remote_executor_approval(approved=True)

                await callback.message.edit_text(
                    f"{callback.message.text}\n\n<b>✅ Aprovado pelo usuário</b>\n"
                    "<i>Executando ação...</i>",
                    parse_mode=ParseMode.HTML
                )
                await callback.answer("✅ Ação aprovada e iniciada!")
            else:
                await callback.answer("⚠️ Aprovação não encontrada ou expirou", show_alert=True)
        except Exception as e:
            log.error(f"[executor_callback] Erro ao aprovar {approval_id}: {e}")
            await callback.answer(f"❌ Erro: {str(e)[:50]}", show_alert=True)

    @dp.callback_query(F.data.startswith("exec_reject:"))
    async def handle_executor_reject(callback: CallbackQuery):
        """Rejeita uma ação L0_MANUAL do Remote Executor"""
        if not _is_allowed_callback(callback, allowed_users):
            return

        approval_id = callback.data.split(":", 1)[1]
        user_id = callback.from_user.id

        scheduler = dp.get("scheduler")
        if not scheduler:
            await callback.answer("❌ Scheduler não disponível", show_alert=True)
            return

        # Localiza o RemoteExecutor goal
        remote_executor_goal = scheduler._goals.get("remote_executor")
        if not remote_executor_goal:
            await callback.answer("❌ Remote Executor goal não encontrado", show_alert=True)
            return

        try:
            # Responde à rejeição
            afk_protocol = remote_executor_goal.afk_protocol
            rejected = await afk_protocol.respond_to_approval(approval_id, approved=False)

            if rejected:
                # Registrar métrica de rejeição
                tracker = getattr(pipeline, 'sprint11_tracker', None)
                if tracker:
                    tracker.record_remote_executor_approval(approved=False)

                await callback.message.edit_text(
                    f"{callback.message.text}\n\n<b>❌ Rejeitado pelo usuário</b>",
                    parse_mode=ParseMode.HTML
                )
                await callback.answer("✅ Ação rejeitada")
            else:
                await callback.answer("⚠️ Rejeição não encontrada ou expirou", show_alert=True)
        except Exception as e:
            log.error(f"[executor_callback] Erro ao rejeitar {approval_id}: {e}")
            await callback.answer(f"❌ Erro: {str(e)[:50]}", show_alert=True)

    @dp.callback_query(F.data.startswith("vis_auth_"))
    async def handle_vision_auth(callback: CallbackQuery):
        # Example data: vis_auth_yes_2
        parts = callback.data.split("_")
        if len(parts) >= 3:
            result = parts[2] # "yes" or "no"
            tier = parts[3] if len(parts) > 3 else "2"
            
            # Buscando o AFK Protocol no Dispatcher (setado no start)
            afk_protocol = dp.get("afk_protocol")
            if afk_protocol:
                await afk_protocol.resolve_request(result, tier)
                
            await callback.message.edit_text(
                f"{callback.message.text}\n\n<b>➔ Resposta do Usuário: {'✅ Autorizado' if result == 'yes' else '❌ Negado'}</b>"
            )
        await callback.answer()

    # ────────────────────────────────────────────────────────
    # Scheduler Conversacional Commands
    # ────────────────────────────────────────────────────────

    @dp.message(F.text == "/agendar")
    async def cmd_agendar(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        try:
            # Encontra o goal scheduler_conversacional
            scheduler_goal = None
            if hasattr(pipeline, '_goals'):
                for goal in pipeline._goals:
                    if hasattr(goal, 'name') and goal.name == 'scheduler_conversacional':
                        scheduler_goal = goal
                        break

            if not scheduler_goal:
                await message.answer(
                    "❌ Scheduler não está ativo.\n"
                    "Execute `/saude` para verificar o status dos goals.",
                    parse_mode=ParseMode.HTML
                )
                return

            # Obtém SchedulerTelegramInterface
            from src.skills.scheduler_conversacional.telegram_interface import SchedulerTelegramInterface
            if not hasattr(scheduler_goal, 'store') or scheduler_goal.store is None:
                # Initialize store if needed
                from src.skills.scheduler_conversacional.store import SchedulerStore
                scheduler_goal.store = SchedulerStore(pipeline.memory._db)
                await scheduler_goal.store.init()

            scheduler_ui = SchedulerTelegramInterface(scheduler_goal.store)
            chat_id = message.chat.id
            user_id = str(message.from_user.id)

            msg = await scheduler_ui.cmd_agendar(chat_id, user_id)
            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[scheduler] Erro em /agendar: {e}", exc_info=True)
            await message.answer(
                f"❌ Erro ao iniciar scheduler: <code>{str(e)[:100]}</code>",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/listar")
    async def cmd_listar(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        try:
            from src.skills.scheduler_conversacional.telegram_interface import SchedulerTelegramInterface
            from src.skills.scheduler_conversacional.store import SchedulerStore

            # Inicializa store
            store = SchedulerStore(pipeline.memory._db)
            await store.init()
            scheduler_ui = SchedulerTelegramInterface(store)

            chat_id = message.chat.id
            msg = await scheduler_ui.cmd_listar(chat_id)
            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[scheduler] Erro em /listar: {e}", exc_info=True)
            await message.answer(f"❌ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/detalhe "))
    async def cmd_detalhe(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        try:
            task_id = message.text.split(" ", 1)[1].strip()

            from src.skills.scheduler_conversacional.telegram_interface import SchedulerTelegramInterface
            from src.skills.scheduler_conversacional.store import SchedulerStore

            store = SchedulerStore(pipeline.memory._db)
            await store.init()
            scheduler_ui = SchedulerTelegramInterface(store)

            chat_id = message.chat.id
            msg = await scheduler_ui.cmd_detalhe(chat_id, task_id)
            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[scheduler] Erro em /detalhe: {e}", exc_info=True)
            await message.answer(f"❌ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/pausar "))
    async def cmd_pausar(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        try:
            task_id = message.text.split(" ", 1)[1].strip()

            from src.skills.scheduler_conversacional.telegram_interface import SchedulerTelegramInterface
            from src.skills.scheduler_conversacional.store import SchedulerStore

            store = SchedulerStore(pipeline.memory._db)
            await store.init()
            scheduler_ui = SchedulerTelegramInterface(store)

            chat_id = message.chat.id
            msg = await scheduler_ui.cmd_pausar(chat_id, task_id)
            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[scheduler] Erro em /pausar: {e}", exc_info=True)
            await message.answer(f"❌ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/reativar "))
    async def cmd_reativar(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        try:
            task_id = message.text.split(" ", 1)[1].strip()

            from src.skills.scheduler_conversacional.telegram_interface import SchedulerTelegramInterface
            from src.skills.scheduler_conversacional.store import SchedulerStore

            store = SchedulerStore(pipeline.memory._db)
            await store.init()
            scheduler_ui = SchedulerTelegramInterface(store)

            chat_id = message.chat.id
            msg = await scheduler_ui.cmd_reativar(chat_id, task_id)
            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[scheduler] Erro em /reativar: {e}", exc_info=True)
            await message.answer(f"❌ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/remover "))
    async def cmd_remover(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        try:
            task_id = message.text.split(" ", 1)[1].strip()

            from src.skills.scheduler_conversacional.telegram_interface import SchedulerTelegramInterface
            from src.skills.scheduler_conversacional.store import SchedulerStore

            store = SchedulerStore(pipeline.memory._db)
            await store.init()
            scheduler_ui = SchedulerTelegramInterface(store)

            chat_id = message.chat.id
            msg = await scheduler_ui.cmd_remover(chat_id, task_id)
            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[scheduler] Erro em /remover: {e}", exc_info=True)
            await message.answer(f"❌ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/executar "))
    async def cmd_executar(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        try:
            task_id = message.text.split(" ", 1)[1].strip()

            from src.skills.scheduler_conversacional.telegram_interface import SchedulerTelegramInterface
            from src.skills.scheduler_conversacional.store import SchedulerStore
            from src.skills.scheduler_conversacional.dispatcher import TaskDispatcher

            store = SchedulerStore(pipeline.memory._db)
            await store.init()
            scheduler_ui = SchedulerTelegramInterface(store)
            dispatcher = TaskDispatcher(store, pipeline.cascade_adapter)

            chat_id = message.chat.id

            # Executa tarefa
            task = await store.get_task(task_id)
            if not task:
                await message.answer(f"❌ Tarefa não encontrada: {task_id}", parse_mode=ParseMode.HTML)
                return

            await message.answer(f"⏱️ Executando {task.title}...", parse_mode=ParseMode.HTML)
            result = await dispatcher._execute_task(task)

            if result.get("success"):
                msg = f"✅ <b>{task.title}</b> executada com sucesso\n\n" \
                      f"ID Execução: <code>{result.get('execution_id', 'N/A')[:12]}</code>\n" \
                      f"Status: {result.get('status', 'success')}"
            else:
                msg = f"❌ <b>{task.title}</b> falhou\n\n" \
                      f"Erro: {result.get('error', 'Desconhecido')[:100]}"

            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[scheduler] Erro em /executar: {e}", exc_info=True)
            await message.answer(f"❌ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    # ────────────────────────────────────────────────────────
    # Bug Analyzer Commands
    # ────────────────────────────────────────────────────────

    @dp.message(F.text == "/bug")
    async def cmd_bug(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        try:
            from src.skills.bug_analyzer import BugAnalyzer, BugAnalyzerTelegramInterface

            # Inicializa analisador
            bug_analyzer = BugAnalyzer(pipeline.cascade_adapter, pipeline.model_router)
            bug_ui = BugAnalyzerTelegramInterface(bug_analyzer)

            chat_id = message.chat.id
            user_id = str(message.from_user.id)

            msg = await bug_ui.cmd_bug(chat_id, user_id)
            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[bug_analyzer] Erro em /bug: {e}", exc_info=True)
            await message.answer(
                f"❌ Erro ao iniciar bug analyzer: <code>{str(e)[:100]}</code>",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/bug_cancel")
    async def cmd_bug_cancel(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        try:
            from src.skills.bug_analyzer import BugAnalyzer, BugAnalyzerTelegramInterface

            bug_analyzer = BugAnalyzer(pipeline.cascade_adapter, pipeline.model_router)
            bug_ui = BugAnalyzerTelegramInterface(bug_analyzer)

            chat_id = message.chat.id
            msg = await bug_ui.cmd_bug_cancel(chat_id)
            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[bug_analyzer] Erro em /bug_cancel: {e}", exc_info=True)
            await message.answer(f"❌ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    @dp.message(F.text == "/bug_approve")
    async def cmd_bug_approve(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        try:
            from src.skills.bug_analyzer import BugAnalyzer, BugAnalyzerTelegramInterface

            bug_analyzer = BugAnalyzer(pipeline.cascade_adapter, pipeline.model_router)
            bug_ui = BugAnalyzerTelegramInterface(bug_analyzer)

            chat_id = message.chat.id
            msg = await bug_ui.cmd_bug_approve(chat_id)
            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[bug_analyzer] Erro em /bug_approve: {e}", exc_info=True)
            await message.answer(f"❌ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/obsidian"))
    async def cmd_obsidian(message: Message):
        """Handler para links ou texto direto via /obsidian"""
        if not _is_allowed(message, allowed_users):
            return
            
        args = message.text.replace("/obsidian", "").strip()
        if not args:
            await message.reply("📝 **Uso do /obsidian**\n\n- `/obsidian <url>` (YouTube ou Site)\n- Envie um **print** com `/obsidian` na legenda\n- Envie um **áudio** com `/obsidian` na legenda")
            return
            
        # Verifica se é URL
        url_match = re.search(r"https?://[^\s]+", args)
        if url_match:
            url = url_match.group(0)
            status_msg = await message.answer(f"⏳ Processando link: {url}...")
            
            if "youtube.com" in url or "youtu.be" in url:
                resp = await vault.process_youtube(url, user_hint=args.replace(url, "").strip())
            else:
                resp = await vault.process_site(url, user_hint=args.replace(url, "").strip())
                
            await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
        else:
            # Texto direto (opcional, mas vamos focar em links e mídia primeiro)
            await message.reply("Por favor, forneça um link do YouTube ou de um site.")

    @dp.message(F.text.startswith("/cofre"))
    async def cmd_cofre_search(message: Message):
        """Pesquisa direta no cofre"""
        if not _is_allowed(message, allowed_users):
            return
            
        query = message.text.replace("/cofre", "").strip()
        if not query:
            await message.reply("Digite o que deseja buscar no cofre. Ex: `/cofre fine-tuning`")
            return
            
        searcher = VaultSearcher()
        results = searcher.search(query, max_results=5)
        
        if not results:
            await message.reply(f"🔍 Nenhuma nota encontrada para: *{query}*", parse_mode=ParseMode.MARKDOWN)
            return
            
        text = [f"🔍 **Resultados no Cofre para: {query}**\n"]
        for note in results:
            text.append(f"📄 **{note.title}**")
            text.append(f"🏷️ {', '.join([f'#{t}' for t in note.tags])}")
            text.append(f"🔗 {note.path.name}\n")
            
        await message.answer("\n".join(text), parse_mode=ParseMode.MARKDOWN)

    @dp.message(F.photo)
    async def handle_vault_photo(message: Message):
        """Handler de fotos com debouncer para media groups"""
        if not _is_allowed(message, allowed_users):
            return
            
        caption = message.caption or ""
        # Verifica se é para o obsidian
        is_obsidian = "/obsidian" in caption.lower()
        if not is_obsidian and message.reply_to_message:
            is_obsidian = message.reply_to_message.text and "/obsidian" in message.reply_to_message.text.lower()
            
        if not is_obsidian:
            return # Ignora fotos normais
            
        # Lógica de Debouncer para Media Groups
        mg_id = message.media_group_id
        if mg_id:
            if mg_id not in dp["vault_debouncer"]:
                dp["vault_debouncer"][mg_id] = []
                # Agenda o processamento do grupo
                asyncio.create_task(process_photo_group(mg_id, message, caption))
            
            # Adiciona a foto ao grupo
            file_info = await message.bot.get_file(message.photo[-1].file_id)
            photo_file = await message.bot.download_file(file_info.file_path)
            dp["vault_debouncer"][mg_id].append(photo_file.read())
        else:
            # Foto única
            status_msg = await message.answer("⏳ Lendo print e salvando no Obsidian...")
            file_info = await message.bot.get_file(message.photo[-1].file_id)
            photo_file = await message.bot.download_file(file_info.file_path)
            resp = await vault.process_images([photo_file.read()], user_hint=caption.replace("/obsidian", ""))
            await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)

    async def process_photo_group(mg_id: str, message: Message, caption: str):
        """Aguarde 1.5s para agrupar todas as fotos do media group"""
        await asyncio.sleep(1.5)
        photos = dp["vault_debouncer"].pop(mg_id, [])
        if not photos:
            return
            
        status_msg = await message.answer(f"⏳ Processando {len(photos)} prints no Obsidian...")
        resp = await vault.process_images(photos, user_hint=caption.replace("/obsidian", ""))
        await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)

    @dp.message(F.voice | F.audio)
    async def handle_audio(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        file_id = message.voice.file_id if message.voice else message.audio.file_id
        file_info = await message.bot.get_file(file_id)
        
        # Avisar que está ouvindo
        await message.bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)
        
        # Download do Telegram
        audio_file = await message.bot.download_file(file_info.file_path)
        audio_bytes = audio_file.read()
        
        from src.skills.stt_groq import transcribe_audio_groq
        user_input = await transcribe_audio_groq(audio_bytes)
        
        if not user_input:
            await message.reply("❌ Falha ao transcrever o áudio. (Verifique a GROQ_API_KEY).")
            return
            
        caption = (message.caption or "").lower()
        if "/obsidian" in caption:
            status_msg = await message.reply("⏳ Analisando áudio e enviando ao Obsidian...")
            resp = await vault.process_audio(audio_bytes, user_hint=caption.replace("/obsidian", ""))
            await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
            return

        await message.reply(f"🎤 <i>Transcrição recebida:</i>\n\n\"{user_input}\"", parse_mode=ParseMode.HTML)
        await _process_and_reply(message, user_input, pipeline, dp)

    @dp.message(F.text)
    async def handle_message(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        user_input = message.text.strip()
        if not user_input:
            return

        await _process_and_reply(message, user_input, pipeline, dp)

    async def _process_and_reply(message: Message, user_input: str, pipeline: SeekerPipeline, dp: Dispatcher) -> None:

        # Check for active bug analyzer wizard
        try:
            from src.skills.bug_analyzer import BugAnalyzer, BugAnalyzerTelegramInterface

            bug_analyzer = BugAnalyzer(pipeline.cascade_adapter, pipeline.model_router)
            bug_ui = BugAnalyzerTelegramInterface(bug_analyzer)

            if bug_ui.is_in_wizard(message.chat.id):
                # Bug wizard ativo — processar input no wizard
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
                # Wizard ativo — processar input no wizard
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
                                    f"✅ Tarefa <b>{last_task.title}</b> agendada!\n"
                                    f"Próxima execução: {last_task.next_run_at.strftime('%d/%m %H:%M')}" if last_task.next_run_at else "em breve",
                                    parse_mode=ParseMode.HTML
                                )
                    return
        except Exception as e:
            log.debug(f"[wizard] Erro ao verificar wizard: {e}")
            # Continua com processamento normal

        # God mode check
        god_users: set = dp.get("god_mode_users", set())
        if message.from_user.id in god_users:
            user_input = f"god mode — {user_input}"
            god_users.discard(message.from_user.id)
            dp["god_mode_users"] = god_users

        # Session ID baseado no chat (suporta múltiplos chats futuramente)
        session_id = f"telegram:{message.chat.id}"

        # ── RL: envia feedback da resposta anterior ao Reward Collector ──
        # A mensagem atual DO Victor é o sinal comportamental da resposta anterior.
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
                # Fecha o evento após receber o feedback
                pipeline.reward_collector.close_event(_last_rl["decision_id"])
            except Exception:
                pass  # RL nunca deve quebrar o fluxo principal

        # OODA Loop for structured decision-making
        ooda_loop = dp.get("ooda_loop")

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(
            keep_typing(message.bot, message.chat.id, stop_typing)
        )

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
                CognitiveDepth.REFLEX: "⚡",
                CognitiveDepth.DELIBERATE: "🧠",
                CognitiveDepth.DEEP: "🔬",
            }.get(result.depth, "")
            if "god" in result.routing_reason.lower():
                badge = "🔴 GOD MODE"

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
            
            for part in split_message(response_text):
                    try:
                        await message.answer(part, parse_mode=ParseMode.HTML)
                    except Exception:
                        await message.answer(html.escape(part)[:MAX_MSG_LENGTH])

            # ── RL: guarda decision_id para o próximo feedback ────────
            dp[f"rl_last_{message.chat.id}"] = {
                "decision_id": result.decision_id,
                "response_ts": time.time(),
            }

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


def _is_allowed_callback(query: CallbackQuery, allowed_users: set[int]) -> bool:
    if not allowed_users:
        return True
    if query.from_user and query.from_user.id in allowed_users:
        return True
    return False


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
