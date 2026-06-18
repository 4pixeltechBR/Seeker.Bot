import json
import asyncio
import logging
from src.core.execution.adapters.manager import register_adapter

log = logging.getLogger("seeker.execution.adapters.mcp")
_initialized = False

def register():
    desc = (
        "3. MODEL CONTEXT PROTOCOL (MCP):\n"
        "   Use para executar ferramentas em servidores MCP externos configurados (ex: github, filesystem).\n"
        "   Chamar ferramenta: `[MCP_CALL: \"server_name|tool_name|args_json\"]`\n"
        "   (Exemplo: `[MCP_CALL: \"github|search_repositories|{\\\"query\\\": \\\"seeker\\\"}\"]`)\n"
    )
    
    async def execute_mcp_call(arg: str, response_text: str) -> str:
        if "|" not in arg:
            return "[ERRO: Formato inválido para MCP_CALL. Use 'server_name|tool_name|args_json']"
        
        parts = arg.split("|", 2)
        if len(parts) < 3:
            return "[ERRO: Formato inválido para MCP_CALL. Use 'server_name|tool_name|args_json']"
            
        server_name, tool_name, args_json = parts
        
        try:
            args_dict = json.loads(args_json) if args_json.strip() else {}
        except Exception as je:
            return f"[ERRO: Falha ao decodificar JSON de argumentos: {je}]"
            
        try:
            from seeker_agent.tools.mcp_tool import _make_tool_handler
            # Cria o handler dinâmico
            handler = _make_tool_handler(server_name, tool_name, tool_timeout=120)
            
            # Executa o handler (que é síncrono e roda no loop de background do MCP)
            # Como ele é síncrono, rodamos com asyncio.to_thread para evitar trancar o bot
            result_str = await asyncio.to_thread(handler, args_dict)
            return result_str
        except Exception as e:
            log.error(f"Erro ao executar ferramenta MCP {server_name}.{tool_name}: {e}")
            return f"[ERRO ao executar ferramenta MCP: {e}]"

    register_adapter("mcp", "MCP_CALL", desc, execute_mcp_call)

async def start_mcp():
    """Inicializa as conexões com os servidores MCP em background."""
    global _initialized
    if not _initialized:
        log.info("Inicializando conexões com os servidores MCP configurados...")
        try:
            from seeker_agent.tools.mcp_tool import discover_mcp_tools
            # discover_mcp_tools roda de forma síncrona
            await asyncio.to_thread(discover_mcp_tools)
            log.info("Conexões MCP inicializadas.")
            _initialized = True
        except Exception as e:
            log.warning(f"Erro ao inicializar servidores MCP (fail-open): {e}")
