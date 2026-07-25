"""Telegram /validate command — audita system prompts (13 boas praticas + 6 red flags).

Port do Promptograph (MIT). Permite:
  /validate <prompt colado>    -> pontua 0-100%, nota A+ a F, lista passes/faltas/warnings
  /validate list               -> mostra as 13 boas praticas e os pesos
  /validate                    -> ajuda
"""

from __future__ import annotations

import html
import logging

from aiogram import Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from src.core.pipeline import SeekerPipeline
from src.skills.promptograph import validate_prompt, build_prompt, GOOD_PRACTICES, RED_FLAGS, PRESET_TEMPLATES

log = logging.getLogger("seeker.telegram.validate")


def setup_validate_handlers(dp: Dispatcher, pipeline: SeekerPipeline):

    @dp.message(F.text.regexp(r"^/validate(\s|$)"))
    async def cmd_validate(message: Message):
        """Auditoria de system prompt com 13 boas praticas + 6 red flags."""
        raw = (message.text or "").strip()
        arg = raw[len("/validate"):].strip()

        if not arg:
            await message.answer(
                "<b>Promptograph Validator</b> \n"
                "Cola um system prompt pra receber uma pontuacao 0-100% (nota A+ a F) "
                "contra 13 boas praticas extraidas de 5.317 prompts reais de producao.\n\n"
                "<b>Uso:</b>\n"
                "<code>/validate <texto do prompt></code> - audita um prompt\n"
                "<code>/validate list</code> - lista as 13 boas praticas + 6 red flags\n"
                "<code>/validate presets</code> - mostra os 5 presets de geracao\n\n"
                "<i>Exemplo: cola depois de /validate um system prompt inteiro. "
                "Quotes e quebras de linha OK.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="📋 13 boas praticas", callback_data="pg_list"),
                    InlineKeyboardButton(text="✨ 5 presets", callback_data="pg_presets"),
                ]]),
            )
            return

        if arg.lower() in ("list", "lista", "help"):
            await _send_practices_list(message)
            return

        if arg.lower() in ("presets", "preset"):
            await _send_presets_keyboard(message)
            return

        await _run_validation(message, arg)

    @dp.callback_query(F.data == "pg_list")
    async def cb_pg_list(callback: CallbackQuery):
        await callback.answer()
        await _send_practices_list(callback.message)

    @dp.callback_query(F.data == "pg_presets")
    async def cb_pg_presets(callback: CallbackQuery):
        await callback.answer()
        await _send_presets_keyboard(callback.message)

    # Callback de preset: "pg_preset:<name>"
    @dp.callback_query(F.data.regexp(r"^pg_preset:"))
    async def cb_pg_preset(callback: CallbackQuery):
        await callback.answer()
        name = callback.data.split(":", 1)[1]
        if name not in PRESET_TEMPLATES:
            await callback.message.answer(f"❌ Preset <code>{html.escape(name)}</code> nao encontrado.",
                                          parse_mode=ParseMode.HTML)
            return
        preset = PRESET_TEMPLATES[name]
        spec = preset["spec"]
        built = build_prompt(spec)
        val = validate_prompt(built)
        lines = [f"<b>✨ Preset: {html.escape(name)}</b>"]
        lines.append(f"<i>{html.escape(preset['description'])}</i>\n")
        lines.append(
            f"<b>Score:</b> <code>{val['score']}%</code> ({val['grade']}) - tokens: ~{val['stats']['tokens_estimate']}\n"
        )
        lines.append(
            "Prompt completo abaixo - pode copiar e ajustar, ou usar /generate para customizar:"
        )
        await callback.message.answer("\n".join(lines), parse_mode=ParseMode.HTML)
        await callback.message.answer(
            f"<code>{html.escape(built)}</code>",
            parse_mode=ParseMode.HTML,
        )

    # Callback de validacao de preset: "pg_val:<name>"
    @dp.callback_query(F.data.regexp(r"^pg_val:"))
    async def cb_pg_val(callback: CallbackQuery):
        await callback.answer()
        name = callback.data.split(":", 1)[1]
        if name not in PRESET_TEMPLATES:
            return
        built = build_prompt(PRESET_TEMPLATES[name]["spec"])
        await _send_validation_output(
            callback.message, built,
            title=f"Validacao do preset <code>{html.escape(name)}</code>",
        )


