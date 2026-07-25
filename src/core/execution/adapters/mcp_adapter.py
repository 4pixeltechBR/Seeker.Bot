"""
Adapter MCP — tag [MCP_CALL] para o Active Loop do LLM.

Substitui o adapter antigo que dependia de `seeker_agent.tools.mcp_tool`
(removido). Agora usa o MCPClient oficial via stdio transport.

Uso pelo LLM no Active Loop:
  [MCP_CALL: "filesystem|list_directory|{\"path\": \"C:/Users/Victor/Documents\"}"]
  [MCP_CALL: "github|search_repositories|{\"query\": \"seeker\"}"]

Fail-open: se MCPClient indisponível, retorna mensagem de erro para o LLM.
"""

import json
import asyncio
import logging

from src.core.execution.adapters.manager import register_adapter

log = logging.getLogger("seeker.execution.adapters.mcp")


def register():
    desc = (
        "3. MODEL CONTEXT PROTOCOL (MCP):\n"
        "   Use para executar ferramentas em servidores MCP externos configurados\n"
        "   em config/mcp_servers.json (ex: filesystem, github, gitlab, etc.).\n"
        "   Chamar ferramenta: `[MCP_CALL: \"server_name|tool_name|args_json\"]`\n"
        "   (Exemplo: `[MCP_CALL: \"filesystem|read_file|{\\\"path\\\": \\\"/tmp/x.txt\\\"}\"]`)\n"
        "   (Exemplo: `[MCP_CALL: \"github|search_repositories|{\\\"query\\\": \\\"seeker\\\"}\"]`)\n"
    )

    async def execute_mcp_call(arg: str, response_text: str) -> str:
        if "|" not in arg:
            return (
                "[ERRO: Formato inválido para MCP_CALL. Use "
                "'server_name|tool_name|args_json']"
            )

        parts = arg.split("|", 2)
        if len(parts) < 3:
            return (
                "[ERRO: Formato inválido para MCP_CALL. Use "
                "'server_name|tool_name|args_json']"
            )

        server_name, tool_name, args_json = parts

        try:
            args_dict = json.loads(args_json) if args_json.strip() else {}
        except Exception as je:
            return f"[ERRO: Falha ao decodificar JSON de argumentos: {je}]"

        try:
            from src.core.execution.mcp_client import MCPClient

            client = MCPClient.get()
            # Garante que conectou (lazy init)
            if not client.connections:
                await client.connect_all()

            result_str = await client.call_tool(
                server_name, tool_name, args_dict
            )
            return result_str
        except TimeoutError as te:
            log.warning(f"[mcp] Timeout em {server_name}.{tool_name}: {te}")
            return f"[ERRO MCP: timeout] {te}"
        except Exception as e:
            log.error(
                f"[mcp] Erro ao executar {server_name}.{tool_name}: {e}",
                exc_info=True,
            )
            return f"[ERRO MCP: {type(e).__name__}] {e}"

    register_adapter("mcp", "MCP_CALL", desc, execute_mcp_call)


async def start_mcp():
    """Conecta aos servidores MCP em background no boot do Seeker."""
    try:
        from src.core.execution.mcp_client import MCPClient

        client = MCPClient.get()
        results = await client.connect_all()
        connected = sum(1 for s, v in results.items() if v == "connected")
        total = len(results)
        if total == 0:
            log.info("[mcp] Nenhum servidor MCP configurado em config/mcp_servers.json")
        else:
            log.info(
                f"[mcp] {connected}/{total} servidor(es) conectado(s): "
                f"{list(results.keys())}"
            )
    except Exception as e:
        log.warning(f"[mcp] Erro ao inicializar servidores (fail-open): {e}")
