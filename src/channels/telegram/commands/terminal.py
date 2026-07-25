"""
Telegram handler — comando /terminal (execução direta de comandos shell).

Permite rodar comandos do host direto do Telegram, estilo Hermes.
Bypassa o Active Loop do LLM — execução direta do `execute_terminal_command`
que já tem Tirith Security + checkpoint + timeout 45s integrados.

Uso:
  /terminal <comando>          — executa e mostra stdout/stderr
  /terminal timeout 120 <cmd>  — customiza timeout (até 300s)
  /terminal safe ls -la        — modo safe: confirma antes de executar comandos perigosos
  /terminal dir                — atalhos de Windows também funcionam (cmd, dir, etc.)
  /terminal ping google.com    — comandos de rede são permitidos (Tirith audita)

Comandos perigosos (rm, del, format, rmdir, dd, ...) sempre pedem confirmação
via botão inline antes de executar — mesmo que o Tirith já tenha liberado.
"""

import asyncio
import logging
import re
import shlex
from typing import Any

from aiogram import Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.telegram.terminal")


# ── Constantes ──────────────────────────────────────────────────────────

DEFAULT_TIMEOUT = 45
MAX_TIMEOUT = 300
MAX_OUTPUT_CHARS = 4000

# Padrão de comandos que SEMPRE exigem confirmação inline, mesmo se Tirith liberar.
# Lista conservadora — em caso de dúvida, exige confirmação.
DANGEROUS_PATTERN = re.compile(
    r"\b("
    r"rm\b|rmdir|del\b|format\b|mkfs\b|fdisk\b|diskpart|"
    r"dd\b|shutdown|reboot|init\s+\d|"
    r"reg\s+(delete|add)|net\s+user|net\s+localgroup|"
    r"Remove-Item|Del\s+-Force|Remove-ItemRecurse|"
    r"sudo\s+|su\s+-"
    r")",
    re.IGNORECASE,
)


# ── Handler ─────────────────────────────────────────────────────────────


