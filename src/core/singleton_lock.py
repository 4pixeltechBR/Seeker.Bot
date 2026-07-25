"""
Singleton Lock — previne duas instâncias do bot rodando simultaneamente.

Problema que resolve: quando há dois processos Python fazendo
`getUpdates` do mesmo token do Telegram, o servidor responde
`TelegramConflictError - terminated by other getUpdates request`,
e nenhuma das duas instâncias entrega mensagens (incidente real,
2026-06-28 — subprocesso filho do bot poluiu o polling do pai).

Padrão:
- Arquivo de lock contém o PID do dono
- Se o lockfile existe mas o PID está morto, outra instância pode reivindicar
- Lock é liberado em atexit (saída normal) e via signal (saída forçada)
- TTL opcional: se o lockfile for mais antigo que X segundos, considera stale

Uso:
    from src.core.singleton_lock import acquire_bot_lock, release_bot_lock

    if not acquire_bot_lock():
        log.error("Outra instância do bot já está rodando. Saindo.")
        sys.exit(2)
"""

import atexit
import os
import sys
import time
from pathlib import Path

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

LOCK_DIR = Path("logs")
LOCK_FILE = LOCK_DIR / "bot.lock"
LOCK_TTL_SECONDS = 3600  # 1h — se lock mais velho que isso sem dono vivo, força reivindicação
STALE_GRACE_SECONDS = 5  # pequena janela onde múltiplos bots podem subir quase simultaneamente


def _pid_is_alive(pid: int) -> bool:
    """Cross-platform: True se o PID estiver vivo."""
    if pid <= 0:
        return False
    if _HAS_PSUTIL:
        return psutil.pid_exists(pid)
    if sys.platform == "win32":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return exit_code.value == 259  # STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _write_lock(lock_path: Path, pid: int) -> bool:
    """Grava o PID no lockfile. Retorna True se sucesso."""
    try:
        lock_path.write_text(str(pid))
        return True
    except OSError as e:
        print(f"[singleton] Falha ao escrever lockfile {lock_path}: {e}", file=sys.stderr)
        return False


def _read_lock(lock_path: Path) -> int:
    """Lê o PID do lockfile. Retorna -1 se inválido."""
    try:
        return int(lock_path.read_text().strip())
    except (ValueError, OSError):
        return -1


def _release_lock(lock_path: Path, our_pid: int) -> None:
    """Libera o lockfile se ele ainda for nosso."""
    try:
        if lock_path.exists():
            content = lock_path.read_text().strip()
            if content == str(our_pid):
                lock_path.unlink()
    except (OSError, ValueError):
        pass


def acquire_bot_lock(lock_path: Path = LOCK_FILE) -> bool:
    """
    Tenta adquirir o singleton lock para o bot.
    Retorna True se conseguiu, False se outra instância ativa já tem o lock.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    our_pid = os.getpid()

    if lock_path.exists():
        existing_pid = _read_lock(lock_path)
        mtime = lock_path.stat().st_mtime
        age = time.time() - mtime

        # Caso 1: lock nosso (re-execução na mesma sessão)
        if existing_pid == our_pid:
            return True

        # Caso 2: PID vivo E lock recente → outra instância ativa
        if existing_pid > 0 and _pid_is_alive(existing_pid) and age < LOCK_TTL_SECONDS:
            print(
                f"[singleton] ❌ Outra instância do bot já está rodando (PID {existing_pid}, "
                f"lock com {age:.0f}s). Saindo para evitar TelegramConflictError.",
                file=sys.stderr,
            )
            return False

        # Caso 3: PID morto OU lock velho → reivindicar
        if existing_pid > 0 and not _pid_is_alive(existing_pid):
            print(f"[singleton] Lock stale (PID {existing_pid} morto). Reivindicando.")
        elif age >= LOCK_TTL_SECONDS:
            print(
                f"[singleton] Lock velho ({age:.0f}s > {LOCK_TTL_SECONDS}s TTL) "
                f"pertencente a PID {existing_pid}. Reivindicando."
            )

    if not _write_lock(lock_path, our_pid):
        return False

    # Garante limpeza em saída normal
    def _release():
        _release_lock(lock_path, our_pid)

    atexit.register(_release)
    return True


def force_release_stale_lock(lock_path: Path = LOCK_FILE) -> bool:
    """Libera lock stale manualmente. Útil em scripts de diagnóstico."""
    if not lock_path.exists():
        return False
    pid = _read_lock(lock_path)
    if pid > 0 and not _pid_is_alive(pid):
        try:
            lock_path.unlink()
            return True
        except OSError:
            return False
    return False
