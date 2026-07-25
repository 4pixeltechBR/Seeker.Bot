"""
Seeker Unified Console — Orchestrator v2
Inicia seeker_watchdog.py em foreground (herda stdout/stderr)
e seeker_agent_watchdog.py em background (fail-silent).

O watchdog do bot é o processo principal. Se ele morrer,
o batch file cai para 'pause' e o usuário vê o que aconteceu.
Se o agent watchdog morrer, é ignorado (gateway opcional).
"""
import subprocess
import sys
import os
import signal


def main():
    print("=" * 50, flush=True)
    print("    SEEKER UNIFIED CONSOLE - Inicializando...    ", flush=True)
    print("=" * 50, flush=True)
    print("", flush=True)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(base_dir, ".venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        venv_python = sys.executable

    print(f"[!] Usando interpretador Python: {venv_python}", flush=True)

    # ── Agent Watchdog (background, fire-and-forget) ───────────────────
    p_agent = None
    try:
        p_agent = subprocess.Popen(
            [venv_python, "seeker_agent_watchdog.py"],
            cwd=base_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # CREATE_NEW_PROCESS_GROUP para não herdar Ctrl+C
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        print(f"[i] Agent Watchdog lançado em background (PID {p_agent.pid})", flush=True)
    except Exception as e:
        print(f"[!] Agent Watchdog não pôde ser iniciado: {e}", flush=True)

    # ── Bot Watchdog (foreground, herda console) ───────────────────────
    # O watchdog do bot HERDA stdout/stderr — o output do bot aparece
    # direto no terminal sem intermediário. Sem pipes, sem threads de
    # leitura, sem race conditions.
    print("[i] Iniciando Bot Watchdog em foreground...", flush=True)
    print("", flush=True)

    try:
        ret = subprocess.call(
            [venv_python, "seeker_watchdog.py"],
            cwd=base_dir,
            # Herda stdin/stdout/stderr — output direto no terminal
        )
        print(f"\n[!] Bot Watchdog encerrou (código: {ret})", flush=True)
    except KeyboardInterrupt:
        print("\n[!] Ctrl+C recebido — encerrando...", flush=True)
    finally:
        # Limpa agent watchdog se ainda estiver rodando
        if p_agent and p_agent.poll() is None:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(p_agent.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    p_agent.kill()
            except Exception:
                pass


if __name__ == "__main__":
    main()
