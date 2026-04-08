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
from aiogram.types import Message, CallbackQuery, BotCommand, BufferedInputFile
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

# Goal Engine
from src.core.goals import GoalScheduler, GoalNotifier, discover_goals
from src.channels.email.client import EmailClient
from src.skills.sense_news.prompts import NICHES

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
        BotCommand(command="/memory", description="Fatos aprendidos na sessão"),
        BotCommand(command="/god", description="Arma God Mode para a próxima mensagem"),
        BotCommand(command="/search", description="Busca direta e forçada na web"),
        BotCommand(command="/rate", description="Exibe status dos rate limiters"),
        BotCommand(command="/decay", description="Roda limpeza de confiança manual"),
        BotCommand(command="/habits", description="Padrões de decisão aprendidos"),
        BotCommand(command="/print", description="Screenshot rápido da tela sem analise"),
        BotCommand(command="/watch", description="Ativa vigilância de tela (modo AFK)"),
        BotCommand(command="/watchoff", description="Desativa vigilância de tela"),
        BotCommand(command="/scout", description="Dispara campanha B2B Scout (leads qualificados)"),
        BotCommand(command="/crm", description="Lista histórico de leads qualificados"),
        BotCommand(command="/configure_news", description="Personaliza nichos do SenseNews")
    ]
    await bot.set_my_commands(commands)


def setup_handlers(dp: Dispatcher, pipeline: SeekerPipeline, allowed_users: set[int]):

    @dp.message(F.text == "/start")
    async def cmd_start(message: Message):
        if not _is_allowed(message, allowed_users):
            return

        user_id = message.from_user.id
        user_niches = await pipeline.memory.get_user_niches(user_id)

        # Mensagem inicial comum
        help_text = (
            "<b>Seeker.Bot, seu agente inteligente.</b>\n\n"
            "Manda qualquer mensagem que eu decido a profundidade.\n"
            "⚡ <i>reflex</i> · 🧠 <i>deliberate</i> · 🔬 <i>deep</i>\n\n"
            "<b>Operação:</b>\n"
            "/god — força análise profunda na próxima\n"
            "/search [query] — busca direta na web\n"
            "/print — screenshot rápido do desktop\n"
            "/watch — ativa vigilância AFK (2 min)\n"
            "/watchoff — desativa vigilância\n\n"
            "<b>Sistema:</b>\n"
            "/status — painel de performance e metas\n"
            "/saude — dashboard detalhado de saúde dos goals\n"
            "/memory — o que eu aprendi sobre você\n"
            "/rate — status dos limites de API\n"
            "/habits — padrões de decisão aprendidos\n"
            "/decay — limpeza manual de memória\n"
            "/configure_news — personaliza notícias do SenseNews"
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
        except Exception as e:
            await message.answer(f"❌ Erro na busca: {e}")
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

        except Exception as e:
            log.error(f"[scout] Erro ao disparar campanha: {e}", exc_info=True)
            await message.answer(
                f"❌ Erro ao executar Scout: <code>{str(e)[:100]}</code>",
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

        except Exception as e:
            await message.answer(f"❌ Erro ao carregar dashboard: {str(e)[:100]}", parse_mode=ParseMode.HTML)

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
                afk_protocol.resolve_request(result, tier)
                
            await callback.message.edit_text(
                f"{callback.message.text}\n\n<b>➔ Resposta do Usuário: {'✅ Autorizado' if result == 'yes' else '❌ Negado'}</b>"
            )
        await callback.answer()

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

        # God mode check
        god_users: set = dp.get("god_mode_users", set())
        if message.from_user.id in god_users:
            user_input = f"god mode — {user_input}"
            god_users.discard(message.from_user.id)
            dp["god_mode_users"] = god_users

        # Session ID baseado no chat (suporta múltiplos chats futuramente)
        session_id = f"telegram:{message.chat.id}"

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

    # ── Init bot ──────────────────────────────────────────
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # ── Init OODA Loop (for structured decision-making + auditability) ──
    dp["ooda_loop"] = OODALoop()

    await setup_commands(bot)
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
    scheduler = GoalScheduler(notifier, memory=pipeline.memory)
    dp["scheduler"] = scheduler

    try:
        deny_list = {
            g.strip().lower()
            for g in os.getenv("GOAL_DENY_LIST", "").split(",")
            if g.strip()
        }
        goals = discover_goals(pipeline, deny_list=deny_list)
        for goal in goals:
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

    try:
        await dp.start_polling(bot)
    finally:
        # Cleanup Goal Engine
        scheduler = dp.get("scheduler")
        if scheduler:
            await scheduler.stop()

        # Cleanup: pipeline (cancela decay, aguarda tasks, fecha memória)
        await pipeline.close()
        await cleanup_client_pool()
        log.info("Shutdown completo")


if __name__ == "__main__":
    asyncio.run(main())
