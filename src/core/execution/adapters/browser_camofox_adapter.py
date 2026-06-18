import logging
from src.core.execution.adapters.manager import register_adapter

log = logging.getLogger("seeker.execution.adapters.browser_camo")

def register():
    desc = (
        "1. NAVEGADOR CAMUFLADO ANTI-BOT (BROWSER_CAMO):\n"
        "   Use para navegar de forma evasiva e contornar proteções como Cloudflare/CAPTCHA.\n"
        "   Navegar: `[BROWSER_CAMO: \"http://url-alvo.com\"]`\n"
        "   Clicar: `[BROWSER_CAMO_CLICK: \"@ref\"]`\n"
        "   Digitar: `[BROWSER_CAMO_TYPE: \"@ref|seu texto aqui\"]`\n"
        "   Snapshot: `[BROWSER_CAMO_SNAPSHOT]`\n"
    )
    
    async def execute_browser_camo(arg: str, response_text: str) -> str:
        from seeker_agent.tools.browser_camofox import camofox_navigate
        return camofox_navigate(arg)

    async def execute_browser_camo_click(arg: str, response_text: str) -> str:
        from seeker_agent.tools.browser_camofox import camofox_click
        return camofox_click(arg)

    async def execute_browser_camo_type(arg: str, response_text: str) -> str:
        from seeker_agent.tools.browser_camofox import camofox_type
        if "|" not in arg:
            return "[ERRO: Formato inválido para BROWSER_CAMO_TYPE. Use 'ref|texto']"
        ref, text = arg.split("|", 1)
        return camofox_type(ref, text)

    async def execute_browser_camo_snapshot(arg: str, response_text: str) -> str:
        from seeker_agent.tools.browser_camofox import camofox_snapshot
        return camofox_snapshot()

    register_adapter("browser_camo", "BROWSER_CAMO", desc, execute_browser_camo)
    register_adapter("browser_camo", "BROWSER_CAMO_CLICK", "", execute_browser_camo_click)
    register_adapter("browser_camo", "BROWSER_CAMO_TYPE", "", execute_browser_camo_type)
    register_adapter("browser_camo", "BROWSER_CAMO_SNAPSHOT", "", execute_browser_camo_snapshot)