async def _run_validation(message: Message, content: str):
    """Filtra, valida e envia o score."""
    if len(content.strip()) < 50:
        await message.answer(
            "⚠️ Prompt muito curto (minimo 50 chars). Cola um system prompt completo.",
            parse_mode=ParseMode.HTML,
        )
        return
    await _send_validation_output(message, content)


async def _send_validation_output(message: Message, content: str, title: str = None):
    try:
        status_msg = await message.answer("⏳ Validando...")
        result = validate_prompt(content)
        await status_msg.delete()

        short_preview = content[:60].replace("\n", " ") + ("..." if len(content) > 60 else "")
        header = (
            f"<b>📋 Auditoria de System Prompt</b>\n"
            f"{title + chr(10) if title else ''}"
            f"<i>{html.escape(short_preview)}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Score:</b> <code>{result['score']}%</code>\n"
            f"<b>Nota:</b> {result['grade']}\n"
            f"<b>Tokens est:</b> ~{result['stats']['tokens_estimate']}\n\n"
            f"📌 <b>{result['summary']}</b>\n"
        )

        passed_keys = [p['key'] for p in result['passed']]
        failed_keys = [f['key'] for f in result['failed']]
        warn_keys = [w['key'] for w in result['warnings']]

        def _label(k):
            if k in passed_keys:
                return "✅"
            if k in failed_keys:
                return "❌"
            return "⚠️"

        lines = [header, "<b>Score detalhado (13 boas praticas):</b>"]
        for p_name, practice in GOOD_PRACTICES.items():
            mark = _label(p_name)
            lines.append(f"{mark} <code>{p_name}</code> ({practice['weight']}pts)")

        if result['warnings']:
            lines.append("\n<b>Red flags:</b>")
            for w in result['warnings']:
                lines.append(f"⚠️ {w['description']}")

        if result['failed']:
            lines.append("\n<b>Faltam:</b>")
            for f in result['failed']:
                lines.append(f"• {f['description']}")

        out_text = "\n".join(lines)
        if len(out_text) > 4000:
            out_text = out_text[:4000] + "\n... (truncado)"
        await message.answer(out_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        log.exception("[validate] falhou")
        await message.answer(f"❌ Erro ao validar: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


async def _send_practices_list(message: Message):
    lines = ["<b>📋 13 boas praticas (100pts total)</b>"]
    for k, p in GOOD_PRACTICES.items():
        lines.append(f"• <code>{k}</code> ({p['weight']}pts) - {p['description']}")
    lines.append("\n<b>🚩 6 red flags</b>")
    for k, f in RED_FLAGS.items():
        lines.append(f"• {k} - {f['description']}")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n... (truncado)"
    await message.answer(text, parse_mode=ParseMode.HTML)


async def _send_presets_keyboard(message: Message):
    rows = []
    for name, p in PRESET_TEMPLATES.items():
        rows.append([InlineKeyboardButton(
            text=f"✨ {name}",
            callback_data=f"pg_preset:{name}",
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer(
        "<b>5 presets</b> (extraidos de prompts reais de producao):\n\n"
        f"• <code>claude_coding_agent</code> - agent codificacao (Anthropic)\n"
        f"• <code>gpt5_assistant</code> - assistente conversacional (OpenAI)\n"
        f"• <code>cursor_style_coding</code> - IDE agent (Anysphere)\n"
        f"• <code>perplexity_search</code> - search engine citado (Perplexity)\n"
        f"• <code>devin_autonomous</code> - autonomic engineer (Cognition)\n\n"
        "<i>Clique pra ver + gerar + validar.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
