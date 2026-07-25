"""Telegram /generate command — gera system prompts a partir de presets ou specs custom.

Port do Promptograph (MIT). Permite:
  /generate                    -> menu com 5 presets
  /generate <preset_name>      -> gera prompt do preset, mostra score
  /generate custom             -> wizard pra construir prompt customizado
  /generate custom <name> | <role_description> | <company> | <tools>
       -> atalho rapido sem wizard
"""

from __future__ import annotations

import html
import logging

from aiogram import Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from src.core.pipeline import SeekerPipeline
from src.skills.promptograph import build_prompt, validate_prompt, PRESET_TEMPLATES

log = logging.getLogger("seeker.telegram.generate")

# Estado em memoria para wizards customizados: chat_id -> {field: value}
# (limpa no fim do wizard; se usuario reiniciar bot, perde — OK pra v1)
_custom_wizards: dict[int, dict] = {}

_WIZARD_FIELDS = [
    ("name", "Nome do agente", "CodeAssist"),
    ("role_description", "Descricao do papel (ex: 'an expert coding assistant')", "an AI assistant"),
    ("company", "Empresa criadora", "Acme"),
    ("model", "Modelo (ex: claude-opus-4.5)", "my-model"),
    ("family", "Familia do modelo", ""),
]

_TONE_OPTIONS = ["default", "concise", "professional", "creative"]
_FORMATTING_OPTIONS = ["default", "minimal"]
_SAFETY_OPTIONS = ["default", "minimal", "creative"]
_MEMORY_OPTIONS = ["default", "none"]
_REFUSALS_OPTIONS = ["default", "strict"]


def setup_generate_handlers(dp: Dispatcher, pipeline: SeekerPipeline):

    @dp.message(F.text.regexp(r"^/generate(\s|$)"))
    async def cmd_generate(message: Message):
        """Gera system prompt via preset ou wizard custom."""
        raw = (message.text or "").strip()
        arg = raw[len("/generate"):].strip()

        if not arg:
            await _send_presets_keyboard(message, prefix="gen")
            return

        if arg.lower() == "custom":
            await _start_wizard(message)
            return

        # Atalho: /generate custom <name> | <role> | <company> | <tools_csv>
        if arg.lower().startswith("custom "):
            payload = arg[len("custom "):].strip()
            await _handle_custom_shortcut(message, payload)
            return

        # Match preset name
        if arg in PRESET_TEMPLATES:
            await _generate_and_show(message, arg)
            return

        # Busca aproximada
        matches = [n for n in PRESET_TEMPLATES if arg.lower() in n.lower()]
        if len(matches) == 1:
            await _generate_and_show(message, matches[0])
            return
        if len(matches) > 1:
            await message.answer(
                f"Multiplos matches: <code>{'</code>, <code>'.join(matches)}</code>\n"
                "Use o nome completo.",
                parse_mode=ParseMode.HTML,
            )
            return
        await message.answer(
            f"Preset <code>{html.escape(arg)}</code> nao encontrado. "
            "Use <code>/generate</code> para ver a lista de presets.",
            parse_mode=ParseMode.HTML,
        )

    @dp.callback_query(F.data.regexp(r"^gen_preset:"))
    async def cb_gen_preset(callback: CallbackQuery):
        await callback.answer()
        name = callback.data.split(":", 1)[1]
        await _generate_and_show(callback.message, name)

    @dp.callback_query(F.data == "gen_custom_start")
    async def cb_gen_custom_start(callback: CallbackQuery):
        await callback.answer()
        await _start_wizard(callback.message)

    # Wizard flow: chat waiting for next field input
    @dp.callback_query(F.data.regexp(r"^gen_wiz_"))
    async def cb_gen_wizard(callback: CallbackQuery):
        await callback.answer()
        chat_id = callback.message.chat.id
        state = _custom_wizards.get(chat_id)
        if not state:
            await callback.message.answer("Wizard expirou. Use /generate custom novamente.")
            return
        action = callback.data.split(":", 1)[1]
        if action.startswith("tone_"):
            state["tone"] = action[len("tone_"):]
            await _advance_wizard(callback.message, state)
        elif action.startswith("fmt_"):
            state["formatting"] = action[len("fmt_"):]
            await _advance_wizard(callback.message, state)
        elif action.startswith("safety_"):
            state["safety"] = action[len("safety_"):]
            await _advance_wizard(callback.message, state)
        elif action.startswith("mem_"):
            state["memory"] = action[len("mem_"):]
            await _advance_wizard(callback.message, state)
        elif action.startswith("ref_"):
            state["refusals"] = action[len("ref_"):]
            await _advance_wizard(callback.message, state)
        elif action == "finish":
            await _finish_wizard(callback.message, state)
        elif action == "cancel":
            _custom_wizards.pop(chat_id, None)
            await callback.message.answer("❌ Wizard cancelado.")


