"""
Seeker.Bot — Common Exception Handling Patterns
src/core/exceptions_handler.py

Centralized exception handling patterns for consistent error reporting
across the bot, following the 10/10 code quality strategy.

Pattern guidelines:
  1. Catch specific exception types (not generic Exception)
  2. Log with exc_info=True for full stack traces
  3. Provide user-friendly error messages
  4. Include context information in logs
  5. Re-raise critical exceptions after logging
"""

import logging
from typing import Optional, Callable, Any, TypeVar
import asyncio

log = logging.getLogger("seeker.exceptions")

T = TypeVar('T')


class CommandExecutionError(Exception):
    """Command execution failed with user-friendly message"""
    pass


class PipelineError(Exception):
    """Pipeline operation failed"""
    pass


class ServiceError(Exception):
    """External service operation failed"""
    pass


async def safe_command_execution(
    operation: Callable,
    operation_name: str,
    default_response: str = "❌ Erro ao executar operação",
    timeout: float = 30.0,
) -> tuple[bool, str]:
    """
    Executa operação com tratamento de exceção padronizado.

    Padrão seguro para handlers Telegram:
      success, response = await safe_command_execution(
          pipeline.some_operation(),
          "email_test",
          "❌ Erro ao testar email"
      )
      await message.answer(response, parse_mode=ParseMode.HTML)

    Args:
        operation: Callable ou coroutine a executar
        operation_name: Nome da operação (para logging)
        default_response: Resposta padrão em caso de erro
        timeout: Timeout em segundos

    Returns:
        (success: bool, response: str)
    """
    try:
        # Se é callable mas não coroutine, chamar
        if callable(operation) and not asyncio.iscoroutine(operation):
            result = await asyncio.wait_for(
                asyncio.create_task(operation()) if asyncio.iscoroutinefunction(operation) else
                asyncio.to_thread(operation),
                timeout=timeout
            )
        else:
            result = await asyncio.wait_for(operation, timeout=timeout)

        return True, result if isinstance(result, str) else "✅ Operação concluída"

    except asyncio.TimeoutError:
        log.warning(
            f"[{operation_name}] Timeout após {timeout}s",
            extra={"context": operation_name}
        )
        return False, f"⏱️ Timeout: operação demorou mais de {timeout}s"

    except ValueError as e:
        log.error(
            f"[{operation_name}] Erro de validação: {e}",
            exc_info=True,
            extra={"context": operation_name, "error_type": "ValueError"}
        )
        return False, f"❌ Erro de validação: {str(e)[:100]}"

    except KeyError as e:
        log.error(
            f"[{operation_name}] Chave não encontrada: {e}",
            exc_info=True,
            extra={"context": operation_name, "error_type": "KeyError"}
        )
        return False, f"❌ Erro de configuração: chave não encontrada"

    except AttributeError as e:
        log.error(
            f"[{operation_name}] Atributo não encontrado: {e}",
            exc_info=True,
            extra={"context": operation_name, "error_type": "AttributeError"}
        )
        return False, f"❌ Erro de estrutura: recurso não disponível"

    except asyncio.CancelledError:
        log.info(f"[{operation_name}] Operação cancelada")
        return False, "⚠️ Operação cancelada"

    except (FileNotFoundError, OSError) as e:
        log.error(
            f"[{operation_name}] Erro de I/O: {e}",
            exc_info=True,
            extra={"context": operation_name, "error_type": type(e).__name__}
        )
        return False, "❌ Erro ao acessar arquivo ou recurso"

    except Exception as e:
        # Catch-all para exceções inesperadas
        log.critical(
            f"[{operation_name}] Erro inesperado: {e}",
            exc_info=True,
            extra={"context": operation_name, "error_type": type(e).__name__}
        )
        return False, f"{default_response}: {str(e)[:80]}"


def handle_command_error(
    operation_name: str,
    user_facing_message: str = "❌ Erro ao executar operação",
) -> Callable:
    """
    Decorator para handlers Telegram que tratam exceções consistentemente.

    Uso:
      @handle_command_error("email_test", "❌ Erro ao testar email")
      async def cmd_email_test(message: Message):
          result = await pipeline.test_email()
          return "✅ Email testado com sucesso"
    """
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs) -> str:
            try:
                return await func(*args, **kwargs)

            except (ValueError, KeyError) as e:
                log.error(
                    f"[{operation_name}] Erro de validação/configuração: {e}",
                    exc_info=True
                )
                return f"{user_facing_message}: {str(e)[:100]}"

            except AttributeError as e:
                log.error(
                    f"[{operation_name}] Recurso não disponível: {e}",
                    exc_info=True
                )
                return f"{user_facing_message}: Recurso não configurado"

            except asyncio.TimeoutError:
                log.warning(f"[{operation_name}] Timeout na operação")
                return "⏱️ Timeout: a operação demorou muito tempo"

            except Exception as e:
                log.critical(
                    f"[{operation_name}] Erro inesperado: {e}",
                    exc_info=True
                )
                return f"{user_facing_message}"

        return wrapper
    return decorator
