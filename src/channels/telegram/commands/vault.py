import logging
import re

from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from src.core.pipeline import SeekerPipeline
from src.skills.knowledge_vault import VaultSearcher

log = logging.getLogger("seeker.telegram.vault")

def setup_vault_handlers(dp: Dispatcher, pipeline: SeekerPipeline, vault, _obsidian_wait_users):
    @dp.callback_query(F.data == "vault_sync_now")
    async def cb_vault_sync(query: CallbackQuery):
        """Dispara sincronizacao manual com Obsidian apos confirmacao"""

        await query.answer("Sincronizando com Obsidian...")

        try:
            if pipeline.obsidian_exporter:
                await pipeline.obsidian_exporter.sync_all()
                await query.message.edit_reply_markup(reply_markup=None)
                await query.message.reply("Conhecimento exportado para o Obsidian com sucesso!")
            else:
                await query.answer("Obsidian Exporter nao configurado.", show_alert=True)
        except Exception as e:
            log.error(f"[obsidian] Erro no sync manual: {e}")
            await query.answer(f"Erro no sync: {e}", show_alert=True)

    @dp.message(F.text.startswith("/obsidian"))
    async def cmd_obsidian(message: Message):
        """Handler para /obsidian - salva texto, links ou midia no Cofre."""

        args = message.text.replace("/obsidian", "").strip()

        if not args:
            _obsidian_wait_users.add(message.from_user.id)

            await message.reply(
                "<b>Modo Cofre Ativado!</b>\n\n"
                "Envie a proxima mensagem para salvar no Obsidian. Pode ser:\n"
                "- Audio (sera salvo como Ideia)\n"
                "- Print/Foto (com extracao OCR)\n"
                "- Link do YouTube ou site\n"
                "- Texto livre\n\n"
                "<i>(Para cancelar, envie /cancelar)</i>",
                parse_mode=ParseMode.HTML
            )
            return

        url_match = re.search(r"https?://[^\s]+", args)
        if url_match:
            url = url_match.group(0)
            status_msg = await message.answer(f"Processando link: {url}...")

            try:
                if "youtube.com" in url or "youtu.be" in url:
                    resp = await vault.process_youtube(url, user_hint=args.replace(url, "").strip())
                else:
                    resp = await vault.process_site(url, user_hint=args.replace(url, "").strip())

                await status_msg.edit_text(resp, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                log.error(f"[obsidian] Erro ao processar URL: {e}", exc_info=True)
                await status_msg.edit_text(f"Erro ao processar link: {e}")
        else:
            status_msg = await message.answer("Salvando nota no Cofre...")
            try:
                resp = await vault.process_text(args)
                await status_msg.edit_text(resp, parse_mode=ParseMode.HTML)
            except Exception as e:
                log.error(f"[obsidian] Erro ao salvar texto: {e}", exc_info=True)
                await status_msg.edit_text(f"Erro ao salvar nota: {e}")


    @dp.message(F.text.startswith("/cofre"))
    async def cmd_cofre_search(message: Message):
        """Pesquisa direta no cofre"""

        query = message.text.replace("/cofre", "").strip()
        if not query:
            await message.reply("Digite o que deseja buscar no cofre. Ex: `/cofre fine-tuning`")
            return

        searcher = VaultSearcher()
        results = searcher.search(query, max_results=5)

        if not results:
            await message.reply(f"Nenhuma nota encontrada para: *{query}*", parse_mode=ParseMode.MARKDOWN)
            return

        text = [f"**Resultados no Cofre para: {query}**\n"]
        for note in results:
            text.append(f"**{note.title}**")
            text.append(f"{', '.join([f'#{t}' for t in note.tags])}")
            text.append(f"{note.path.name}\n")

        await message.answer("\n".join(text), parse_mode=ParseMode.MARKDOWN)