async def _send_presets_keyboard(message: Message, prefix: str = "gen"):
    rows = []
    for name, preset in PRESET_TEMPLATES.items():
        rows.append([InlineKeyboardButton(
            text=f"✨ {name}",
            callback_data=f"{prefix}_preset:{name}",
        )])
    rows.append([InlineKeyboardButton(text="🛠️ Custom (wizard)", callback_data=f"{prefix}_custom_start")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer(
        "<b>✨ Gerador de System Prompts</b>\n"
        "5 presets extraidos de prompts reais de producao + wizard custom.\n\n"
        "<b>Presets:</b>\n"
        "• <code>claude_coding_agent</code> - Anthropic\n"
        "• <code>gpt5_assistant</code> - OpenAI\n"
        "• <code>cursor_style_coding</code> - Anysphere\n"
        "• <code>perplexity_search</code> - Perplexity\n"
        "• <code>devin_autonomous</code> - Cognition\n\n"
        "<i>Clique pra gerar. Use /validate para auditar o resultado.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def _generate_and_show(message: Message, preset_name: str):
    """Gera prompt do preset, mostra + valida."""
    preset = PRESET_TEMPLATES[preset_name]
    spec = preset["spec"]
    prompt = build_prompt(spec)
    val = validate_prompt(prompt)

    header_lines = [
        f"<b>✨ Prompt gerado: {html.escape(preset_name)}</b>",
        f"<i>{html.escape(preset['description'])}</i>\n",
        f"<b>Score:</b> <code>{val['score']}%</code> ({val['grade']})  |  "
        f"<b>Tokens:</b> ~{val['stats']['tokens_estimate']}  |  "
        f"<b>Chars:</b> {val['stats']['chars']}\n",
        "<i>Prompt completo:</i>",
    ]
    await message.answer("\n".join(header_lines), parse_mode=ParseMode.HTML)

    if len(prompt) > 4000 - 100:
        # Telegram message limit 4096 chars. Split into chunks.
        chunks = [prompt[i:i+3900] for i in range(0, len(prompt), 3900)]
        for i, chunk in enumerate(chunks, 1):
            await message.answer(
                f"<code>{html.escape(chunk)}</code>",
                parse_mode=ParseMode.HTML,
            )
    else:
        await message.answer(
            f"<code>{html.escape(prompt)}</code>",
            parse_mode=ParseMode.HTML,
        )

    # Botao pra validar de novo ou copiar
    warnings = len(val['warnings']) > 0
    footer = []
    if val['failed']:
        footer.append(f"❌ <b>Faltam {len(val['failed'])} checks:</b>")
        for f in val['failed'][:5]:
            footer.append(f"   • {html.escape(f['description'])}")
    if warnings:
        footer.append(f"⚠️ <b>{len(val['warnings'])} red flags</b> identificadas.")
    if footer:
        await message.answer("\n".join(footer), parse_mode=ParseMode.HTML)


async def _start_wizard(message: Message):
    """Inicia wizard conversacional pra prompt customizado."""
    chat_id = message.chat.id
    # Se ja tinha wizard, recomeca
    _custom_wizards[chat_id] = {
        "name": "",
        "role_description": "",
        "company": "",
        "model": "",
        "family": "",
        "tone": "default",
        "formatting": "default",
        "safety": "default",
        "memory": "default",
        "refusals": "default",
        "include_examples": True,
        "step": "name",
    }
    await message.answer(
        "<b>🛠️ Wizard Custom Prompt</b>\n\n"
        "Vou pedir 5 campos. Manda o valor de cada um como mensagem.\n"
        "<i>Digite <code>/generate custom cancel</code> pra desistir.</i>\n\n"
        "<b>Campo 1/5: Nome do agente</b>\n"
        "<i>Ex: CodeAssist, MyBot, FinanceHelper...</i>",
        parse_mode=ParseMode.HTML,
    )

    # Marca chat como wizard — capturamos mensagens no catch-all
    # Mas o catch-all em message.py pode interferir. Solução: registramos um filtro
    # de mensagem aqui dentro que pega a próxima mensagem do chat.
    # aiogram 3 não tem "esperar próxima mensagem" fácil. workaround: armazenar
    # chat_id e tratar em um handler de fallback.
    # Simplificação: vamos usar callback_data + inline keyboards pra tudo.
    return await _advance_wizard(message, _custom_wizards[chat_id])


async def _advance_wizard(message: Message, state: dict):
    """Avanca o wizard mostrando proxima pergunta ou abas com botoes."""
    # O wizard e por botoes inline no canto do chat - mais robusto que esperar texto livre
    step = state.get("step", "tone")
    if step == "tone":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Default", callback_data="gen_wiz_tone_default")],
            [InlineKeyboardButton(text="Concise", callback_data="gen_wiz_tone_concise"),
             InlineKeyboardButton(text="Professional", callback_data="gen_wiz_tone_professional"),
             InlineKeyboardButton(text="Creative", callback_data="gen_wiz_tone_creative")],
        ])
        await message.answer(
            "<b>Tom de voz</b>\n"
            "<i>Como o agente deve falar?</i>",
            reply_markup=kb, parse_mode=ParseMode.HTML,
        )
    elif step == "formatting":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Default (markdown + bullets)", callback_data="gen_wiz_fmt_default"),
             InlineKeyboardButton(text="Minimal", callback_data="gen_wiz_fmt_minimal")],
        ])
        await message.answer(
            "<b>Formatacao</b>\n<i>Default usa markdown robusto. Minimal e mais enxuto.</i>",
            reply_markup=kb, parse_mode=ParseMode.HTML,
        )
    elif step == "safety":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Default (full)", callback_data="gen_wiz_safety_default"),
             InlineKeyboardButton(text="Minimal", callback_data="gen_wiz_safety_minimal"),
             InlineKeyboardButton(text="Creative", callback_data="gen_wiz_safety_creative")],
        ])
        await message.answer(
            "<b>Seguranca</b>\n<i>Default tem regras robustas. Minimal e curta. Creative libera contexto artistico.</i>",
            reply_markup=kb, parse_mode=ParseMode.HTML,
        )
    elif step == "memory":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Default (com memoria)", callback_data="gen_wiz_mem_default"),
             InlineKeyboardButton(text="None (fresh cada turno)", callback_data="gen_wiz_mem_none")],
        ])
        await message.answer(
            "<b>Memoria entre turnos</b>",
            reply_markup=kb, parse_mode=ParseMode.HTML,
        )
    elif step == "refusals":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Default", callback_data="gen_wiz_ref_default"),
             InlineKeyboardButton(text="Strict", callback_data="gen_wiz_ref_strict")],
        ])
        await message.answer(
            "<b>Recusas</b>\n<i>Default oferece alternativas. Strict so recusa.</i>",
            reply_markup=kb, parse_mode=ParseMode.HTML,
        )
    elif step == "finish":
        # Mostra resumo e pede confirmacao
        spec = _build_spec_from_wizard(state)
        await message.answer(
            f"<b>Resumo da spec:</b>\n"
            f"<code>{html.escape(_spec_summary(spec))}</code>\n\n"
            "<i>Gerar prompt?</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Gerar", callback_data="gen_wiz_finish"),
                InlineKeyboardButton(text="❌ Cancelar", callback_data="gen_wiz_cancel"),
            ]]),
            parse_mode=ParseMode.HTML,
        )


