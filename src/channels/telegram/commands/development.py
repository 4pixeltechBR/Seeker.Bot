import logging
import os
from aiogram import Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.telegram.development")

def setup_development_handlers(dp: Dispatcher, pipeline: SeekerPipeline, _bug_context):
    @dp.message(F.text == "/git_backup")
    async def cmd_git_backup(message: Message):

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

    @dp.message(F.text == "/bug")
    async def cmd_bug(message: Message):

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
