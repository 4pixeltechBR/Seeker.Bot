import asyncio
import logging
from src.core.execution.adapters.manager import register_adapter

log = logging.getLogger("seeker.execution.adapters.cronjob")
_scheduler_task = None

async def _cron_scheduler_loop():
    log.info("Iniciando loop do agendador de Cron em background...")
    from seeker_agent.cron.scheduler import tick
    # Aguarda 15 segundos antes de rodar o primeiro tick para garantir inicialização limpa do bot
    await asyncio.sleep(15)
    while True:
        try:
            log.debug("Executando tick do agendador Cron...")
            # Roda o tick em uma thread separada para evitar bloquear o event loop assíncrono
            await asyncio.to_thread(tick, verbose=False)
        except Exception as e:
            log.error(f"Erro ao executar tick do agendador Cron: {e}")
        await asyncio.sleep(60)

async def start_scheduler():
    global _scheduler_task
    if _scheduler_task is None:
        _scheduler_task = asyncio.create_task(_cron_scheduler_loop())
        log.info("Scheduler do Cron iniciado com sucesso.")

def register():
    desc = (
        "2. AGENDADOR DE TAREFAS PERSISTENTE (CRONJOB):\n"
        "   Use para agendar tarefas que devem rodar recorrentemente em background.\n"
        "   Criar Job: `[CRON_CREATE: \"schedule|prompt\"]`\n"
        "   (Exemplo: `[CRON_CREATE: \"every 2h|Busque novidades sobre IA\"]`)\n"
        "   Listar Jobs: `[CRON_LIST]`\n"
        "   Remover Job: `[CRON_REMOVE: \"job_id\"]`\n"
        "   Pausar Job: `[CRON_PAUSE: \"job_id\"]`\n"
        "   Retomar Job: `[CRON_RESUME: \"job_id\"]`\n"
    )
    
    async def execute_cron_create(arg: str, response_text: str) -> str:
        from seeker_agent.tools.cronjob_tools import cronjob
        from src.core.execution.adapters.manager import active_session_id
        if "|" not in arg:
            return "[ERRO: Formato inválido para CRON_CREATE. Use 'schedule|prompt']"
        schedule, prompt = arg.split("|", 1)
        
        session_id = active_session_id.get()
        deliver = "local"
        if session_id:
            chat_id = session_id.replace("telegram:", "")
            if chat_id.isdigit() or (chat_id.startswith("-") and chat_id[1:].isdigit()):
                deliver = f"telegram:{chat_id}"
                
        return cronjob(action="create", schedule=schedule, prompt=prompt, deliver=deliver)

    async def execute_cron_list(arg: str, response_text: str) -> str:
        from seeker_agent.tools.cronjob_tools import cronjob
        return cronjob(action="list")

    async def execute_cron_remove(arg: str, response_text: str) -> str:
        from seeker_agent.tools.cronjob_tools import cronjob
        return cronjob(action="remove", job_id=arg)

    async def execute_cron_pause(arg: str, response_text: str) -> str:
        from seeker_agent.tools.cronjob_tools import cronjob
        return cronjob(action="pause", job_id=arg)

    async def execute_cron_resume(arg: str, response_text: str) -> str:
        from seeker_agent.tools.cronjob_tools import cronjob
        return cronjob(action="resume", job_id=arg)

    register_adapter("cronjob", "CRON_CREATE", desc, execute_cron_create)
    register_adapter("cronjob", "CRON_LIST", "", execute_cron_list)
    register_adapter("cronjob", "CRON_REMOVE", "", execute_cron_remove)
    register_adapter("cronjob", "CRON_PAUSE", "", execute_cron_pause)
    register_adapter("cronjob", "CRON_RESUME", "", execute_cron_resume)
