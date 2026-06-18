import os
import sys
import logging
from typing import Dict, Any, Callable, Awaitable

# Localiza dinamicamente a pasta raiz do Seeker.Bot e injeta o caminho do seeker_agent no sys.path
bot_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
seeker_agent_dir = os.path.join(bot_root, "seeker_agent")
if seeker_agent_dir not in sys.path:
    sys.path.insert(0, seeker_agent_dir)
if bot_root not in sys.path:
    sys.path.insert(0, bot_root)

log = logging.getLogger("seeker.execution.adapters")

# Flags do .env
ENABLED_FLAGS = {
    "browser_camo": os.getenv("PORTED_BROWSER_CAMO_ENABLED", "true").lower() in ("true", "1", "yes"),
    "cronjob": os.getenv("PORTED_CRONJOB_ENABLED", "true").lower() in ("true", "1", "yes"),
    "mcp": os.getenv("PORTED_MCP_ENABLED", "true").lower() in ("true", "1", "yes"),
    "moa": os.getenv("PORTED_MOA_ENABLED", "true").lower() in ("true", "1", "yes"),
    "x_search": os.getenv("PORTED_X_SEARCH_ENABLED", "true").lower() in ("true", "1", "yes"),
    "media": os.getenv("PORTED_MEDIA_ENABLED", "true").lower() in ("true", "1", "yes"),
}

# Armazena os executores registrados
# Assinatura: func(arg, response_text) -> str
_executors: Dict[str, Callable[[str, str], Awaitable[str]]] = {}
_prompts: Dict[str, str] = {}

def register_adapter(name: str, tag: str, prompt_desc: str, executor: Callable[[str, str], Awaitable[str]]):
    """Registra dinamicamente um adaptador se ele estiver habilitado nas configurações."""
    if ENABLED_FLAGS.get(name, False):
        _executors[tag] = executor
        _prompts[tag] = prompt_desc
        log.info(f"Adaptador '{name}' registrado com sucesso sob a tag '{tag}'.")

def get_ported_tools_prompt() -> str:
    """Retorna o bloco de prompt explicativo para o LLM apenas com as ferramentas portadas ativas."""
    if not _prompts:
        return ""
    
    parts = ["\n━━━ FERRAMENTAS AVANÇADAS ADICIONAIS ━━━"]
    for tag, desc in _prompts.items():
        parts.append(desc)
    return "\n".join(parts)

def is_tag_registered(tag: str) -> bool:
    """Retorna se uma determinada tag de ferramenta portada está ativa e registrada."""
    return tag in _executors

from contextvars import ContextVar
active_session_id: ContextVar[str] = ContextVar("active_session_id", default="")

async def execute_ported_tool(tag: str, arg: str, response_text: str = "", session_id: str = "") -> str:
    """Executa a ferramenta associada à tag de forma assíncrona."""
    if tag not in _executors:
        raise ValueError(f"Ferramenta portada para a tag '{tag}' não está registrada ou ativa.")
    
    token = active_session_id.set(session_id)
    try:
        log.info(f"Executando ferramenta portada para a tag {tag} com argumento: '{arg}' e session_id: '{session_id}'")
        return await _executors[tag](arg, response_text)
    finally:
        active_session_id.reset(token)

def find_registered_tag(response_text: str):
    """
    Procura por qualquer uma das tags registradas no response_text.
    Se encontrar, retorna a tupla (tag, argumento).
    As tags podem estar no formato [TAG: "arg"] ou [TAG].
    """
    for tag in _executors.keys():
        tag_pattern = f"[{tag}:"
        tag_no_arg = f"[{tag}]"
        
        if tag_pattern in response_text:
            start_idx = response_text.find(tag_pattern) + len(tag_pattern)
            end_idx = response_text.find("]", start_idx)
            if end_idx != -1:
                arg = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                return tag, arg
        elif tag_no_arg in response_text:
            return tag, ""
            
    return None

# Inicialização dos adaptadores dinâmicos
try:
    if ENABLED_FLAGS.get("browser_camo", False):
        from src.core.execution.adapters.browser_camofox_adapter import register
        register()
except Exception as e:
    log.warning(f"Erro ao carregar adaptador 'browser_camo': {e}")

try:
    if ENABLED_FLAGS.get("cronjob", False):
        from src.core.execution.adapters.cronjob_adapter import register
        register()
except Exception as e:
    log.warning(f"Erro ao carregar adaptador 'cronjob': {e}")

try:
    if ENABLED_FLAGS.get("mcp", False):
        from src.core.execution.adapters.mcp_adapter import register
        register()
except Exception as e:
    log.warning(f"Erro ao carregar adaptador 'mcp': {e}")

try:
    if ENABLED_FLAGS.get("moa", False):
        from src.core.execution.adapters.moa_adapter import register
        register()
except Exception as e:
    log.warning(f"Erro ao carregar adaptador 'moa': {e}")

try:
    if ENABLED_FLAGS.get("x_search", False):
        from src.core.execution.adapters.x_search_adapter import register
        register()
except Exception as e:
    log.warning(f"Erro ao carregar adaptador 'x_search': {e}")

try:
    if ENABLED_FLAGS.get("media", False):
        from src.core.execution.adapters.media_adapter import register
        register()
except Exception as e:
    log.warning(f"Erro ao carregar adaptador 'media': {e}")


async def start_background_tasks():
    """Inicia tarefas em background das ferramentas portadas (scheduler, MCP)."""
    if ENABLED_FLAGS.get("cronjob", False):
        try:
            from src.core.execution.adapters.cronjob_adapter import start_scheduler
            await start_scheduler()
        except Exception as e:
            log.warning(f"Erro ao iniciar background scheduler do cronjob: {e}")
            
    if ENABLED_FLAGS.get("mcp", False):
        try:
            from src.core.execution.adapters.mcp_adapter import start_mcp
            await start_mcp()
        except Exception as e:
            log.warning(f"Erro ao iniciar background MCP: {e}")
