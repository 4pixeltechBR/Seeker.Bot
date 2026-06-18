import logging
from src.core.execution.adapters.manager import register_adapter

log = logging.getLogger("seeker.execution.adapters.moa")

def register():
    desc = (
        "4. MIXTURE OF AGENTS (MOA):\n"
        "   Use para resolver problemas extremamente complexos de lógica, matemática ou algoritmos.\n"
        "   (Gera múltiplas chamadas na OpenRouter para auto-revisão e consolidação por um juiz).\n"
        "   Chamar MoA: `[MOA_QUERY: \"sua pergunta complexa aqui\"]`\n"
    )
    
    async def execute_moa(arg: str, response_text: str) -> str:
        from seeker_agent.tools.mixture_of_agents_tool import mixture_of_agents_tool
        return await mixture_of_agents_tool(user_prompt=arg)

    register_adapter("moa", "MOA_QUERY", desc, execute_moa)
