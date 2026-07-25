"""
Telegram handler — comando /mcp (gerenciamento e invocação direta de tools MCP).

Permite listar servidores MCP conectados, ver tools disponíveis e invocá-las
diretamente sem precisar do LLM emitir tag [MCP_CALL].

Uso:
  /mcp                       → lista servidores conectados + contagem de tools
  /mcp <server>              → lista tools de um servidor específico
  /mcp <server> <tool> <json> → executa tool com argumentos JSON
  /mcp reconnect             → reconecta todos os servidores

Exemplos:
  /mcp
  /mcp filesystem
  /mcp filesystem list_directory {"path": "C:/Users/Victor/Documents"}
  /mcp github search_repositories {"query": "seeker bot"}
"""

import asyncio
import json
import logging
import re
from html import escape

from aiogram import Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import Message

from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.telegram.mcp")


# ── Constantes ──────────────────────────────────────────────────────────

MAX_OUTPUT_CHARS = 3500
TOOL_CALL_TIMEOUT = 120  # segundos


# ── Handler ─────────────────────────────────────────────────────────────


def setup_mcp_handlers(dp: Dispatcher, pipeline: SeekerPipeline):

    @dp.message(F.text.regexp(r"^/mcp(\s|$)"))
    async def cmd_mcp(message: Message):
        """Comando principal /mcp."""
        text = (message.text or "").strip()

        # /mcp sem args → lista servidores
        if text in ("/mcp", "/mcp help", "/mcp?"):
            await _list_servers(message, pipeline)
            return

        # /mcp reconnect
        if text == "/mcp reconnect":
            await _reconnect_all(message, pipeline)
            return

        # /mcp <server>
        parts = text.split(maxsplit=2)
        if len(parts) == 2:
            await _list_tools(message, pipeline, parts[1].strip())
            return

        # /mcp <server> <tool> <json>
        if len(parts) == 3:
            server = parts[1].strip()
            rest = parts[2].strip()
            tool_and_args = rest.split(maxsplit=1)
            tool = tool_and_args[0]
            args_json = tool_and_args[1] if len(tool_and_args) > 1 else "{}"
            await _call_tool(message, pipeline, server, tool, args_json)
            return

        await _help(message)


# ── Ações ───────────────────────────────────────────────────────────────


async def _help(message: Message):
    await message.answer(
        "🔌 <b>MCP (Model Context Protocol)</b>\n\n"
        "<b>Uso:</b>\n"
        "• <code>/mcp</code> — lista servidores conectados\n"
        "• <code>/mcp &lt;server&gt;</code> — lista tools de um servidor\n"
        "• <code>/mcp &lt;server&gt; &lt;tool&gt; &lt;args_json&gt;</code> — executa tool\n"
        "• <code>/mcp reconnect</code> — reconecta todos\n\n"
        "<b>Exemplos:</b>\n"
        "• <code>/mcp</code>\n"
        "• <code>/mcp filesystem</code>\n"
        "• <code>/mcp filesystem list_directory {\"path\": \"C:/Users/Victor/Documents\"}</code>\n"
        "• <code>/mcp github search_repositories {\"query\": \"seeker bot\"}</code>\n\n"
        "<b>Configuração:</b> <code>config/mcp_servers.json</code>",
        parse_mode=ParseMode.HTML,
    )


