import logging
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
import html
import uuid
from src.core.pipeline import SeekerPipeline
from src.core.goals.manager import parse_time_for_scheduler

log = logging.getLogger("seeker.telegram.tasks")

def setup_tasks_handlers(dp: Dispatcher, pipeline: SeekerPipeline):
    @dp.callback_query(F.data.startswith("exec_approve:"))
    async def handle_executor_approve(callback: CallbackQuery):
        """Aprova uma aÃ§Ã£o L0_MANUAL do Remote Executor"""

        approval_id = callback.data.split(":", 1)[1]
        user_id = callback.from_user.id

        scheduler = dp.get("scheduler")
        if not scheduler:
            await callback.answer("âŒ Scheduler nÃ£o disponÃ­vel", show_alert=True)
            return

        # Localiza o RemoteExecutor goal
        remote_executor_goal = scheduler._goals.get("remote_executor")
        if not remote_executor_goal:
            await callback.answer("âŒ Remote Executor goal nÃ£o encontrado", show_alert=True)
            return

        try:
            # Responde Ã  aprovaÃ§Ã£o
            afk_protocol = remote_executor_goal.afk_protocol
            approved = await afk_protocol.respond_to_approval(approval_id, approved=True)

            if approved:
                # Registrar mÃ©trica de aprovaÃ§Ã£o
                tracker = getattr(pipeline, 'sprint11_tracker', None)
                if tracker:
                    tracker.record_remote_executor_approval(approved=True)

                await callback.message.edit_text(
                    f"{callback.message.text}\n\n<b>âœ… Aprovado pelo usuÃ¡rio</b>\n"
                    "<i>Executando aÃ§Ã£o...</i>",
                    parse_mode=ParseMode.HTML
                )
                await callback.answer("âœ… AÃ§Ã£o aprovada e iniciada!")
            else:
                await callback.answer("âš ï¸ AprovaÃ§Ã£o nÃ£o encontrada ou expirou", show_alert=True)
        except Exception as e:
            log.error(f"[executor_callback] Erro ao aprovar {approval_id}: {e}")
            await callback.answer(f"âŒ Erro: {str(e)[:50]}", show_alert=True)

    @dp.callback_query(F.data.startswith("exec_reject:"))
    async def handle_executor_reject(callback: CallbackQuery):
        """Rejeita uma aÃ§Ã£o L0_MANUAL do Remote Executor"""

        approval_id = callback.data.split(":", 1)[1]
        user_id = callback.from_user.id

        scheduler = dp.get("scheduler")
        if not scheduler:
            await callback.answer("âŒ Scheduler nÃ£o disponÃ­vel", show_alert=True)
            return

        # Localiza o RemoteExecutor goal
        remote_executor_goal = scheduler._goals.get("remote_executor")
        if not remote_executor_goal:
            await callback.answer("âŒ Remote Executor goal nÃ£o encontrado", show_alert=True)
            return

        try:
            # Responde Ã  rejeiÃ§Ã£o
            afk_protocol = remote_executor_goal.afk_protocol
            rejected = await afk_protocol.respond_to_approval(approval_id, approved=False)

            if rejected:
                # Registrar mÃ©trica de rejeiÃ§Ã£o
                tracker = getattr(pipeline, 'sprint11_tracker', None)
                if tracker:
                    tracker.record_remote_executor_approval(approved=False)

                await callback.message.edit_text(
                    f"{callback.message.text}\n\n<b>âŒ Rejeitado pelo usuÃ¡rio</b>",
                    parse_mode=ParseMode.HTML
                )
                await callback.answer("âœ… AÃ§Ã£o rejeitada")
            else:
                await callback.answer("âš ï¸ RejeiÃ§Ã£o nÃ£o encontrada ou expirou", show_alert=True)
        except Exception as e:
            log.error(f"[executor_callback] Erro ao rejeitar {approval_id}: {e}")
            await callback.answer(f"âŒ Erro: {str(e)[:50]}", show_alert=True)

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # S.A.R.A Approval Callbacks (ApprovalEngine â€” Day 5)
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @dp.callback_query(F.data.startswith("sara_approve:"))
    async def handle_sara_approve(callback: CallbackQuery):
        """Aplica o patch S.A.R.A aprovado pelo usuÃ¡rio."""
        try:
            pending_id = int(callback.data.split(":", 1)[1])
        except (ValueError, IndexError):
            await callback.answer("Formato de callback invÃ¡lido", show_alert=True)
            return

        try:
            from src.skills.self_improvement.error_database import get_pending_store
            import shutil, os

            store = get_pending_store()
            patch = await store.approve(pending_id)

            if patch is None:
                await callback.answer("Patch jÃ¡ resolvido ou expirou (>24h)", show_alert=True)
                await callback.message.edit_reply_markup(reply_markup=None)
                return

            file_path = patch["file_path"]
            new_code = patch["proposed_code"]
            rationale = patch["rationale"]
            filename = os.path.basename(file_path)

            # Verifica se o arquivo ainda existe
            if not os.path.exists(file_path):
                await callback.answer(f"Arquivo nÃ£o encontrado: {filename}", show_alert=True)
                return

            # Backup + Overwrite
            backup_path = f"{file_path}.bak"
            shutil.copy2(file_path, backup_path)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_code)

            log.info(f"[sara_approve] Patch {pending_id} aplicado em {filename} pelo usuario")

            await callback.answer("Patch aplicado com sucesso!")
            await callback.message.edit_text(
                f"ðŸ›¡ï¸ <b>S.A.R.A â€” PATCH APLICADO</b>\n\n"
                f"ðŸ“„ <b>Arquivo:</b> {filename}\n"
                f"ðŸ§  <b>Motivo:</b> {rationale}\n"
                f"<i>Backup salvo em .bak</i>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            log.error(f"[sara_approve] Erro ao aplicar patch {pending_id}: {e}", exc_info=True)
            await callback.answer(f"Erro ao aplicar: {str(e)[:80]}", show_alert=True)

    @dp.callback_query(F.data.startswith("sara_reject:"))
    async def handle_sara_reject(callback: CallbackQuery):
        """Rejeita o patch S.A.R.A â€” arquivo original preservado."""
        try:
            pending_id = int(callback.data.split(":", 1)[1])
        except (ValueError, IndexError):
            await callback.answer("Formato de callback invÃ¡lido", show_alert=True)
            return

        try:
            from src.skills.self_improvement.error_database import get_pending_store

            store = get_pending_store()
            rejected = await store.reject(pending_id)

            if not rejected:
                await callback.answer("Patch jÃ¡ resolvido ou expirou (>24h)", show_alert=True)
                await callback.message.edit_reply_markup(reply_markup=None)
                return

            log.info(f"[sara_reject] Patch {pending_id} rejeitado pelo usuario")
            await callback.answer("Patch rejeitado â€” arquivo preservado")
            await callback.message.edit_text(
                f"ðŸ›¡ï¸ <b>S.A.R.A â€” PATCH REJEITADO</b>\n\n"
                f"O arquivo original foi preservado.\n"
                f"<i>RevisÃ£o manual necessÃ¡ria quando conveniente.</i>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            log.error(f"[sara_reject] Erro ao rejeitar patch {pending_id}: {e}", exc_info=True)
            await callback.answer(f"Erro: {str(e)[:80]}", show_alert=True)

    @dp.message(F.text == "/agendar")
    async def cmd_agendar(message: Message):

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
                    "âŒ Scheduler nÃ£o estÃ¡ ativo.\n"
                    "Execute `/saude` para verificar o status dos goals.",
                    parse_mode=ParseMode.HTML
                )
                return

            # ObtÃ©m SchedulerTelegramInterface
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
                f"âŒ Erro ao iniciar scheduler: <code>{str(e)[:100]}</code>",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/listar")
    async def cmd_listar(message: Message):

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
            await message.answer(f"âŒ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/detalhe "))
    async def cmd_detalhe(message: Message):

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
            await message.answer(f"âŒ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/pausar "))
    async def cmd_pausar(message: Message):

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
            await message.answer(f"âŒ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/reativar "))
    async def cmd_reativar(message: Message):

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
            await message.answer(f"âŒ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/remover "))
    async def cmd_remover(message: Message):

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
            await message.answer(f"âŒ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/executar "))
    async def cmd_executar(message: Message):

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
                await message.answer(f"âŒ Tarefa nÃ£o encontrada: {task_id}", parse_mode=ParseMode.HTML)
                return

            await message.answer(f"â±ï¸ Executando {task.title}...", parse_mode=ParseMode.HTML)
            result = await dispatcher._execute_task(task)

            if result.get("success"):
                msg = f"âœ… <b>{task.title}</b> executada com sucesso\n\n" \
                      f"ID ExecuÃ§Ã£o: <code>{result.get('execution_id', 'N/A')[:12]}</code>\n" \
                      f"Status: {result.get('status', 'success')}"
            else:
                msg = f"âŒ <b>{task.title}</b> falhou\n\n" \
                      f"Erro: {result.get('error', 'Desconhecido')[:100]}"

            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[scheduler] Erro em /executar: {e}", exc_info=True)
            await message.answer(f"âŒ Erro: {str(e)[:100]}", parse_mode=ParseMode.HTML)

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Bug Analyzer Commands
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

