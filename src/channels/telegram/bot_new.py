"""
Seeker.Bot — Telegram Bot
src/channels/telegram/bot.py

Executar: python -m src
"""

import asyncio
import logging
import os
import html

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, BotCommand
from aiogram.enums import ParseMode, ChatAction
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from src.core.pipeline import SeekerPipeline, PipelineResult
from src.core.logging_secure import setup_secure_logging

# Goal Engine
from src.skills.sense_news.prompts import NICHES
from src.skills.sherlock_news.targets_manager import (
    add_target,
    list_targets,
)  # SherlockNews

# Knowledge Vault (Obsidian)
from src.skills.knowledge_vault import KnowledgeVault

# Setup secure logging (masks secrets automatically)
setup_secure_logging()
log = logging.getLogger("seeker.telegram")

MAX_MSG_LENGTH = 4096
TYPING_INTERVAL = 4


def _is_allowed(message: Message, allowed_users: set[int]) -> bool:
    if not message.from_user:
        return False
    return message.from_user.id in allowed_users


def _is_allowed_callback(query: CallbackQuery, allowed_users: set[int]) -> bool:
    if not query.from_user:
        return False
    return query.from_user.id in allowed_users


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
        BotCommand(
            command="/status", description="Painel de providers, memória e metas"
        ),
        BotCommand(
            command="/saude", description="Dashboard de saúde dos goals (detalhado)"
        ),
        BotCommand(command="/perf", description="Dashboard de performance e latência"),
        BotCommand(
            command="/perf_detailed", description="Métricas detalhadas por fase"
        ),
        BotCommand(
            command="/cascade_status",
            description="Status detalhado da API Cascade (6 tiers)",
        ),
        BotCommand(
            command="/recovery", description="Status de circuit breakers e degradação"
        ),
        BotCommand(command="/memory", description="Fatos aprendidos na sessão"),
        BotCommand(command="/god", description="Arma God Mode para a próxima mensagem"),
        BotCommand(command="/search", description="Busca direta e forçada na web"),
        BotCommand(command="/rate", description="Exibe status dos rate limiters"),
        BotCommand(command="/decay", description="Roda limpeza de confiança manual"),
        BotCommand(command="/budget", description="Gastos de hoje por provedor"),
        BotCommand(command="/budget_monthly", description="Gastos do mês por provedor"),
        BotCommand(
            command="/data_stats", description="Estatisticas do armazem de dados"
        ),
        BotCommand(
            command="/data_clean", description="Executa limpeza de dados antigos"
        ),
        BotCommand(
            command="/dashboard", description="Dashboard financeiro com status atual"
        ),
        BotCommand(
            command="/forecast",
            description="Previsoes de custos para proximos 7 e 30 dias",
        ),
        BotCommand(command="/habits", description="Padrões de decisão aprendidos"),
        BotCommand(
            command="/print", description="Screenshot rápido da tela sem analise"
        ),
        BotCommand(command="/watch", description="Ativa vigilância de tela (modo AFK)"),
        BotCommand(command="/watchoff", description="Desativa vigilância de tela"),
        BotCommand(
            command="/scout",
            description="Dispara campanha B2B Scout (leads qualificados)",
        ),
        BotCommand(
            command="/git_backup",
            description="Faz backup manual do código no GitHub privado",
        ),
        BotCommand(command="/crm", description="Lista histórico de leads qualificados"),
        BotCommand(
            command="/configure_news", description="Personaliza nichos do SenseNews"
        ),
        BotCommand(
            command="/agendar",
            description="📅 Agenda nova tarefa (wizard conversacional)",
        ),
        BotCommand(command="/listar", description="📋 Lista tarefas agendadas do chat"),
        BotCommand(
            command="/detalhe", description="🔍 Ver detalhes de tarefa (/detalhe <ID>)"
        ),
        BotCommand(command="/pausar", description="⏸ Pausa tarefa (/pausar <ID>)"),
        BotCommand(
            command="/reativar", description="▶️ Reativa tarefa (/reativar <ID>)"
        ),
        BotCommand(command="/remover", description="🗑 Remove tarefa (/remover <ID>)"),
        BotCommand(
            command="/executar", description="⚡ Executa tarefa agora (/executar <ID>)"
        ),
        BotCommand(
            command="/bug", description="🐛 Analisa bug com contexto e sugestões"
        ),
        BotCommand(
            command="/bug_approve", description="✅ Aprova e aplica correções sugeridas"
        ),
        BotCommand(command="/bug_cancel", description="❌ Cancela análise de bug"),
        BotCommand(
            command="/sherlock",
            description="🕵️ SherlockNews: Painel Interativo de Monitoramento IA",
        ),
        BotCommand(
            command="/obsidian", description="📝 Salva conteúdo no cofre do Obsidian"
        ),
        BotCommand(command="/cofre", description="🔍 Pesquisa no cofre do Obsidian"),
    ]
    await bot.set_my_commands(commands)


