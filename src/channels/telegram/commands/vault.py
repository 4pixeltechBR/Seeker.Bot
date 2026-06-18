import logging
import re
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.telegram.vault")


def setup_vault_handlers(
    dp: Dispatcher, pipeline: SeekerPipeline, vault, _obsidian_wait_users
):
    @dp.callback_query(F.data == "vault_sync_now")
    async def cb_vault_sync(query: CallbackQuery):
        """Dispara sincronização manual com Obsidian após confirmação"""

        await query.answer("🔄 Sincronizando com Obsidian...")

        try:
            if pipeline.obsidian_exporter:
                await pipeline.obsidian_exporter.sync_all()
                await query.message.edit_reply_markup(reply_markup=None)  # Remove botão
                await query.message.reply(
                    "✅ Conhecimento exportado para o Obsidian com sucesso!"
                )
            else:
                await query.answer(
                    "❌ Obsidian Exporter não configurado.", show_alert=True
                )
        except Exception as e:
            log.error(f"[obsidian] Erro no sync manual: {e}")
            await query.answer(f"❌ Erro no sync: {e}", show_alert=True)

    @dp.message(F.text.startswith("/obsidian"))
    async def cmd_obsidian(message: Message):
        """Handler para /obsidian — salva texto, links ou mídia no Cofre."""

        args = message.text.replace("/obsidian", "").strip()

        # Inicia estado de aguardo para a próxima mensagem
        if not args:
            _obsidian_wait_users.add(message.from_user.id)

            await message.reply(
                "📝 <b>Modo Cofre Ativado!</b>\n\n"
                "Envie a próxima mensagem para salvar no Obsidian. Pode ser:\n"
                "• 🎙️ Áudio (será salvo como Ideia)\n"
                "• 📷 Print/Foto (com extração OCR)\n"
                "• 📄 PDF/Documento\n"
                "• 🔗 Link do YouTube, site ou repositório GitHub\n"
                "• 📝 Texto livre\n\n"
                "<i>(Para cancelar, envie /cancelar)</i>",
                parse_mode=ParseMode.HTML,
            )
            return

        # Verifica se é URL
        url_match = re.search(r"https?://[^\s]+", args)
        if url_match:
            url = url_match.group(0)
            status_msg = await message.answer(f"⏳ Processando link: {url}...")

            try:
                resp = await vault.process_url(
                    url, user_hint=args.replace(url, "").strip()
                )
                await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                log.error(f"[obsidian] Erro ao processar URL: {e}", exc_info=True)
                await status_msg.edit_text(f"❌ Erro ao processar link: {e}")
        else:
            # Texto direto → salva como nota no cofre via facade
            status_msg = await message.answer("📝 Salvando nota no Cofre...")
            try:
                resp = await vault.process_text(args)
                await status_msg.edit_text(resp, parse_mode=ParseMode.HTML)
            except Exception as e:
                log.error(f"[obsidian] Erro ao salvar texto: {e}", exc_info=True)
                await status_msg.edit_text(f"❌ Erro ao salvar nota: {e}")

    @dp.message(F.text.startswith("/cofre"))
    async def cmd_cofre_search(message: Message):
        """Pesquisa semântica no cofre com resposta sintetizada por LLM"""

        query = message.text.replace("/cofre", "").strip()
        if not query:
            await message.reply(
                "Digite o que deseja buscar no cofre. Ex: `/cofre fine-tuning`"
            )
            return

        status_msg = await message.answer(f"🔍 Buscando no cofre: *{query}*...", parse_mode=ParseMode.MARKDOWN)

        try:
            resp = await vault.search_and_answer(query, max_results=5)
            await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            log.error(f"[cofre] Erro na busca: {e}", exc_info=True)
            await status_msg.edit_text(f"❌ Erro ao buscar no cofre: {str(e)[:100]}")

    # Closure-scoped set para evitar bugs de dp["key"] no Aiogram 3.x
    # O dp.__getitem__ usa workflow_data e é incompatível com o in operator
    _obsidian_wait_users: set = set()

    def _check_obsidian_state(user_id: int) -> bool:
        """Verifica e limpa o estado de aguardo do obsidian para o usuário."""
        if user_id in _obsidian_wait_users:
            _obsidian_wait_users.discard(user_id)
            return True
        return False
