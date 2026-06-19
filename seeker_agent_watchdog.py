"""
Seeker.Agent — Watchdog Process
seeker_agent_watchdog.py

Monitora o gateway do Seeker Agent (ex-SeekerAgent) e reinicia automaticamente se:
  - O processo morrer
  - O gateway travar (sem resposta / heartbeat ausente por N segundos)
  - Crash com exception fatal

Uso: python seeker_agent_watchdog.py
"""

import atexit
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────
MAX_RESTARTS_PER_HOUR = 5  # Se reiniciar mais que isso em 1h, para (loop de crash)
RESTART_DELAY_SECONDS = 5  # Espera antes de reiniciar
CRASH_LOOP_COOLDOWN = 300  # 5 min de pausa se atingir MAX_RESTARTS
# Resolvendo caminhos base
BASE_DIR = Path(__file__).parent.resolve()
SEEKER_AGENT_DIR = BASE_DIR / "seeker_agent"

LOG_FILE = str(BASE_DIR / "logs" / "agent_watchdog.log")
GATEWAY_LOG_FILE = str(BASE_DIR / "logs" / "agent_gateway.log")

# Carregando a home do agente para localizar o heartbeat
AGENT_HOME = Path.home() / ".seeker_agent"
ENV_PATH = SEEKER_AGENT_DIR / ".env"
if ENV_PATH.exists():
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("SEEKER_HOME="):
                    AGENT_HOME = Path(line.split("=")[1].strip().strip('"').strip("'"))
                    break
    except Exception:
        pass

HEARTBEAT_FILE = AGENT_HOME / "logs" / "agent_heartbeat.txt"
HEARTBEAT_TIMEOUT = 300  # 5 minutos sem heartbeat = travado (heartbeat bate a cada 60s)
LOCKFILE = str(BASE_DIR / "logs" / "agent_watchdog.lock")

# ── Logging ─────────────────────────────────────────────────────────────
os.makedirs(str(BASE_DIR / "logs"), exist_ok=True)

# Garante saída UTF-8 no stdout do terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [agent-watchdog] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("agent-watchdog")

active_process = None
process_start_time = 0.0


def kill_stale_gateway_processes() -> None:
    """Mata processos python órfãos que rodam o gateway para evitar conflitos de portas."""
    if sys.platform == "win32":
        try:
            cmd = 'Get-CimInstance Win32_Process -Filter "name = \'python.exe\'" | ' \
                  'Where-Object {$_.CommandLine -like "*-m gateway.run*"} | ' \
                  'ForEach-Object { Stop-Process -Id $_.ProcessId -Force }'
            subprocess.run(["powershell", "-Command", cmd], capture_output=True)
            log.info("Processos orfaos do gateway antigos finalizados.")
        except Exception as e:
            log.warning(f"Erro ao limpar processos antigos no Windows: {e}")
    else:
        try:
            subprocess.run(["pkill", "-f", "python -m gateway.run"], capture_output=True)
            log.info("Processos orfaos do gateway no Unix finalizados.")
        except Exception:
            pass


def get_python_executable() -> str:
    """Retorna o executavel Python correto para o ambiente, priorizando o venv local."""
    windows_paths = [
        BASE_DIR / ".venv" / "Scripts" / "python.exe",
        BASE_DIR / "venv" / "Scripts" / "python.exe",
    ]
    unix_paths = [
        BASE_DIR / ".venv" / "bin" / "python",
        BASE_DIR / "venv" / "bin" / "python",
    ]
    
    paths_to_check = windows_paths if sys.platform == "win32" else unix_paths
    
    for path in paths_to_check:
        if path.exists():
            log.info(f"Venv local resolvida: {path}")
            return str(path)
            
    log.warning(f"Nenhuma venv local encontrada. Usando o interpretador ativo: {sys.executable}")
    return sys.executable


def is_gateway_frozen() -> bool:
    """Verifica se o gateway esta travado via arquivo de heartbeat."""
    hb_path = Path(HEARTBEAT_FILE)
    if not hb_path.exists():
        if process_start_time > 0.0 and (time.time() - process_start_time > 180.0):
            log.warning("Gateway falhou em criar o heartbeat inicial apos 180s.")
            return True
        return False

    try:
        last_beat = hb_path.stat().st_mtime
        elapsed = time.time() - last_beat
        if elapsed > HEARTBEAT_TIMEOUT:
            log.warning(f"Gateway heartbeat ausente ha {elapsed:.0f}s (limite: {HEARTBEAT_TIMEOUT}s)")
            return True
    except Exception:
        pass
    return False