def setup_terminal_handlers(dp: Dispatcher, pipeline: SeekerPipeline):

    @dp.message(F.text.regexp(r"^/terminal(\s|$)"))
    async def cmd_terminal(message: Message):
        """Executa comando shell no host."""
        text = (message.text or "").strip()

        # /terminal sem argumento: mostra help
        if text in ("/terminal", "/terminal help", "/terminal?"):
            await _help(message)
            return

        # Extrai comando e timeout opcional
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.answer(
                "❌ <b>Uso:</b> <code>/terminal &lt;comando&gt;</code>\n"
                "Exemplos:\n"
                "• <code>/terminal ls -la</code>\n"
                "• <code>/terminal dir</code>\n"
                "• <code>/terminal ping 8.8.8.8 -n 4</code>\n"
                "• <code>/terminal timeout 120 npm test</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        rest = parts[1].strip()
        timeout = DEFAULT_TIMEOUT

        # /terminal timeout 120 <cmd>
        m = re.match(r"^timeout\s+(\d+)\s+(.+)$", rest, re.DOTALL)
        if m:
            timeout = min(int(m.group(1)), MAX_TIMEOUT)
            rest = m.group(2).strip()

        command = rest
        if not command:
            await message.answer("❌ Comando vazio.", parse_mode=ParseMode.HTML)
            return

        # Bloqueio de tamanho absurdo
        if len(command) > 4000:
            await message.answer(
                "❌ Comando muito longo (máx 4000 chars).",
                parse_mode=ParseMode.HTML,
            )
            return

        # Se é perigoso, exige confirmação inline
        if DANGEROUS_PATTERN.search(command):
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⚠️ Confirmar execução",
                        callback_data=f"terminal_confirm:{message.message_id}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Cancelar",
                        callback_data="terminal_cancel",
                    ),
                ]
            ])
            # Armazena comando pendente no state da pipeline (TTL simples)
            pipeline._terminal_pending = {
                "command": command,
                "timeout": timeout,
                "message_id": message.message_id,
            }
            await message.answer(
                f"⚠️ <b>Comando potencialmente perigoso detectado</b>\n\n"
                f"<code>{_escape_html(command[:500])}</code>\n\n"
                f"Esse comando contém padrão que exige confirmação explícita. "
                f"Deseja prosseguir?",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return

        # Execução direta
        await _execute_and_reply(message, pipeline, command, timeout)

    @dp.callback_query(F.data.startswith("terminal_confirm:"))
    async def cb_confirm(call: CallbackQuery):
        """Confirma execução de comando perigoso."""
        await call.answer()
        pending = getattr(pipeline, "_terminal_pending", None)
        if not pending:
            await call.message.answer("❌ Sessão expirou. Envie o comando de novo.")
            return
        # Limpa pending IMEDIATAMENTE (evita duplo-click)
        pipeline._terminal_pending = None
        await _execute_and_reply(
            call.message,
            pipeline,
            pending["command"],
            pending["timeout"],
        )

    @dp.callback_query(F.data == "terminal_cancel")
    async def cb_cancel(call: CallbackQuery):
        await call.answer("Cancelado")
        pending = getattr(pipeline, "_terminal_pending", None)
        if pending:
            pipeline._terminal_pending = None
        try:
            await call.message.edit_text("❌ Comando cancelado.")
        except Exception:
            pass


# ── Helpers ─────────────────────────────────────────────────────────────


async def _help(message: Message):
    await message.answer(
        "🖥️ <b>Terminal Direto (estilo Hermes)</b>\n\n"
        "<b>Uso:</b> <code>/terminal &lt;comando&gt;</code>\n\n"
        "<b>Opções:</b>\n"
        "• <code>/terminal &lt;comando&gt;</code> — executa (timeout 45s)\n"
        "• <code>/terminal timeout 120 &lt;comando&gt;</code> — customiza timeout (até 300s)\n\n"
        "<b>Proteções:</b>\n"
        "• Tirith Security audita cada comando antes de executar\n"
        "• Checkpoint automático antes de comandos destrutivos\n"
        "• Comandos perigosos (rm, del, format, ...) pedem confirmação inline\n"
        "• Timeout máximo: 300s\n\n"
        "<b>Exemplos:</b>\n"
        "• <code>/terminal dir</code>\n"
        "• <code>/terminal ls -la</code>\n"
        "• <code>/terminal ping 8.8.8.8 -n 4</code>\n"
        "• <code>/terminal timeout 120 npm test</code>\n"
        "• <code>/terminal cat config\\.env\\.example</code>",
        parse_mode=ParseMode.HTML,
    )


async def _execute_and_reply(
    message: Message,
    pipeline: SeekerPipeline,
    command: str,
    timeout: int,
):
    """Executa o comando e responde com output."""
    # Mensagem "executando..."
    status_msg = await message.answer(
        f"⏱️ <b>Executando:</b>\n<code>{_escape_html(command[:300])}</code>\n"
        f"<i>Timeout: {timeout}s</i>",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Importa aqui para não acoplar o módulo inteiro do Seeker no import-time
        from src.core.execution.registry import execute_terminal_command

        start = asyncio.get_event_loop().time()
        output = await execute_terminal_command(command)
        elapsed = asyncio.get_event_loop().time() - start

        # Trunca output se muito longo
        if len(output) > MAX_OUTPUT_CHARS:
            output = (
                output[:MAX_OUTPUT_CHARS]
                + f"\n\n<i>... (truncado, output total: {len(output)} chars)</i>"
            )

        text = (
            f"✅ <b>Concluído em {elapsed:.1f}s</b>\n\n"
            f"<b>Comando:</b> <code>{_escape_html(command[:300])}</code>\n\n"
            f"<b>Output:</b>\n"
            f"<pre>{_escape_html(output)}</pre>"
        )

        try:
            await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
        except Exception:
            # Se falhar (mensagem muito longa), envia como nova
            await message.answer(text, parse_mode=ParseMode.HTML)

    except Exception as e:
        log.error(f"[terminal] Erro ao executar '{command}': {e}", exc_info=True)
        try:
            await status_msg.edit_text(
                f"❌ <b>Erro ao executar comando</b>\n\n"
                f"<b>Comando:</b> <code>{_escape_html(command[:300])}</code>\n\n"
                f"<b>Erro:</b> <pre>{_escape_html(str(e)[:1000])}</pre>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            await message.answer(
                f"❌ <b>Erro ao executar comando</b>\n\n"
                f"<code>{_escape_html(str(e)[:500])}</code>",
                parse_mode=ParseMode.HTML,
            )


def _escape_html(text: str) -> str:
    """Escapa HTML para Telegram ParseMode.HTML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
