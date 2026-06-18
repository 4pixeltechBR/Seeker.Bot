import logging
import asyncio
from src.core.execution.adapters.manager import register_adapter

log = logging.getLogger("seeker.execution.adapters.x_search")

def register():
    desc = (
        "5. BUSCA AVANÇADA NO X/TWITTER (X_SEARCH):\n"
        "   Use para buscar discussões, posts ou tendências em tempo real no X/Twitter.\n"
        "   Formato: `[X_SEARCH: \"sua query de busca aqui\"]`\n"
        "   Ou com filtros opcionais usando pipe:\n"
        "   `[X_SEARCH: \"query|allowed_handles_comma_separated|from_date|to_date\"]`\n"
        "   (Exemplo: `[X_SEARCH: \"AI agents|elonmusk,grok|2026-06-01|2026-06-11\"]`)\n"
    )

    async def execute_x_search(arg: str, response_text: str) -> str:
        try:
            from seeker_agent.tools.x_search_tool import x_search_tool
        except ImportError as ie:
            log.error(f"Erro ao importar x_search_tool: {ie}")
            return f"[ERRO: Ferramenta de busca no X indisponível devido a erro de dependências: {ie}]"

        query = arg
        allowed_handles = None
        from_date = ""
        to_date = ""

        if "|" in arg:
            parts = arg.split("|")
            query = parts[0].strip()
            if len(parts) > 1 and parts[1].strip():
                allowed_handles = [h.strip() for h in parts[1].split(",") if h.strip()]
            if len(parts) > 2:
                from_date = parts[2].strip()
            if len(parts) > 3:
                to_date = parts[3].strip()

        try:
            # Executa em thread pool para evitar bloqueio do event loop
            res = await asyncio.to_thread(
                x_search_tool,
                query=query,
                allowed_x_handles=allowed_handles,
                from_date=from_date,
                to_date=to_date
            )
            return res
        except Exception as e:
            log.error(f"Falha na busca do X: {e}")
            return f"[ERRO ao buscar no X: {e}]"

    register_adapter("x_search", "X_SEARCH", desc, execute_x_search)