async def _list_servers(message: Message, pipeline: SeekerPipeline):
    """Lista todos os servidores MCP e seu status."""
    status_msg = await message.answer(
        "🔌 Carregando servidores MCP...",
        parse_mode=ParseMode.HTML,
    )

    try:
        from src.core.execution.mcp_client import MCPClient

        client = MCPClient.get()
        # Lazy connect se ainda não conectou
        if not client.connections:
            await client.connect_all()

        servers = await client.list_servers()
        if not servers:
            await status_msg.edit_text(
                "🔌 <b>MCP</b>\n\n"
                "Nenhum servidor configurado.\n\n"
                "Edite <code>config/mcp_servers.json</code> e reinicie, "
                "ou use <code>/mcp reconnect</code>.",
                parse_mode=ParseMode.HTML,
            )
            return

        lines = ["🔌 <b>MCP Servers</b>\n"]
        for srv in servers:
            name = srv["name"]
            if srv.get("connected"):
                n_tools = srv.get("tool_count", 0)
                tool_names = srv.get("tools", [])
                cmd = srv.get("command", "?")
                args = srv.get("args", [])
                cmd_str = f"{cmd} {' '.join(args[:2])}"
                lines.append(
                    f"✅ <b>{_escape(name)}</b> — {n_tools} tools\n"
                    f"   <i>{_escape(cmd_str[:80])}</i>"
                )
                if tool_names:
                    preview = ", ".join(tool_names[:5])
                    more = f" +{len(tool_names)-5}" if len(tool_names) > 5 else ""
                    lines.append(f"   <code>{_escape(preview + more)}</code>")
            else:
                err = srv.get("error", "desconhecido")
                lines.append(
                    f"❌ <b>{_escape(name)}</b> — falhou\n"
                    f"   <i>{_escape(str(err)[:120])}</i>"
                )

        lines.append(f"\nTotal: <b>{len(servers)}</b> servidor(es) configurado(s)")
        lines.append("\nUse <code>/mcp &lt;server&gt;</code> para ver tools.")
        await status_msg.edit_text(
            "\n".join(lines), parse_mode=ParseMode.HTML
        )
    except Exception as e:
        log.error(f"[mcp] Erro listando servers: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ <b>Erro ao listar servidores</b>\n\n<pre>{_escape(str(e)[:500])}</pre>",
            parse_mode=ParseMode.HTML,
        )


async def _list_tools(message: Message, pipeline: SeekerPipeline, server: str):
    """Lista tools de um servidor específico."""
    status_msg = await message.answer(
        f"🔌 Carregando tools de <code>{_escape(server)}</code>...",
        parse_mode=ParseMode.HTML,
    )

    try:
        from src.core.execution.mcp_client import MCPClient

        client = MCPClient.get()
        if not client.connections:
            await client.connect_all()

        if server not in client.connections:
            available = ", ".join(client.connections.keys()) or "(nenhum)"
            await status_msg.edit_text(
                f"❌ Servidor <b>{_escape(server)}</b> não está conectado.\n\n"
                f"<b>Disponíveis:</b> <code>{_escape(available)}</code>\n\n"
                f"Use <code>/mcp</code> para listar todos.",
                parse_mode=ParseMode.HTML,
            )
            return

        tools = await client.list_tools(server)
        if not tools:
            await status_msg.edit_text(
                f"🔌 <b>{_escape(server)}</b> — 0 tools expostas.",
                parse_mode=ParseMode.HTML,
            )
            return

        lines = [f"🔌 <b>{_escape(server)}</b> — {len(tools)} tools\n"]
        for t in tools:
            desc = t.description[:120] + ("…" if len(t.description) > 120 else "")
            schema_props = list(t.input_schema.get("properties", {}).keys())
            schema_hint = f" <i>[{', '.join(schema_props[:3])}]</i>" if schema_props else ""
            lines.append(f"• <code>{_escape(t.name)}</code>{schema_hint}")
            if desc:
                lines.append(f"  <i>{_escape(desc)}</i>")

        usage_example = f"/mcp {server} {tools[0].name} {{\"...args...\"}}"
        lines.append(
            f"\n<b>Uso:</b>\n"
            f"<code>{_escape(usage_example)}</code>"
        )
        await status_msg.edit_text(
            "\n".join(lines), parse_mode=ParseMode.HTML
        )
    except Exception as e:
        log.error(f"[mcp] Erro listando tools de {server}: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ <b>Erro ao listar tools de {_escape(server)}</b>\n\n"
            f"<pre>{_escape(str(e)[:500])}</pre>",
            parse_mode=ParseMode.HTML,
        )


