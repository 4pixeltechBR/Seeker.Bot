"""
seeker_nb_login.py — Helper robusto para autenticar NotebookLM no Seeker.Bot.

3 modos:
  1. attach  — Anexa ao Chrome já aberto (com --remote-debugging-port=9222)
  2. persist — Abre Chrome persistente novo (perfil em ~/.notebooklm/browser_profile)
  3. reset   — Limpa tudo e começa do zero

Uso (do terminal):
    .venv\\Scripts\\python.exe scripts\\seeker_nb_login.py attach
    .venv\\Scripts\\python.exe scripts\\seeker_nb_login.py persist
    .venv\\Scripts\\python.exe scripts\\seeker_nb_login.py reset
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def venv_python() -> str:
    root = Path(__file__).resolve().parent.parent
    py = root / ".venv" / "Scripts" / "python.exe"
    return str(py) if py.exists() else sys.executable


def storage_path() -> Path:
    return Path(os.environ.get("NOTEBOOKLM_HOME", Path.home() / ".notebooklm")) / "storage_state.json"


def browser_profile() -> Path:
    return Path(os.environ.get("NOTEBOOKLM_HOME", Path.home() / ".notebooklm")) / "browser_profile"


def is_authenticated() -> bool:
    if not storage_path().exists():
        return False
    cp = subprocess.run(
        [venv_python(), "-m", "notebooklm", "list"],
        capture_output=True, text=True, check=False,
    )
    return cp.returncode == 0


def validate_end_to_end() -> bool:
    test_title = "Seeker-Hello-World-DELETE-ME"
    print(f"\n  [Teste] Criando notebook dummy '{test_title}'...")
    cp = subprocess.run(
        [venv_python(), "-m", "notebooklm", "create", test_title],
        capture_output=True, text=True, check=False,
    )
    if cp.returncode != 0:
        print(f"  [FALHA] {cp.stderr.strip()[:300]}")
        return False
    print("  [OK] Notebook criado")

    cp = subprocess.run(
        [venv_python(), "-m", "notebooklm", "delete", test_title],
        capture_output=True, text=True, check=False,
    )
    if cp.returncode == 0:
        print("  [OK] Notebook removido")
    return True


def find_chrome_exe() -> str | None:
    """Encontra o executável do Chrome (não o Chromium do Playwright)."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        # Edge como fallback (mesmo motor)
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def is_cdp_port_open(port: int = 9222) -> bool:
    """Verifica se já existe Chrome com --remote-debugging-port."""
    try:
        import httpx
        r = httpx.get(f"http://localhost:{port}/json/version", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def mode_attach() -> int:
    """Anexa ao Chrome já aberto com remote-debugging."""
    from playwright.sync_api import sync_playwright

    port = 9222
    if not is_cdp_port_open(port):
        print(f"  [ERRO] Nenhum Chrome com --remote-debugging-port={port} aberto.")
        print()
        print("  Como abrir seu Chrome com esse modo:")
        print()
        chrome = find_chrome_exe()
        if not chrome:
            print("  Chrome/Edge não encontrado nos paths padrão.")
            return 1
        print(f"  1. Feche TODAS as janelas do Chrome.")
        print(f"  2. Abra PowerShell e rode:")
        print()
        print(f'     & "{chrome}" --remote-debugging-port={port} --remote-allow-origins=*')
        print()
        print(f"  3. Faça login no NotebookLM no Chrome que abriu.")
        print(f"  4. Volte aqui e rode:")
        print()
        print(f"     .venv\\Scripts\\python.exe scripts\\seeker_nb_login.py attach")
        return 1

    print(f"  [OK] Chrome com debug-port já está aberto.")
    print("  [..] Anexando...")

    storage = storage_path()
    storage.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{port}")
        contexts = browser.contexts
        if not contexts:
            print("  [ERRO] Nenhum contexto encontrado no Chrome.")
            return 1
        ctx = contexts[0]

        # Procura página do NotebookLM
        nb_page = None
        for page in ctx.pages:
            if "notebooklm.google.com" in page.url:
                nb_page = page
                break
        if not nb_page:
            print("  [..] NotebookLM não está aberto. Abrindo nova aba...")
            nb_page = ctx.new_page()
            nb_page.goto("https://notebooklm.google.com/", wait_until="domcontentloaded", timeout=30000)

        print(f"  [i] URL: {nb_page.url}")
        title = nb_page.title()
        print(f"  [i] Título: {title!r}")

        if "accounts.google.com" in nb_page.url or "Sign in" in title:
            print("  [ERRO] Você ainda não está logado no NotebookLM no Chrome.")
            print("         Faça login lá e rode este comando de novo.")
            return 1

        # Salva storage_state do contexto existente
        print(f"  [..] Salvando storage_state em {storage}...")
        try:
            ctx.storage_state(path=str(storage))
            storage.chmod(0o600)
            print(f"  [OK] Storage salvo ({storage.stat().st_size} bytes)")
        except Exception as e:
            print(f"  [ERRO] Ao salvar: {e}")
            return 1

        # NÃO fecha o Chrome — você quer continuar usando
        browser.close()  # só fecha a conexão CDP, não o Chrome
    return 0


def mode_persist() -> int:
    """Abre Chrome persistente novo (igual ao notebooklm login padrão)."""
    from playwright.sync_api import sync_playwright

    storage = storage_path()
    profile = browser_profile()
    storage.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)

    print(f"  [..] Abrindo Chrome persistente: {profile}")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--password-store=basic",
                "--no-sandbox",
            ],
            ignore_default_args=["--enable-automation"],
        )

        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto("https://notebooklm.google.com/", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  [aviso] Navegação: {e}")

        time.sleep(2)
        print(f"  [i] URL: {page.url}")
        print(f"  [i] Título: {page.title()!r}")

        if "accounts.google.com" in page.url or "Sign in" in page.title() or "Fazer login" in page.title():
            print()
            print("  ──────────────────────────────────────────────────────")
            print("  1. Faça login no Chrome que abriu (conta Google)")
            print("  2. Aguarde carregar o NotebookLM")
            print("  3. Volte aqui e pressione ENTER")
            print("  ──────────────────────────────────────────────────────")
            input("\n  [Pressione ENTER quando estiver logado] ")

        # Aguarda estabilizar
        print("  [..] Aguardando estabilização (até 30s)...")
        for _ in range(6):
            time.sleep(5)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                pass
            if "notebooklm.google.com" in page.url and "accounts.google.com" not in page.url:
                break

        if "notebooklm.google.com" not in page.url:
            print(f"  [ERRO] URL final {page.url} não é NotebookLM")
            try:
                context.close()
            except Exception:
                pass
            return 1

        print(f"  [..] Salvando storage_state...")
        try:
            context.storage_state(path=str(storage))
            storage.chmod(0o600)
            print(f"  [OK] Storage salvo ({storage.stat().st_size} bytes)")
        except Exception as e:
            print(f"  [ERRO] {e}")
            try:
                context.close()
            except Exception:
                pass
            return 1

        context.close()
    return 0


def mode_reset() -> int:
    """Limpa tudo e reinicia."""
    storage = storage_path()
    profile = browser_profile()
    removed = []
    if storage.exists():
        storage.unlink()
        removed.append(str(storage))
    if profile.exists():
        import shutil
        shutil.rmtree(profile, ignore_errors=True)
        removed.append(str(profile))
    print(f"  [OK] Removido: {', '.join(removed) if removed else 'nada'}")
    return 0


def print_header() -> None:
    print()
    print("┌────────────────────────────────────────────────────────────┐")
    print("│ Seeker.Bot — NotebookLM Helper                             │")
    print("└────────────────────────────────────────────────────────────┘")
    print()
    print(f"  Storage:  {storage_path()}")
    print(f"  Profile:  {browser_profile()}")
    print()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    print_header()

    # Status primeiro
    if is_authenticated():
        print("  [i] Status atual: ✅ AUTENTICADO")
        if validate_end_to_end():
            print()
            print("  ✅ Tudo pronto! Não precisa fazer login.")
            return 0
        print("  [!] Autenticação corrompida. Escolha um modo abaixo.")
    else:
        print("  [i] Status atual: ❌ NÃO AUTENTICADO")

    print()
    print("  Modos disponíveis:")
    print()
    print("    attach  → Conecta ao Chrome já aberto (USE ESTE se já tem Chrome logado)")
    print("    persist → Abre Chrome persistente novo (login interativo)")
    print("    reset   → Limpa tudo")
    print()

    if not mode:
        mode = input("  Modo [attach/persist/reset]: ").strip().lower()

    print()
    if mode == "attach":
        rc = mode_attach()
    elif mode == "persist":
        rc = mode_persist()
    elif mode == "reset":
        rc = mode_reset()
        if rc == 0:
            print("\n  Agora rode: scripts\\seeker_nb_login.py persist")
        return rc
    else:
        print(f"  [ERRO] Modo desconhecido: {mode}")
        return 1

    if rc != 0:
        return rc

    print()
    if validate_end_to_end():
        print()
        print("  ✅ Autenticado com sucesso!")
        print(f"  Storage: {storage_path()}")
        return 0
    print()
    print("  ⚠️  Storage salvo mas validação falhou.")
    return 1


if __name__ == "__main__":
    sys.exit(main())