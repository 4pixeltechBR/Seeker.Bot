"""
react_retry — ReAct retry com observation.

Padrão da skill ai-agents-architect: quando o agente erra, em vez de
devolver a exception crua, repassa o erro como observation para a
próxima iteração com mensagem estruturada.

Implementação minimal: se uma chamada (LLM, tool, etc) lança exception,
anexa a mensagem de erro como contexto e tenta novamente. Limita a
MAX_REACT_RETRIES para evitar loops infinitos.

Uso:
    from src.core.react_retry import with_react_retry

    async def minha_funcao(arg, session_id=None):
        return await invoke_with_fallback(...)

    result = await with_react_retry(
        minha_funcao,
        arg="query",
        session_id=session_id,
        max_retries=2,
    )
"""

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

log = logging.getLogger("seeker.react_retry")

# Erros que merecem retry (transientes). Erros fatais (PermissionError,
# ValueError sem contexto) NÃO devem ser retentados.
RETRYABLE_EXCEPTIONS = (
    asyncio.TimeoutError,
    ConnectionError,
    ConnectionResetError,
    ConnectionRefusedError,
    OSError,  # inclui socket errors
)


class ReactRetryExhausted(Exception):
    """Levantada quando max_retries é atingido sem sucesso."""

    def __init__(self, original_error: Exception, attempts: int):
        self.original_error = original_error
        self.attempts = attempts
        super().__init__(
            f"ReAct retry exhausted após {attempts} tentativas. "
            f"Último erro: {type(original_error).__name__}: {original_error}"
        )


async def with_react_retry(
    func: Callable[..., Awaitable[Any]],
    *args,
    max_retries: int = 2,
    backoff_base: float = 1.5,
    session_id: str = "unknown",
    **kwargs,
) -> Any:
    """
    Executa `func(*args, **kwargs)` com retry exponencial em erros transientes.

    Args:
        func: callable async.
        max_retries: número de retries APÓS a primeira tentativa (total = max_retries + 1).
        backoff_base: base do exponential backoff. Primeira espera = backoff_base^0 = 1s.
        session_id: para logging.

    Returns:
        O resultado de func.

    Raises:
        ReactRetryExhausted: se max_retries atingido.
        Exception: a exception original se não for retryable.
    """
    last_error = None
    total_attempts = max_retries + 1

    for attempt in range(1, total_attempts + 1):
        try:
            result = await func(*args, **kwargs)
            if attempt > 1:
                log.info(
                    f"[react_retry:{session_id}] Sucesso após {attempt} tentativas "
                    f"(recuperado de {type(last_error).__name__ if last_error else 'N/A'})"
                )
            return result
        except Exception as e:
            last_error = e
            is_last = attempt == total_attempts
            is_retryable = isinstance(e, RETRYABLE_EXCEPTIONS)

            if is_last or not is_retryable:
                if not is_retryable and attempt == 1:
                    # Erro não-retryable na primeira tentativa: propaga sem retry.
                    log.debug(
                        f"[react_retry:{session_id}] Erro não-retryable: "
                        f"{type(e).__name__}: {e}"
                    )
                    raise
                log.warning(
                    f"[react_retry:{session_id}] Falha na tentativa {attempt}/{total_attempts}: "
                    f"{type(e).__name__}: {e}"
                )
                raise ReactRetryExhausted(e, attempt) from e

            # Retry: loga o erro como observation e espera antes de tentar.
            wait = backoff_base ** (attempt - 1)
            log.warning(
                f"[react_retry:{session_id}] Observation: {type(e).__name__}: {e}. "
                f"Retry {attempt + 1}/{total_attempts} em {wait:.1f}s..."
            )
            await asyncio.sleep(wait)

    # Nunca deve chegar aqui, mas por segurança:
    raise ReactRetryExhausted(last_error, total_attempts) from last_error  # type: ignore
