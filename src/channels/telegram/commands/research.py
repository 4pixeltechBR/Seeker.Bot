"""
Telegram handler — comando /research (research_machine skill) + /research_schedule
"""
import asyncio
import logging
import re
from datetime import datetime, time

from aiogram import Dispatcher, F
from aiogram.enums import ParseMode

from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.telegram.research")


SCHEDULE_PATTERN = re.compile(
    r'^/research_schedule\s+"(?P<schedule>.+?)"\s+(?P<query>.+)$'
)


def setup_research_handlers(dp: Dispatcher, pipeline: SeekerPipeline):

    @dp.message(F.text.startswith("/research_schedule"))
    async def cmd_research_schedule(message):
        """Agenda pesquisa recorrente via scheduler_conversacional.

        /research_schedule "<every day 8am>" "Claude 4.5 release"
        /research_schedule "<every monday 9am>" "agentes autônomos"
        /research_schedule list
        /research_schedule cancel <job_id>
        """
        text = (message.text or "").strip()
        
        if text == "/research_schedule list":
            await _list_scheduled(message, pipeline)
            return
        
        if text.startswith("/research_schedule cancel "):
            job_id = text.split(maxsplit=2)[2]
            await _cancel_scheduled(message, pipeline, job_id)
            return
        
        # Parse: /research_schedule "<schedule>" "query"
        m = SCHEDULE_PATTERN.match(text)
        if not m:
            await message.reply(
                "🔬 <b>Research Scheduler</b>\n\n"
                "Uso:\n"
                '• <code>/research_schedule "<cron/every>" "<query>"</code>\n'
                '• <code>/research_schedule list</code>\n'
                '• <code>/research_schedule cancel <job_id></code>\n\n'
                "Exemplos de schedule:\n"
                '• <code>"every day 8am"</code>\n'
                '• <code>"every monday 9am"</code>\n'
                '• <code>"0 8 * * 1-5"</code> (cron: seg-sex 8h)\n'
                '• <code>"every 6h"</code>',
                parse_mode=ParseMode.HTML,
            )
            return
        
        schedule = m.group("schedule")
        query = m.group("query")
        
        await _schedule_research(message, pipeline, schedule, query)

    @dp.message(F.text.startswith("/research"))
    async def cmd_research(message):
        """Dispara a máquina de pesquisa.

        /research <query>          → pesquisa completa (YouTube + NotebookLM + Obsidian)
        /research status <run_id>  → status de uma pesquisa em andamento
        """
        text = (message.text or "").strip()
        parts = text.split(maxsplit=2)

        if len(parts) < 2:
            await message.reply(
                "🔬 <b>Research Machine</b>\n\n"
                "Uso: <code>/research <query></code>\n\n"
                "Exemplos:\n"
                "• <code>/research Claude 4.5 release notes</code>\n"
                "• <code>/research agentes autônomos 2026</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        # Subcomando status
        if parts[1].lower() == "status":
            run_id = parts[2] if len(parts) > 2 else ""
            if not run_id:
                await message.reply("Use: /research status <run_id>")
                return
            await _show_status(message, run_id)
            return

        query = " ".join(parts[1:]).strip()
        if not query:
            await message.reply("Query vazia. Use: /research <query>")
            return

        await _run_research(message, pipeline, query)

    async def _schedule_research(message, pipeline: SeekerPipeline, schedule: str, query: str):
        """Agenda pesquisa recorrente usando SchedulerStore real."""
        from src.skills.scheduler_conversacional.store import SchedulerStore
        from src.skills.scheduler_conversacional.calculator import NextRunCalculator
        from src.skills.research_machine.scheduler import parse_schedule, build_scheduled_task

        spec = parse_schedule(schedule)
        if not spec.ok:
            await message.reply(
                f"❌ <b>Schedule inválido</b>\n\n{spec.error}",
                parse_mode=ParseMode.HTML,
            )
            return

        try:
            db = pipeline.memory._db
            store = SchedulerStore(db)
            await store.init()

            task = build_scheduled_task(
                spec,
                query,
                chat_id=message.chat.id,
                user_id=str(message.from_user.id) if message.from_user else "telegram",
            )
            await store.create_task(task)
        except Exception as e:
            log.error(f"[research_schedule] Falha ao agendar: {e}", exc_info=True)
            await message.reply(f"❌ Erro ao agendar: {e}")
            return

        next_run_str = (
            task.next_run_at.strftime("%d/%m/%Y %H:%M UTC") if task.next_run_at else "—"
        )
        await message.reply(
            f"⏰ <b>Pesquisa agendada</b>\n\n"
            f"<b>Query:</b> {query}\n"
            f"<b>Schedule:</b> {spec.description}\n"
            f"<b>Próxima execução:</b> {next_run_str}\n"
            f"<b>Job ID:</b> <code>{task.id}</code>\n\n"
            f"Gerenciar: <code>/research_schedule list</code>\n"
            f"Cancelar: <code>/research_schedule cancel {task.id}</code>\n\n"
            f"<i>Quando disparar, o scheduler vai me notificar aqui.</i>",
            parse_mode=ParseMode.HTML,
        )

    async def _list_scheduled(message, pipeline: SeekerPipeline):
        """Lista pesquisas agendadas do chat atual."""
        from src.skills.scheduler_conversacional.store import SchedulerStore

        try:
            db = pipeline.memory._db
            store = SchedulerStore(db)
            await store.init()
            tasks = await store.list_tasks(message.chat.id)
        except Exception as e:
            log.error(f"[research_schedule] list falhou: {e}", exc_info=True)
            await message.reply(f"❌ Erro ao listar: {e}")
            return

        research_tasks = [
            t for t in tasks if (t.instruction_text or "").startswith("[research_machine]")
        ]

        if not research_tasks:
            await message.reply("📭 Nenhuma pesquisa agendada neste chat.")
            return

        lines = ["⏰ <b>Pesquisas Agendadas</b>\n"]
        for t in research_tasks:
            query = (t.instruction_text or "").replace("[research_machine]", "", 1).strip()
            next_run = (
                t.next_run_at.strftime("%d/%m %H:%M UTC") if t.next_run_at else "—"
            )
            status_icon = "🟢" if t.is_enabled else "⏸️"
            type_str = (
                f"diário {t.hour:02d}:{t.minute:02d}" if t.schedule_type == "daily"
                else f"semanal dia {t.day_of_week} {t.hour:02d}:{t.minute:02d}"
                if t.schedule_type == "weekly"
                else t.schedule_type
            )
            lines.append(
                f"{status_icon} <code>{t.id}</code>\n"
                f"   Query: <i>{query[:50]}</i>\n"
                f"   {type_str} · próxima: {next_run}"
            )

        await message.reply("\n\n".join(lines), parse_mode=ParseMode.HTML)

    async def _cancel_scheduled(message, pipeline: SeekerPipeline, job_id: str):
        """Cancela (deleta) uma pesquisa agendada."""
        from src.skills.scheduler_conversacional.store import SchedulerStore

        try:
            db = pipeline.memory._db
            store = SchedulerStore(db)
            await store.init()

            existing = await store.get_task(job_id)
            if not existing:
                await message.reply(f"❌ Job <code>{job_id}</code> não encontrado.")
                return
            if not (existing.instruction_text or "").startswith("[research_machine]"):
                await message.reply(
                    f"⚠️ <code>{job_id}</code> não é uma pesquisa agendada (é de outra skill).",
                    parse_mode=ParseMode.HTML,
                )
                return

            await store.delete_task(job_id)
            await message.reply(f"✅ Job <code>{job_id}</code> cancelado.", parse_mode=ParseMode.HTML)
        except Exception as e:
            log.error(f"[research_schedule] cancel falhou: {e}", exc_info=True)
            await message.reply(f"❌ Erro ao cancelar: {e}")

    # ... resto do código (cmd_research, _run_research, _show_status) mantido igual

    async def _run_research(message, pipeline: SeekerPipeline, query: str):
        from src.skills.research_machine.pipeline import ResearchPipeline

        await message.reply(
            f"🔬 <b>Pesquisa iniciada</b>\n\n"
            f"<b>Query:</b> {query}\n"
            f"<i>YouTube → NotebookLM → Síntese → Obsidian</i>\n\n"
            f"⏳ Aguarde... (geralmente 1-3 min)",
            parse_mode=ParseMode.HTML,
        )

        rp = ResearchPipeline(pipeline)

        # Roda em background — não bloqueia o bot
        async def _bg():
            try:
                result = await rp.research(query=query)
                if "error" in result:
                    await message.reply(f"❌ Erro: {result['error']}")
                    return

                run_id = result.get("run_id", "")
                n_videos = len(result.get("videos", []))
                cost = result.get("cost_usd", 0.0)
                dur = result.get("duration_s", 0.0)
                obs = result.get("obsidian_path", "")
                nb_url = result.get("notebook_url", "")

                lines = [
                    f"✅ <b>Pesquisa concluída</b>",
                    f"",
                    f"<b>Query:</b> {query}",
                    f"<b>Vídeos analisados:</b> {n_videos}",
                    f"<b>Custo:</b> ${cost:.4f}",
                    f"<b>Duração:</b> {dur:.1f}s",
                    f"<b>Run ID:</b> <code>{run_id}</code>",
                ]
                if obs:
                    lines.append(f"\n📝 <b>Obsidian:</b> <code>{obs}</code>")
                if nb_url:
                    lines.append(f"📓 <b>NotebookLM:</b> {nb_url}")
                lines.append(f"\nVer status: /research status {run_id}")

                await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)
            except Exception as e:
                log.error(f"[research] bg falhou: {e}", exc_info=True)
                await message.reply(f"❌ Erro: {e}")

        asyncio.create_task(_bg())

    async def _show_status(message, run_id: str):
        from src.skills.research_machine import store as rm_store
        data = rm_store.load_run(run_id)
        if not data:
            await message.reply(f"❌ Run {run_id} não encontrada.")
            return

        status = data.get("status", "unknown")
        n_videos = len(data.get("videos", []))
        cost = data.get("cost_usd", 0.0)
        dur = data.get("duration_s", 0.0)

        lines = [
            f"🔬 <b>Status: {run_id}</b>",
            f"",
            f"<b>Status:</b> {status}",
            f"<b>Query:</b> {data.get('query', '')}",
            f"<b>Vídeos:</b> {n_videos}",
            f"<b>Custo:</b> ${cost:.4f}",
            f"<b>Duração:</b> {dur:.1f}s",
        ]
        if data.get("obsidian_path"):
            lines.append(f"📝 <code>{data['obsidian_path']}</code>")
        if data.get("notebook_url"):
            lines.append(f"📓 {data['notebook_url']}")

        await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)