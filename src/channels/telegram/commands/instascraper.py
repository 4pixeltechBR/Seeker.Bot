import html
import logging
import asyncio
from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ParseMode

from src.core.pipeline import SeekerPipeline
from src.skills.instascraper.insta_scraper import InstaScraper
from src.skills.instascraper.goal import TARGETS_FILE

log = logging.getLogger("seeker.telegram.instascraper")

instascraper_router = Router()
instascraper_states = {}


def get_instascraper_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="📋 Listar Alvos", callback_data="insta_list")],
        [
            InlineKeyboardButton(text="➕ Adicionar Perfil", callback_data="insta_add"),
            InlineKeyboardButton(text="❌ Remover Perfil", callback_data="insta_remove_menu"),
        ],
        [InlineKeyboardButton(text="🚀 Executar Pendentes", callback_data="insta_force")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def load_raw_targets() -> list[dict]:
    import json
    import os
    if not os.path.exists(TARGETS_FILE):
        return []
    try:
        with open(TARGETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_raw_targets(targets: list[dict]):
    import json
    try:
        with open(TARGETS_FILE, "w", encoding="utf-8") as f:
            json.dump(targets, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.error(f"Erro ao salvar targets: {e}")


@instascraper_router.message(F.text.startswith("/instascraper"))
async def cmd_instascraper(message: Message):
    args = message.text.split()
    if len(args) > 1:
        # Execução direta: /instascraper <perfil> [limite]
        target_profile = args[1].strip().replace("@", "")
        limit = 5
        if len(args) > 2:
            try:
                limit = int(args[2])
            except ValueError:
                pass

        status_msg = await message.answer(
            f"⏳ <b>Iniciando InstaScraper para @{target_profile}...</b>\n"
            f"• Limite de posts: {limit}\n"
            f"• Delay Anti-Ban ativo (10-15s entre mídias).\n\n"
            f"<i>Esta operação roda de forma segura no background. Aguarde o relatório...</i>",
            parse_mode=ParseMode.HTML
        )

        async def run_scraping():
            try:
                scraper = InstaScraper()
                loop = asyncio.get_running_loop()
                # Roda a raspagem síncrona em executor para não travar o polling do bot
                result = await loop.run_in_executor(
                    None, scraper.raspar_perfil, target_profile, limit
                )

                if "Sucesso" in result:
                    await status_msg.edit_text(
                        f"✅ <b>InstaScraper concluído com sucesso!</b>\n\n"
                        f"• Perfil: @{target_profile}\n"
                        f"• Mídias locais salvas na pasta de Downloads.\n"
                        f"• Notas Markdown geradas na Inbox do Obsidian.\n\n"
                        f"<i>Detalhe: {result}</i>",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await status_msg.edit_text(
                        f"❌ <b>Falha na execução do InstaScraper</b>\n\n"
                        f"• Perfil: @{target_profile}\n"
                        f"• Detalhe: {result}",
                        parse_mode=ParseMode.HTML
                    )
            except Exception as ex:
                log.error(f"Erro na raspagem direta: {ex}", exc_info=True)
                await status_msg.edit_text(f"❌ Erro crítico no InstaScraper: {ex}")

        # Dispara em background
        asyncio.create_task(run_scraping())

    else:
        # Exibe o Painel
        await message.answer(
            "📸 <b>InstaScraper: Soberania Local & Obsidian</b>\n\n"
            "Escolha uma opção no painel abaixo:",
            reply_markup=get_instascraper_keyboard(),
            parse_mode=ParseMode.HTML,
        )


@instascraper_router.message(
    lambda message: (
        message.from_user.id in instascraper_states
        and instascraper_states[message.from_user.id].get("step") == "waiting_username"
    )
)
async def intercept_insta_add(message: Message):
    user_input = message.text.strip().replace("@", "")
    user_id = message.from_user.id

    targets = load_raw_targets()
    # Evita duplicações
    if any(t["name"].lower() == user_input.lower() for t in targets):
        await message.answer(
            f"⚠️ O perfil <b>@{user_input}</b> já está na lista de monitoramento.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_instascraper_keyboard()
        )
        del instascraper_states[user_id]
        return

    targets.append({
        "name": user_input,
        "status": "pending",
        "limit": 5
    })
    save_raw_targets(targets)
    del instascraper_states[user_id]

    await message.answer(
        f"✅ Perfil <b>@{user_input}</b> adicionado à lista com status <code>pending</code> (limite: 5 posts).",
        parse_mode=ParseMode.HTML,
        reply_markup=get_instascraper_keyboard()
    )


@instascraper_router.callback_query(F.data.startswith("insta_"))
async def instascraper_callbacks(callback: CallbackQuery, pipeline: SeekerPipeline):
    action = callback.data.split("insta_")[1]
    user_id = callback.from_user.id

    if action == "list":
        targets = load_raw_targets()
        if not targets:
            await callback.message.edit_text(
                "Nenhum perfil cadastrado na lista.",
                reply_markup=get_instascraper_keyboard()
            )
            return

        lines = ["📸 <b>Instagram Alvos Monitorados:</b>\n"]
        for t in targets:
            status_emoji = "⏳" if t.get("status") == "pending" else "✅"
            lines.append(
                f"{status_emoji} <b>@{html.escape(t.get('name', ''))}</b> "
                f"<i>(status: {t.get('status')}, limite: {t.get('limit', 5)})</i>"
            )

        await callback.message.edit_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=get_instascraper_keyboard(),
        )

    elif action == "add":
        instascraper_states[user_id] = {"step": "waiting_username"}
        await callback.message.answer(
            "Digite o username do perfil do Instagram que deseja adicionar:"
        )
        await callback.answer()

    elif action == "remove_menu":
        targets = load_raw_targets()
        if not targets:
            await callback.answer("Nenhum perfil para remover.")
            return

        keyboard = []
        for t in targets:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"❌ @{t.get('name')}",
                    callback_data=f"insta_del_{t.get('name')}"
                )
            ])
        keyboard.append([InlineKeyboardButton(text="⬅️ Voltar", callback_data="insta_back")])

        await callback.message.edit_text(
            "Selecione o perfil que deseja remover:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await callback.answer()

    elif action.startswith("del_"):
        target_name = action.split("del_")[1]
        targets = load_raw_targets()
        new_targets = [t for t in targets if t.get("name") != target_name]
        save_raw_targets(new_targets)

        await callback.answer(f"@{target_name} removido.")
        await callback.message.edit_text(
            "📸 <b>InstaScraper: Soberania Local & Obsidian</b>\n\n"
            "Escolha uma opção no painel abaixo:",
            reply_markup=get_instascraper_keyboard(),
            parse_mode=ParseMode.HTML,
        )

    elif action == "back":
        await callback.message.edit_text(
            "📸 <b>InstaScraper: Soberania Local & Obsidian</b>\n\n"
            "Escolha uma opção no painel abaixo:",
            reply_markup=get_instascraper_keyboard(),
            parse_mode=ParseMode.HTML,
        )

    elif action == "force":
        await callback.answer("Iniciando varredura...")
        status_msg = await callback.message.answer(
            "⏳ <b>Processando perfis pendentes do InstaScraper...</b>",
            parse_mode=ParseMode.HTML
        )

        async def run_sync():
            try:
                from src.skills.instascraper.goal import InstaScraperGoal
                goal = InstaScraperGoal(pipeline)
                res = await goal.run_cycle()
                
                msg = f"📝 <b>Resultado do Ciclo:</b>\n{res.summary}"
                if res.notification:
                    msg += f"\n\n{res.notification}"
                await status_msg.edit_text(msg, parse_mode=ParseMode.HTML)
            except Exception as e:
                log.error(f"Erro na raspagem forçada: {e}", exc_info=True)
                await status_msg.edit_text(f"❌ Erro na varredura: {e}")

        asyncio.create_task(run_sync())
