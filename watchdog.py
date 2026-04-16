"""
Seeker.Bot — Watchdog Process
watchdog.py

Monitora o bot principal e reinicia automaticamente se:
  - O processo morrer
  - O bot travar (sem resposta por N segundos)
  - Crash com exception fatal

Uso: python watchdog.py
     (sempre rodar esse, nunca o bot diretamente em produção)
"""

import asyncio
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────
MAX_RESTARTS_PER_HOUR = 5       # Se reiniciar mais que isso em 1h, para (loop de crash)
RESTART_DELAY_SECONDS = 5       # Espera antes de reiniciar (deixa SO liberar portas)
CRASH_LOOP_COOLDOWN   = 300     # 5 min de pausa se atingir MAX_RESTARTS
LOG_FILE              = "logs/watchdog.log"
BOT_LOG_FILE          = "logs/seeker.log"
HEARTBEAT_FILE        = "logs/bot_heartbeat.txt"  # Bot escreve aqui periodicamente
HEARTBEAT_TIMEOUT     = 600     # 10 min sem heartbeat = bot travado

# ── Logging ─────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchdog] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("watchdog")


def get_python_executable() -> str:
    """Retorna o executável Python correto para o ambiente."""
    return sys.executable


def is_bot_frozen() -> bool:
    """
    Verifica se o bot está travado via arquivo de heartbeat.
    O bot escreve nesse arquivo periodicamente (a cada ciclo do scheduler).
    Se passou mais de HEARTBEAT_TIMEOUT sem atualização, está travado.
    """
    hb_path = Path(HEARTBEAT_FILE)
    if not hb_path.exists():
        return False  # Sem heartbeat = funcionalidade não implementada ainda, ignora

    try:
        last_beat = hb_path.stat().st_mtime
        elapsed = time.time() - last_beat
        if elapsed > HEARTBEAT_TIMEOUT:
            log.warning(f"Bot heartbeat ausente há {elapsed:.0f}s (limite: {HEARTBEAT_TIMEOUT}s)")
            return True
    except Exception:
        pass

    return False


def tail_log(n: int = 20) -> str:
    """Retorna as últimas N linhas do log do bot."""
    try:
        with open(BOT_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return "".join(lines[-n:])
    except Exception:
        return "(log não disponível)"


def run_bot() -> subprocess.Popen:
    """Inicia o processo do bot e retorna o Popen."""
    python = get_python_executable()
    log.info(f"Iniciando bot: {python} -m src")

    proc = subprocess.Popen(
        [python, "-m", "src"],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    log.info(f"Bot iniciado — PID: {proc.pid}")
    return proc


def watch_output(proc: subprocess.Popen) -> None:
    """Loga saída do processo bot em tempo real."""
    if proc.stdout:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                print(line)  # Aparece no terminal do watchdog também


def main():
    log.info("=" * 60)
    log.info("Seeker.Bot Watchdog iniciado")
    log.info(f"Max restarts/hora: {MAX_RESTARTS_PER_HOUR}")
    log.info(f"Delay entre restarts: {RESTART_DELAY_SECONDS}s")
    log.info("=" * 60)

    restart_times: list[float] = []
    total_restarts = 0
    start_time = time.time()

    while True:
        # ── Limpa restarts com mais de 1h ──────────────────────────────
        now = time.time()
        restart_times = [t for t in restart_times if now - t < 3600]

        # ── Verifica crash loop ────────────────────────────────────────
        if len(restart_times) >= MAX_RESTARTS_PER_HOUR:
            log.error(
                f"⚠️ Crash loop detectado: {len(restart_times)} restarts na última hora. "
                f"Pausando {CRASH_LOOP_COOLDOWN}s antes de tentar novamente..."
            )
            log.error(f"Últimas linhas do log:\n{tail_log(30)}")
            time.sleep(CRASH_LOOP_COOLDOWN)
            restart_times.clear()
            continue

        # ── Inicia bot ─────────────────────────────────────────────────
        proc = run_bot()

        # ── Thread separada para logar output ─────────────────────────
        import threading
        output_thread = threading.Thread(target=watch_output, args=(proc,), daemon=True)
        output_thread.start()

        # ── Loop de monitoramento ──────────────────────────────────────
        while True:
            # Verifica se o processo ainda está vivo
            ret = proc.poll()

            if ret is not None:
                # Processo terminou
                uptime = time.time() - now
                log.warning(
                    f"Bot terminou com código {ret} após {uptime:.0f}s. "
                    f"Total de restarts: {total_restarts}"
                )
                if ret != 0:
                    log.error(f"Últimas linhas do log:\n{tail_log(20)}")
                break

            # Verifica heartbeat (bot travado)
            if is_bot_frozen():
                log.error("Bot parece travado (heartbeat ausente). Matando processo...")
                proc.kill()
                proc.wait()
                break

            time.sleep(10)  # Verifica a cada 10 segundos

        # ── Preparação para restart ────────────────────────────────────
        total_restarts += 1
        restart_times.append(time.time())

        log.info(f"Aguardando {RESTART_DELAY_SECONDS}s antes de reiniciar...")
        time.sleep(RESTART_DELAY_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Watchdog encerrado pelo usuário (Ctrl+C).")
        sys.exit(0)