def setup_handlers(dp: Dispatcher, pipeline: SeekerPipeline, allowed_users: set[int]):

    # Adiciona dependências no dispatcher
    dp["pipeline"] = pipeline
    dp["allowed_users"] = allowed_users

    from src.channels.telegram.commands.sherlock import sherlock_router

    dp.include_router(sherlock_router)

    # Initialize Knowledge Vault com VLM + WebSearcher para enriquecimento
    from src.skills.vision.vlm_client import VLMClient
    from src.core.search.web import WebSearcher

    vlm = VLMClient()
    web_searcher = WebSearcher(
        tavily_key=os.getenv("TAVILY_API_KEY", ""),
        brave_key=os.getenv("BRAVE_API_KEY", ""),
    )
    KnowledgeVault(pipeline.cascade_adapter, vlm_client=vlm, web_searcher=web_searcher)
    dp["vault_debouncer"] = {}  # Para agrupamento de mídias

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
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"✓ {niche}", callback_data=f"niche_toggle:{niche}"
                    )
                ]
            )

        # Botão "Confirmar"
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ Confirmar Seleção", callback_data="niches_done"
                )
            ]
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await message.answer(
            "<b>📰 Personalize seu SenseNews</b>\n\n"
            "Escolha quais nichos de notícias te interessam:\n\n"
            "<i>Clique para selecionar/desselecionar, depois confirme.</i>",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
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
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{check} {n}", callback_data=f"niche_toggle:{n}"
                    )
                ]
            )

        # Botão "Confirmar"
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ Confirmar Seleção", callback_data="niches_done"
                )
            ]
        )

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
                parse_mode=ParseMode.HTML,
            )
            # Limpa seleção temporária
            if user_id in niche_selection:
                del niche_selection[user_id]
        else:
            await query.answer(
                "Erro ao salvar preferências. Tente novamente.", show_alert=True
            )

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
                    f'<b>{r.position}.</b> <a href="{r.url}">'
                    f"{html.escape(r.title[:60])}</a>\n"
                    f"  <i>{html.escape(r.snippet[:150])}</i>\n"
                )
            await message.answer(
                "\n".join(lines),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except (AttributeError, TypeError) as e:
            log.error(
                f"[search] Searcher not properly configured: {e}",
                exc_info=True,
                extra={"context": "search_command", "error_type": type(e).__name__},
            )
            await message.answer("❌ Serviço de busca não está disponível")
        except ValueError as e:
            log.error(
                f"[search] Invalid search query: {e}",
                exc_info=True,
                extra={"context": "search_command", "error_type": "ValueError"},
            )
            await message.answer("❌ Erro na busca: consulta inválida")
        except asyncio.TimeoutError:
            log.warning("[search] Search operation timeout")
            await message.answer(
                "⏱️ Timeout na busca (>30s). Tente novamente com uma query mais simples."
            )
        except (RuntimeError, OSError) as e:
            log.error(
                f"[search] Search service error: {e}",
                exc_info=True,
                extra={"context": "search_command", "error_type": type(e).__name__},
            )
            await message.answer(f"❌ Erro na busca: {str(e)[:100]}")
        except Exception as e:
            log.critical(
                f"[search] Unexpected error in search: {e}",
                exc_info=True,
                extra={"context": "search_command", "error_type": type(e).__name__},
            )
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
        if not _is_allowed(message, allowed_users):
            return

        await message.answer(
            "🧪 Disparando teste do Email Monitor...", parse_mode=ParseMode.HTML
        )

        try:
            # Estratégia de busca: pipeline → scheduler → fallback
            email_goal = None

            # 1. Tenta em pipeline._goals (setado no startup)
            if hasattr(pipeline, "_goals") and pipeline._goals:
                for goal in pipeline._goals:
                    if hasattr(goal, "name") and goal.name == "email_monitor":
                        email_goal = goal
                        log.debug("[telegram] Email goal encontrado em pipeline._goals")
                        break

            # 2. Fallback: tenta em scheduler._goals
            if not email_goal:
                scheduler = dp.get("scheduler")
                if scheduler and hasattr(scheduler, "_goals"):
                    for goal in scheduler._goals:
                        if hasattr(goal, "name") and goal.name == "email_monitor":
                            email_goal = goal
                            log.debug(
                                "[telegram] Email goal encontrado em scheduler._goals"
                            )
                            break

            # 3. Último fallback: tenta pipeline._scheduler
            if not email_goal and hasattr(pipeline, "_scheduler"):
                scheduler = pipeline._scheduler
                if scheduler and hasattr(scheduler, "_goals"):
                    for goal in scheduler._goals:
                        if hasattr(goal, "name") and goal.name == "email_monitor":
                            email_goal = goal
                            log.debug(
                                "[telegram] Email goal encontrado em pipeline._scheduler"
                            )
                            break

            if not email_goal:
                # Debug: lista o que encontrou
                goals_available = []
                if hasattr(pipeline, "_goals"):
                    goals_available = [
                        g.name for g in pipeline._goals if hasattr(g, "name")
                    ]

                await message.answer(
                    f"❌ Email Monitor não encontrado.\n"
                    f"Goals disponíveis: {', '.join(goals_available) if goals_available else 'nenhum'}\n"
                    f"Execute `/saude` para verificar.",
                    parse_mode=ParseMode.HTML,
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
                extra={"context": "email_test", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro: Email Monitor não está configurado corretamente. Execute `/saude` para mais detalhes.",
                parse_mode=ParseMode.HTML,
            )
        except asyncio.TimeoutError:
            log.warning("[email_test] Timeout ao executar email monitor (>30s)")
            await message.answer(
                "⏱️ Timeout: o Email Monitor demorou muito tempo para responder.",
                parse_mode=ParseMode.HTML,
            )
        except (RuntimeError, ValueError) as e:
            # Erro de execução: problema na lógica do goal
            log.error(
                f"[email_test] Erro de execução: {e}",
                exc_info=True,
                extra={"context": "email_test", "error_type": type(e).__name__},
            )
            await message.answer(
                f"❌ Erro ao executar Email Monitor: {str(e)[:100]}",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            # Catch-all para exceções inesperadas
            log.critical(
                f"[email_test] Erro inesperado: {e}",
                exc_info=True,
                extra={"context": "email_test", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro ao executar Email Monitor", parse_mode=ParseMode.HTML
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
                await message.answer(
                    "🕵️ SherlockNews: Nenhum modelo sendo monitorado no momento.\nUse <code>/sherlock <nome></code> para adicionar.",
                    parse_mode=ParseMode.HTML,
                )
            else:
                targets_str = "\n".join([f"• <code>{t}</code>" for t in targets])
                await message.answer(
                    f"🕵️ <b>SherlockNews: Alvos Ativos</b>\n\n{targets_str}\n\n<i>Eu verifico o status deles todo dia às 08:00.</i>",
                    parse_mode=ParseMode.HTML,
                )
            return

        # Adiciona novo alvo
        if add_target(args):
            await message.answer(
                f"🕵️ <b>SherlockNews: Alvo Adicionado!</b>\n\nModelo: <code>{args}</code>\n<i>Vou te avisar assim que detectar o lançamento oficial.</i>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.answer("❌ Erro ao adicionar modelo ao SherlockNews.")