async def _handle_custom_shortcut(message: Message, payload: str):
    """Atalho: /generate custom Name | role | company | tool1,tool2."""
    parts = [p.strip() for p in payload.split("|")]
    if len(parts) < 2:
        await message.answer(
            "Uso: <code>/generate custom Nome | papel do agente | empresa | tool1,tool2</code>\n"
            "<i>Ex: /generate custom Helper | an AI helper | Acme | search,fetch</i>",
            parse_mode=ParseMode.HTML,
        )
        return
    spec = {
        "name": parts[0] or "CustomBot",
        "role_description": parts[1] or "an AI assistant",
        "company": parts[2] if len(parts) > 2 else "your company",
        "model": "custom-model",
        "family": "Custom",
        "tone": "default",
        "formatting": "default",
        "safety": "default",
        "tools": [t.strip() for t in parts[3].split(",")] if len(parts) > 3 and parts[3] else None,
        "memory": "default",
        "refusals": "default",
        "include_examples": True,
    }
    prompt = build_prompt(spec)
    val = validate_prompt(prompt)
    await message.answer(
        f"<b>✨ Prompt custom gerado</b>\n"
        f"<b>Score:</b> <code>{val['score']}%</code> ({val['grade']})  |  "
        f"<b>Tokens:</b> ~{val['stats']['tokens_estimate']}\n",
        parse_mode=ParseMode.HTML,
    )
    await message.answer(f"<code>{html.escape(prompt)}</code>", parse_mode=ParseMode.HTML)