async def _call_tool(
    message: Message,
    pipeline: SeekerPipeline,
    server: str,
    tool: str,
    args_json: str,
):
    """Executa uma tool MCP com os argumentos JSON."""
    # Parse args_json
    try:
        args = json.loads(args_json) if args_json.strip() else {}
    except Exception as je:
        await message.answer(
            f"❌ <b>JSON inválido:</b>\n<pre>{_escape(str(je)[:300])}</pre>\n\n"
            f"<b>Args recebidos:</b>\n<code>{_escape(args_json[:300])}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if not isinstance(args, dict):
        await message.answer(
            f"❌ Args devem ser um objeto JSON, recebi: {type(args).__name__}",
            parse_mode=ParseMode.HTML,
        )
        return

    status_msg = await message.answer(
        f"⏱️ <b>Executando</b> <code>{_escape(server)}.{_escape(tool)}</code>...\n"
        f"<i>Args:</i> <code>{_escape(json.dumps(args)[:300])}</code>",
        parse_mode=ParseMode.HTML,
    )

    try:
        from src.core.execution.mcp_client import MCPClient

        client = MCPClient.get()
        if not client.connections:
            await client.connect_all()

        start = asyncio.get_event_loop().time()
        result = await client.call_tool(server, tool, args, timeout=TOOL_CALL_TIMEOUT)
        elapsed = asyncio.get_event_loop().time() - start

        # Trunca output
        truncated = False
        if len(result) > MAX_OUTPUT_CHARS:
            result = result[:MAX_OUTPUT_CHARS] + f"\n\n... (truncado, {len(result)} chars)"
            truncated = True

        text = (
            f"✅ <b>Concluído em {elapsed:.1f}s</b>\n\n"
            f"<b>Servidor:</b> <code>{_escape(server)}</code>\n"
            f"<b>Tool:</b> <code>{_escape(tool)}</code>\n"
            f"<b>Args:</b> <code>{_escape(json.dumps(args)[:200])}</code>\n\n"
            f"<b>Output:</b>\n<pre>{_escape(result)}</pre>"
        )
        try:
            await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
        except Exception:
            await message.answer(text, parse_mode=ParseMode.HTML)
    except TimeoutError as te:
        await status_msg.edit_text(
            f"⏰ <b>Timeout</b> em <code>{_escape(server)}.{_escape(tool)}</code>\n\n"
            f"<pre>{_escape(str(te)[:500])}</pre>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        log.error(
            f"[mcp] Erro executando {server}.{tool}: {e}", exc_info=True
        )
        await status_msg.edit_text(
            f"❌ <b>Erro em</b> <code>{_escape(server)}.{_escape(tool)}</code>\n\n"
            f"<pre>{_escape(str(e)[:500])}</pre>",
            parse_mode=ParseMode.HTML,
        )


async def _reconnect_all(message: Message, pipeline: SeekerPipeline):
    """Reconecta todos os servidores MCP."""
    status_msg = await message.answer(
        "🔄 Reconectando servidores MCP...",
        parse_mode=ParseMode.HTML,
    )

    try:
        from src.core.execution.mcp_client import MCPClient

        client = MCPClient.get()
        await client.disconnect_all()
        results = await client.reconnect()

        lines = ["🔄 <b>MCP Reconnect</b>\n"]
        for name, status in results.items():
            if status == "connected":
                lines.append(f"✅ <b>{_escape(name)}</b> — reconectado")
            else:
                lines.append(
                    f"❌ <b>{_escape(name)}</b> — {_escape(status[:120])}"
                )

        connected = sum(1 for v in results.values() if v == "connected")
        total = len(results)
        lines.append(f"\n{connected}/{total} conectado(s)")
        await status_msg.edit_text(
            "\n".join(lines), parse_mode=ParseMode.HTML
        )
    except Exception as e:
        log.error(f"[mcp] Erro no reconnect: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ <b>Erro no reconnect</b>\n\n<pre>{_escape(str(e)[:500])}</pre>",
            parse_mode=ParseMode.HTML,
        )


def _escape(text: str) -> str:
    """Escapa HTML para Telegram ParseMode.HTML."""
    return escape(str(text))
