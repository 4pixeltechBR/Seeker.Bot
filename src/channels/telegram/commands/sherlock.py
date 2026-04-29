import html
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from src.core.pipeline import SeekerPipeline
from src.skills.sherlock_news.targets_manager import add_target, list_all_targets, remove_target

log = logging.getLogger("seeker.telegram.sherlock")

sherlock_router = Router()

# Dicionario de estados globais de sherlock movido para memoria de modulo
sherlock_states = {}

def get_sherlock_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="Listar Alvos", callback_data="sherlock_list")],
        [InlineKeyboardButton(text="Adicionar Modelo", callback_data="sherlock_add"),
         InlineKeyboardButton(text="Remover", callback_data="sherlock_remove_menu")],
        [InlineKeyboardButton(text="Forcar Busca Agora", callback_data="sherlock_force")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_category_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="LLM", callback_data="sherlock_cat_LLM"),
         InlineKeyboardButton(text="Voz (TTS)", callback_data="sherlock_cat_Voice")],
        [InlineKeyboardButton(text="Imagem", callback_data="sherlock_cat_Image"),
         InlineKeyboardButton(text="Video", callback_data="sherlock_cat_Video")],
        [InlineKeyboardButton(text="Ferramenta", callback_data="sherlock_cat_Tool"),
         InlineKeyboardButton(text="Agente", callback_data="sherlock_cat_Agent")],
        [InlineKeyboardButton(text="AI Generica", callback_data="sherlock_cat_AI")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@sherlock_router.message(F.text == "/sherlock")
async def cmd_sherlock(message: Message):
    await message.answer(
        "<b>SherlockNews: Painel de Monitoramento</b>\n\nEscolha uma opcao abaixo:",
        reply_markup=get_sherlock_keyboard(),
        parse_mode=ParseMode.HTML
    )

@sherlock_router.message(lambda message: message.text and "sherlock" in message.text.lower() and any(verb in message.text.lower() for verb in ["editar", "adicionar", "excluir", "remover", "abrir"]))
async def intercept_sherlock_nlp(message: Message):
    await cmd_sherlock(message)

@sherlock_router.message(lambda message: message.from_user.id in sherlock_states and sherlock_states[message.from_user.id].get("step") == "waiting_name")
async def intercept_sherlock_state(message: Message):
    user_input = message.text.strip()
    sherlock_states[message.from_user.id]["name"] = user_input
    sherlock_states[message.from_user.id]["step"] = "waiting_category"
    await message.answer(
        f"Alvo recebido: <b>{html.escape(user_input)}</b>.\n\nQual e a categoria?",
        parse_mode=ParseMode.HTML,
        reply_markup=get_category_keyboard()
    )


@sherlock_router.callback_query(F.data.startswith("sherlock_"))
async def sherlock_callbacks(callback: CallbackQuery, pipeline: SeekerPipeline):
    action = callback.data.split("sherlock_")[1]
    user_id = callback.from_user.id

    if action == "list":
        targets = list_all_targets()
        if not targets:
            await callback.message.edit_text("Nenhum alvo monitorado.", reply_markup=get_sherlock_keyboard())
            return

        lines = ["<b>Alvos Monitorados:</b>\n"]
        for t in targets:
            status_emoji = "..." if t.get("status") == "pending" else "OK"
            lines.append(f"{status_emoji} <b>{html.escape(t.get('name', ''))}</b> <i>({t.get('category', 'LLM')})</i>")

        await callback.message.edit_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=get_sherlock_keyboard())

    elif action == "add":
        sherlock_states[user_id] = {"step": "waiting_name"}
        await callback.message.answer("Digite o nome do modelo/ferramenta que deseja monitorar:")
        await callback.answer()

    elif action.startswith("cat_"):
        if user_id in sherlock_states and sherlock_states[user_id].get("step") == "waiting_category":
            category = action.split("cat_")[1]
            model_name = sherlock_states[user_id].get("name")

            add_target(model_name, category)
            del sherlock_states[user_id]

            await callback.message.edit_text(
                f"<b>{html.escape(model_name)}</b> ({category}) adicionado ao SherlockNews!",
                parse_mode=ParseMode.HTML,
                reply_markup=get_sherlock_keyboard()
            )
        else:
            await callback.answer("Sessao expirada. Tente novamente.")

    elif action == "remove_menu":
        targets = list_all_targets()
        keyboard = []
        for t in targets:
            keyboard.append([InlineKeyboardButton(text=f"{t.get('name')} ({t.get('category')})", callback_data=f"sherlock_del_{t.get('id')}")])
        keyboard.append([InlineKeyboardButton(text="Voltar", callback_data="sherlock_back")])

        await callback.message.edit_text(
            "Selecione o alvo para excluir:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    elif action.startswith("del_"):
        target_id = action.split("del_")[1]
        success = remove_target(target_id)
        if success:
            await callback.answer("Alvo removido com sucesso!")
        else:
            await callback.answer("Erro: Alvo nao encontrado.")
        await callback.message.edit_text(
            "<b>SherlockNews: Painel de Monitoramento</b>\n\nEscolha uma opcao abaixo:",
            reply_markup=get_sherlock_keyboard(),
            parse_mode=ParseMode.HTML
        )

    elif action == "back":
        await callback.message.edit_text(
            "<b>SherlockNews: Painel de Monitoramento</b>\n\nEscolha uma opcao abaixo:",
            reply_markup=get_sherlock_keyboard(),
            parse_mode=ParseMode.HTML
        )

    elif action == "force":
        await callback.answer("Iniciando busca...")
        status_msg = await callback.message.answer("Iniciando varredura manual do SherlockNews...")

        try:
            from src.skills.sherlock_news.goal import SherlockNewsGoal
            goal = SherlockNewsGoal(pipeline)
            result = await goal.run_cycle(force=True)

            msg = f"<b>Resultado da Varredura:</b>\n{result.summary}"
            if result.notification:
                msg += f"\n\n{result.notification}"
            await status_msg.edit_text(msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.error(f"[sherlock] Erro na busca forcada: {e}", exc_info=True)
            await status_msg.edit_text(f"Erro na busca: {e}")