def _build_spec_from_wizard(state: dict) -> dict:
    return {
        "name": state.get("name") or "CustomBot",
        "role_description": state.get("role_description") or "an AI assistant",
        "company": state.get("company") or "your company",
        "model": state.get("model") or "custom-model",
        "family": state.get("family") or "Custom",
        "tone": state.get("tone", "default"),
        "formatting": state.get("formatting", "default"),
        "safety": state.get("safety", "default"),
        "memory": state.get("memory", "default"),
        "refusals": state.get("refusals", "default"),
        "tools": None,
        "include_examples": True,
    }


def _spec_summary(spec: dict) -> str:
    return (
        f"name={spec['name']}\n"
        f"role={spec['role_description']}\n"
        f"company={spec['company']}\n"
        f"model={spec['model']} family={spec['family']}\n"
        f"tone={spec['tone']} | fmt={spec['formatting']} | safety={spec['safety']}\n"
        f"memory={spec['memory']} | refusals={spec['refusals']} | examples={spec['include_examples']}"
    )


async def _finish_wizard(message: Message, state: dict):
    chat_id = message.chat.id
    _custom_wizards.pop(chat_id, None)
    spec = _build_spec_from_wizard(state)
    prompt = build_prompt(spec)
    val = validate_prompt(prompt)
    await message.answer(
        f"<b>✨ Prompt custom gerado</b>\n"
        f"<b>Score:</b> <code>{val['score']}%</code> ({val['grade']})  |  "
        f"<b>Tokens:</b> ~{val['stats']['tokens_estimate']}\n",
        parse_mode=ParseMode.HTML,
    )
    await message.answer(f"<code>{html.escape(prompt)}</code>", parse_mode=ParseMode.HTML)
