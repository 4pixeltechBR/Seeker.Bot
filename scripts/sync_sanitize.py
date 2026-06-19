"""
Seeker.Bot — Sync Sanitizer
scripts/sync_sanitize.py

Pos-sync: garante que a copia publica (D:\\Seeker GitHub) nao tem
nenhuma referencia comercial residual depois de copiar E:\\Seeker.Bot.

O que faz:
  1. Remove diretorios comerciais que escaparam do robocopy (idempotente)
  2. Remove arquivos comerciais conhecidos (hunter_crew.py, sales.py)
  3. Patcha bot.py: remove BotCommands /scout, /crm e o bloco
     try/except setup_sales_handlers
  4. Patcha src/core/hierarchy/__init__.py e crews/__init__.py para
     nao referenciar hunter_crew
  5. Roda security scan — ABORTA com exit 1 se sobrar qualquer
     keyword comercial nos .py do working tree

Uso: python scripts/sync_sanitize.py "D:\\Seeker GitHub"
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path


# ============================================================
# Configuracao
# ============================================================

COMMERCIAL_DIRS = [
    "apps",
    "src/skills/seeker_sales",
    "src/skills/seeker_sales_week",
    "src/skills/show_leads_daily",
    "src/skills/event_map_scout",
    "src/skills/event_radar",
    "src/skills/viralx9",
    "src/skills/cortex",
    "src/skills/revenue_hunter",
    # NOTA: drive_manager NAO eh comercial — eh o cliente Google Drive (/drive command)
]

# Diretorios que NUNCA devem existir no repo publico — abortam o sync se aparecerem
SENSITIVE_DIRS = [
    "Credenciais",  # OAuth tokens, service accounts, etc
    "Credentials",
    "secrets",
    ".secrets",
]

# Arquivos sensiveis individuais (alem dos .gitignore patterns)
# OBS: NUNCA capturar .env.example/.sample/.template — sao docs validas
SENSITIVE_FILE_PATTERNS = [
    re.compile(r".*credentials\.json$", re.IGNORECASE),
    re.compile(r".*gcp[_-]oauth.*\.json$", re.IGNORECASE),
    re.compile(r".*service[_-]account.*\.json$", re.IGNORECASE),
    re.compile(r".*token.*\.json$", re.IGNORECASE),
    # .env, .env.local, .env.production etc — mas NAO .env.example/.sample/.template
    re.compile(r"^\.env$|^\.env\.(local|production|prod|dev|development|staging)$", re.IGNORECASE),
]

COMMERCIAL_FILES = [
    "src/core/hierarchy/crews/hunter_crew.py",
    "src/channels/telegram/commands/sales.py",
    "src/channels/telegram/commands/radar.py",
    "src/channels/telegram/commands/viralx9.py",
    "src/channels/telegram/bot_new.py",  # stale, ainda tem /scout e /crm
    "tests/test_event_bridge.py",
    "tests/test_month_enricher.py",
    "tests/test_opportunity_engine.py",
    "tests/test_event_radar_mapped.py",
    "tests/test_event_radar.py",
]

# Keywords proibidas no working tree publico
# (pattern, descricao curta)
COMMERCIAL_PATTERNS = [
    (r"\bseeker_sales\b", "seeker_sales identifier"),
    (r"\bseeker_sales_week\b", "seeker_sales_week identifier"),
    (r"\bevent_map_scout\b", "event_map_scout identifier"),
    (r"\bevent_radar\b", "event_radar identifier"),
    (r"\bviralx9\b", "viralx9 identifier"),
    (r"\bHunterCrew\b", "HunterCrew class"),
    (r"\bhunter_crew\b", "hunter_crew module"),
    (r"\bsetup_sales_handlers\b", "setup_sales_handlers function"),
    (r"\bdiscovery_matrix\b", "discovery_matrix module"),
    (r'BotCommand\(\s*command="/scout"', "/scout BotCommand"),
    (r'BotCommand\(\s*command="/scout_config"', "/scout_config BotCommand"),
    (r'BotCommand\(\s*command="/crm"', "/crm BotCommand"),
    (r'BotCommand\(\s*command="/radar"', "/radar BotCommand"),
    (r'BotCommand\(\s*command="/viralx9"', "/viralx9 BotCommand"),
    (r"\bscout_hunter_2_0\b", "scout_hunter_2_0 reference"),
]

# Dirs ignorados no security scan (cache, vendor, scripts de sync, etc)
SCAN_IGNORED_PARTS = {
    ".git", ".venv", "venv", "env", "__pycache__",
    ".vscode", ".idea", ".claude",
    "data", "logs", "scratch", "Credenciais",
    "node_modules", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "scripts",  # scripts de sync contem keywords como strings de exclusao
}


# ============================================================
# Pre-flight: deteccao e remocao de coisas sensiveis (credenciais)
# ============================================================

def purge_sensitive(root: Path) -> tuple[list[str], list[str]]:
    """
    Remove diretorios e arquivos sensiveis (credenciais, tokens, .env)
    que NUNCA devem existir no repo publico.

    Retorna (removed_dirs, removed_files).
    """
    removed_dirs: list[str] = []
    removed_files: list[str] = []

    # 1. Diretorios sensiveis no top-level (Credenciais/, secrets/, etc)
    for d in SENSITIVE_DIRS:
        p = root / d
        if p.exists() and p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            removed_dirs.append(d)

    # 2. Arquivos sensiveis em qualquer lugar (credentials.json, .env, etc)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SCAN_IGNORED_PARTS for part in path.parts):
            continue
        # Pula o proprio sanitizer (regex strings dao falso positivo)
        if path.name == "sync_sanitize.py":
            continue
        name = path.name
        if any(pat.match(name) for pat in SENSITIVE_FILE_PATTERNS):
            try:
                path.unlink()
                removed_files.append(path.relative_to(root).as_posix())
            except OSError:
                pass

    return removed_dirs, removed_files


# ============================================================
# Operacoes idempotentes
# ============================================================

def remove_commercial_dirs(root: Path) -> list[str]:
    removed = []
    for rel in COMMERCIAL_DIRS:
        p = root / rel
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            removed.append(rel)
    return removed


def remove_commercial_files(root: Path) -> list[str]:
    removed = []
    for rel in COMMERCIAL_FILES:
        p = root / rel
        if p.exists():
            p.unlink()
            removed.append(rel)
    return removed


# ============================================================
# Patcher: bot.py
# ============================================================

BOT_PY_PATCHES = [
    # /scout BotCommand (multi-linha)
    (
        re.compile(
            r'\s*BotCommand\(\s*command="/scout".*?\),?\s*\n',
            re.DOTALL,
        ),
        "\n",
    ),
    # /scout_config BotCommand
    (
        re.compile(
            r'\s*BotCommand\(\s*command="/scout_config".*?\),?\s*\n',
            re.DOTALL,
        ),
        "\n",
    ),
    # /crm BotCommand (single-line)
    (
        re.compile(
            r'\s*BotCommand\(\s*command="/crm".*?\),?\s*\n',
            re.DOTALL,
        ),
        "\n",
    ),
    # /radar BotCommand
    (
        re.compile(
            r'\s*BotCommand\(\s*command="/radar".*?\),?\s*\n',
            re.DOTALL,
        ),
        "\n",
    ),
    # /viralx9 BotCommand
    (
        re.compile(
            r'\s*BotCommand\(\s*command="/viralx9".*?\),?\s*\n',
            re.DOTALL,
        ),
        "\n",
    ),
    # try/except setup_sales_handlers
    (
        re.compile(
            r"\s*try:\s*\n"
            r"\s*from src\.channels\.telegram\.commands\.sales import setup_sales_handlers\s*\n"
            r"\s*\n?"
            r"\s*has_sales\s*=\s*True\s*\n"
            r"\s*except ImportError:\s*\n"
            r"\s*has_sales\s*=\s*False\s*\n",
            re.MULTILINE,
        ),
        "\n",
    ),
    # call to setup_sales_handlers
    (
        re.compile(
            r"\s*if has_sales:\s*\n\s*setup_sales_handlers\(dp, pipeline\)\s*\n",
            re.MULTILINE,
        ),
        "\n",
    ),
    # /scout linha em help text
    (
        re.compile(r'\s*"/scout — campanha B2B[^"]*"\s*\n', re.MULTILINE),
        "",
    ),
    # /crm linha em help text
    (
        re.compile(r'\s*"/crm — hist[oó]rico de leads[^"]*"\s*\n', re.MULTILINE),
        "",
    ),
    # Section header "Produção:" → "Utilitários:" (rotulo mais neutro pra repo publico)
    # OBS: o replacement usa r-string + double-backslash pra preservar literal "\n"
    # em vez de re.sub interpretar como newline real (que quebraria a string Python)
    (
        re.compile(r'"<b>🚀 Produção:</b>\\n"'),
        r'"<b>🚀 Utilitários:</b>\\n"',
    ),
    # try/except setup_radar_handlers
    (
        re.compile(
            r"\s*try:\s*\n"
            r"\s*from src\.channels\.telegram\.commands\.radar import setup_radar_handlers\s*\n"
            r"\s*setup_radar_handlers\(dp, pipeline\)\s*\n"
            r"\s*except ImportError:\s*\n"
            r"\s*pass\s*\n",
            re.MULTILINE,
        ),
        "\n",
    ),
    # try/except setup_viralx9_handlers
    (
        re.compile(
            r"\s*try:\s*\n"
            r"\s*from src\.channels\.telegram\.commands\.viralx9 import setup_viralx9_handlers\s*\n"
            r"\s*setup_viralx9_handlers\(dp, pipeline\)\s*\n"
            r"\s*except ImportError:\s*\n"
            r"\s*pass\s*\n",
            re.MULTILINE,
        ),
        "\n",
    ),
]


def patch_bot_py(path: Path) -> bool:
    if not path.exists():
        return False
    original = path.read_text(encoding="utf-8")
    content = original
    for pattern, replacement in BOT_PY_PATCHES:
        content = pattern.sub(replacement, content)
    if content != original:
        path.write_text(content, encoding="utf-8")
        return True
    return False


# ============================================================
# Patcher: analyst_crew.py — remove bloco Scout Hunter 2.0
# ============================================================

ANALYST_CREW_PATCHES = [
    # Remove bloco "3. Scout Hunter 2.0 - B2B Prospecting" e renumera o proximo
    (
        re.compile(
            r"\n3\. Scout Hunter 2\.0 - B2B Prospecting\n"
            r".*?└─ Expected Impact:.*?\n\n"
            r"4\. ",
            re.DOTALL,
        ),
        "\n3. ",
    ),
    # Remove qualquer linha solta com HunterCrew em comentarios
    (
        re.compile(r".*HunterCrew.*\n"),
        "",
    ),
    # Remove milestone "Scout 2.0"
    (
        re.compile(r"\s*□\s*\d+-\d+:\s*Scout 2\.0[^\n]*\n"),
        "",
    ),
]


def patch_analyst_crew(path: Path) -> bool:
    if not path.exists():
        return False
    original = path.read_text(encoding="utf-8")
    content = original
    for pattern, replacement in ANALYST_CREW_PATCHES:
        content = pattern.sub(replacement, content)
    if content != original:
        path.write_text(content, encoding="utf-8")
        return True
    return False


# ============================================================
# Patcher: hierarchy __init__ files
# ============================================================

def patch_hierarchy_init(root: Path) -> list[str]:
    patched = []
    targets = [
        root / "src/core/hierarchy/__init__.py",
        root / "src/core/hierarchy/crews/__init__.py",
    ]
    patterns = [
        re.compile(r"\s+hunter_crew,\s*\n"),
        re.compile(r'\s+"hunter_crew",\s*\n'),
        re.compile(r"\s*from \. import hunter_crew[^\n]*\n"),
    ]
    for path in targets:
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        content = original
        for pat in patterns:
            content = pat.sub("\n" if pat.pattern.endswith("\\n") else "", content)
        if content != original:
            path.write_text(content, encoding="utf-8")
            patched.append(str(path.relative_to(root)))
    return patched


def patch_skills_yaml(path: Path) -> bool:
    if not path.exists():
        return False
    original = path.read_text(encoding="utf-8")
    patterns = [
        re.compile(r"\s*seeker_sales:\s*[^\n]+\n"),
        re.compile(r"\s*seeker_sales_week:\s*[^\n]+\n"),
        re.compile(r"\s*show_leads_daily:\s*[^\n]+\n"),
    ]
    content = original
    for pat in patterns:
        content = pat.sub("", content)
    if content != original:
        path.write_text(content, encoding="utf-8")
        return True
    return False


# ============================================================
# Security scan — ULTIMA LINHA DE DEFESA
# ============================================================

def security_scan(root: Path) -> list[tuple[str, str, int]]:
    """
    Varre todo .py/.yaml/.md do working tree publico procurando
    keywords comerciais. Retorna lista de (arquivo, descricao, linha).
    Lista vazia = repo limpo.
    """
    issues: list[tuple[str, str, int]] = []
    extensions = {".py", ".yaml", ".yml", ".md", ".bat", ".toml", ".json"}
    target_dirs = ["src", "config", "tests"]
    import os

    # 1. Varre arquivos soltos na raiz do destino
    for path in root.iterdir():
        if path.is_file():
            if path.suffix not in extensions:
                continue
            if path.name == "sync_sanitize.py":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for pattern, label in COMMERCIAL_PATTERNS:
                for m in re.finditer(pattern, text):
                    line_no = text.count("\n", 0, m.start()) + 1
                    rel = path.relative_to(root).as_posix()
                    issues.append((rel, label, line_no))

    # 2. Varre pastas alvo do reposicao (src, config, tests)
    for target in target_dirs:
        dir_path = root / target
        if not dir_path.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(dir_path):
            dirnames[:] = [d for d in dirnames if d not in SCAN_IGNORED_PARTS]
            for fname in filenames:
                path = Path(dirpath) / fname
                if path.suffix not in extensions:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for pattern, label in COMMERCIAL_PATTERNS:
                    for m in re.finditer(pattern, text):
                        line_no = text.count("\n", 0, m.start()) + 1
                        rel = path.relative_to(root).as_posix()
                        issues.append((rel, label, line_no))

    return issues


# ============================================================
# Entry point
# ============================================================

def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: sync_sanitize.py <dest_path>", file=sys.stderr)
        return 2

    dest = Path(sys.argv[1])
    if not dest.is_dir():
        print(f"[sanitize] ERRO: nao e diretorio: {dest}", file=sys.stderr)
        return 2

    print(f"[sanitize] alvo: {dest}")

    # 0) PRE-FLIGHT: purga credenciais e arquivos sensiveis (NUNCA podem subir)
    sens_dirs, sens_files = purge_sensitive(dest)
    for d in sens_dirs:
        print(f"  ! purgado sensivel (dir):  {d}")
    for f in sens_files:
        print(f"  ! purgado sensivel (file): {f}")

    # 1) remove diretorios comerciais
    removed_dirs = remove_commercial_dirs(dest)
    for d in removed_dirs:
        print(f"  - removido dir:  {d}")

    # 2) remove arquivos comerciais
    removed_files = remove_commercial_files(dest)
    for f in removed_files:
        print(f"  - removido file: {f}")

    # 3) patch bot.py
    bot_py = dest / "src/channels/telegram/bot.py"
    if patch_bot_py(bot_py):
        print("  ~ patchado:      src/channels/telegram/bot.py")

    # 4) patch analyst_crew.py — remove bloco Scout Hunter 2.0
    analyst_crew = dest / "src/core/hierarchy/crews/analyst_crew.py"
    if patch_analyst_crew(analyst_crew):
        print("  ~ patchado:      src/core/hierarchy/crews/analyst_crew.py")

    # 5) patch hierarchy __init__ files
    patched_init = patch_hierarchy_init(dest)
    for p in patched_init:
        print(f"  ~ patchado:      {p}")

    # 6) patch skills.yaml
    skills_yaml = dest / "config/skills.yaml"
    if patch_skills_yaml(skills_yaml):
        print("  ~ patchado:      config/skills.yaml")

    # 7) security scan
    print()
    issues = security_scan(dest)
    if issues:
        print(f"[sanitize] FAIL — {len(issues)} referencias comerciais residuais:")
        for rel, label, line in issues[:20]:
            print(f"  ! {rel}:{line}  ({label})")
        if len(issues) > 20:
            print(f"  ... (+{len(issues) - 20} mais)")
        return 1

    print("[sanitize] OK — working tree publico esta limpo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
