import asyncio
import logging
import os
import subprocess
import sys

log = logging.getLogger("seeker.execution.sandbox")

DOCKER_DESKTOP_PATH = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"

async def is_docker_running() -> bool:
    """Verifica se o daemon do Docker está ativo executando 'docker ps'."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "ps",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        return proc.returncode == 0
    except Exception:
        return False

async def ensure_docker_running() -> bool:
    """Garante que o Docker está rodando. Se desativado, inicia o Docker Desktop."""
    if await is_docker_running():
        return True

    if sys.platform != "win32":
        log.warning("[sandbox] Docker inativo e SO não é Windows. Impossível auto-iniciar.")
        return False

    if not os.path.exists(DOCKER_DESKTOP_PATH):
        log.error(f"[sandbox] Docker Desktop não encontrado no caminho padrão: {DOCKER_DESKTOP_PATH}")
        return False

    log.info("[sandbox] Docker inativo. Iniciando Docker Desktop automaticamente...")
    try:
        # Abre o Docker Desktop de forma assíncrona/desacoplada
        subprocess.Popen(
            [DOCKER_DESKTOP_PATH],
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        log.error(f"[sandbox] Falha ao invocar Docker Desktop: {e}")
        return False

    # Polling de conectividade (timeout de 60 segundos)
    for attempt in range(1, 13):
        await asyncio.sleep(5)
        log.info(f"[sandbox] Aguardando Docker daemon (tentativa {attempt}/12)...")
        if await is_docker_running():
            log.info("[sandbox] Docker daemon conectado com sucesso!")
            return True

    log.error("[sandbox] Timeout: Docker daemon não respondeu em 60 segundos.")
    return False

async def execute_in_sandbox(code_content: str, timeout: float = 30.0) -> str:
    """
    Executa um script Python isoladamente em um container Docker python:3.10-slim.
    Passa o código via stdin para evitar problemas de montagem de volumes no Windows.
    """
    # 1. Garante que o Docker está respondendo
    docker_ok = await ensure_docker_running()
    if not docker_ok:
        log.warning("[sandbox] Docker indisponível. Abortando execução sandboxed.")
        raise RuntimeError("Docker daemon indisponível para sandboxing seguro.")

    log.info("[sandbox] Iniciando container seguro para execução de código...")
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "run", "--rm", "-i", "--net=none", "python:3.10-slim", "python",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=code_content.encode("utf-8")),
                timeout=timeout
            )
            out_str = stdout.decode("utf-8", errors="replace")
            err_str = stderr.decode("utf-8", errors="replace")
            
            if proc.returncode == 0:
                return out_str
            else:
                return f"Erro de Execução (código {proc.returncode}):\n{err_str}\nSaída:\n{out_str}"
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return f"Erro: Tempo limite de execução excedido ({timeout}s)."
            
    except Exception as e:
        log.error(f"[sandbox] Falha ao rodar container: {e}")
        return f"Erro de infraestrutura do sandbox: {e}"