def tail_log(n: int = 20) -> str:
    """Retorna as ultimas N linhas do log do gateway."""
    try:
        with open(GATEWAY_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return "".join(lines[-n:])
    except Exception:
        return "(log nao disponivel)"


def reset_heartbeat() -> None:
    """Remove o arquivo de heartbeat antigo antes de iniciar."""
    hb_path = Path(HEARTBEAT_FILE)
    if hb_path.exists():
        try:
            hb_path.unlink()
            log.info("Heartbeat file resetado antes do boot.")
        except Exception as e:
            log.warning(f"Erro ao resetar heartbeat: {e}")


import threading

def log_stream(stream, log_file_path):
    """Lê a saída do subprocesso e espelha tanto no console quanto no arquivo de log."""
    try:
        with open(log_file_path, "a", encoding="utf-8", errors="replace") as f:
            for line in iter(stream.readline, ""):
                sys.stdout.write(line)
                sys.stdout.flush()
                f.write(line)
                f.flush()
    except Exception:
        pass

def run_gateway() -> subprocess.Popen:
    """Inicia o processo do gateway."""
    global active_process, process_start_time
    
    kill_stale_gateway_processes()
    reset_heartbeat()

    python = get_python_executable()
    log.info(f"Iniciando Seeker Agent Gateway: {python} -m gateway.run")

    os.makedirs(os.path.dirname(GATEWAY_LOG_FILE), exist_ok=True)

    proc = subprocess.Popen(
        [python, "-m", "gateway.run", "-v"],
        cwd=str(SEEKER_AGENT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    log.info(f"Gateway iniciado — PID: {proc.pid}")

    # Thread para ler a saída do gateway e espelhar no console + arquivo de log
    t = threading.Thread(target=log_stream, args=(proc.stdout, GATEWAY_LOG_FILE), daemon=True)
    t.start()

    active_process = proc
    process_start_time = time.time()
    return proc


def _pid_is_alive(pid: int) -> bool:
    """True se o PID esta vivo."""
    if pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def acquire_singleton_lock() -> bool:
    """Garante apenas um watchdog rodando por vez."""
    lock_path = Path(LOCKFILE)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        try:
            existing_pid = int(lock_path.read_text().strip())
        except (ValueError, OSError):
            existing_pid = -1

        if existing_pid > 0 and _pid_is_alive(existing_pid):
            log.error(f"Outro watchdog do agente ja esta rodando (PID {existing_pid}). Lock em {LOCKFILE}. Saindo.")
            return False
        log.warning(f"Lock stale encontrado (PID {existing_pid} morto). Reivindicando.")

    try:
        lock_path.write_text(str(os.getpid()))
    except OSError as e:
        log.error(f"Falha ao escrever lockfile {LOCKFILE}: {e}")
        return False

    def _release():
        try:
            if lock_path.exists():
                content = lock_path.read_text().strip()
                if content == str(os.getpid()):
                    lock_path.unlink()
        except Exception:
            pass

        global active_process
        if active_process and active_process.poll() is None:
            try:
                log.info(f"Finalizando gateway ativo (PID {active_process.pid}) no shutdown do watchdog.")
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(active_process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    active_process.kill()
            except Exception:
                pass

    atexit.register(_release)
    return True


def main():
    if not acquire_singleton_lock():
        sys.exit(2)

    log.info("=" * 60)
    log.info("Seeker.Agent Gateway Watchdog iniciado")
    log.info(f"PID: {os.getpid()}  |  Lockfile: {LOCKFILE}")
    log.info(f"Max restarts/hora: {MAX_RESTARTS_PER_HOUR}")
    log.info(f"Delay entre restarts: {RESTART_DELAY_SECONDS}s")
    log.info("=" * 60)

    restart_times = []
    total_restarts = 0

    while True:
        now = time.time()
        restart_times = [t for t in restart_times if now - t < 3600]

        if len(restart_times) >= MAX_RESTARTS_PER_HOUR:
            log.error(
                f"Crash loop detectado: {len(restart_times)} restarts na ultima hora. "
                f"Pausando {CRASH_LOOP_COOLDOWN}s..."
            )
            log.error(f"Ultimas linhas do log do gateway:\n{tail_log(30)}")
            time.sleep(CRASH_LOOP_COOLDOWN)
            restart_times.clear()
            continue

        proc = run_gateway()

        while True:
            ret = proc.poll()

            if ret is not None:
                uptime = time.time() - now
                log.warning(f"Gateway terminou com codigo {ret} apos {uptime:.0f}s. Total restarts: {total_restarts}")
                if ret != 0:
                    log.error(f"Ultimas linhas do log do gateway:\n{tail_log(20)}")
                break

            if is_gateway_frozen():
                log.error("Gateway travado (heartbeat ausente). Reiniciando...")
                if sys.platform == "win32":
                    try:
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        proc.kill()
                else:
                    proc.kill()
                proc.wait()
                break

            time.sleep(10)

        total_restarts += 1
        restart_times.append(time.time())
        log.info(f"Aguardando {RESTART_DELAY_SECONDS}s antes de reiniciar...")
        time.sleep(RESTART_DELAY_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Watchdog encerrado pelo usuario (Ctrl+C).")
        sys.exit(0)
