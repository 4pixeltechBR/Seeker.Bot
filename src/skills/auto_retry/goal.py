import time
import functools
import logging

# Configuração básica de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def retry_logic(max_attempts=3, delay=2):
    """Decorador para retry automático em caso de exceção."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    logger.warning(f"Tentativa {attempts}/{max_attempts} falhou em '{func.__name__}': {e}")
                    if attempts >= max_attempts:
                        logger.error(f"Número máximo de tentativas atingido para '{func.__name__}'.")
                        raise e
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

class Goal:
    def __init__(self):
        self.name = "AutoRetrySkill"

    @retry_logic(max_attempts=5, delay=1)
    def execute(self, task_context):
        """
        Executa a tarefa principal da skill com proteção de retry.
        """
        logger.info(f"Executando skill {self.name} com contexto: {task_context}")
        
        # Exemplo de lógica que poderia falhar (ex: requisição HTTP ou DB)
        # Se ocorrer um erro aqui, o decorador intercepta e tenta novamente
        
        return {
            "status": "success",
            "message": "Tarefa concluída com sucesso após verificações.",
            "context": task_context
        }