@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================
REM  Seeker.Bot — Sync to Public GitHub Folder
REM  scripts\sync_to_public.bat
REM
REM  Copia E:\Seeker.Bot -> D:\Seeker GitHub, excluindo:
REM   - Ferramentas comerciais (seeker_sales, hunter_crew, etc)
REM   - Credenciais, dados, logs, venv, caches
REM   - Scripts temporarios da raiz (audit_*, push_*, etc)
REM
REM  Depois roda sync_sanitize.py para limpar refs inline em bot.py
REM  e validar que ZERO codigo comercial sobrou no working tree.
REM ============================================================

set "SRC=E:\Seeker.Bot"
set "DST=D:\Seeker GitHub"

echo.
echo ============================================================
echo  Seeker.Bot Public Sync
echo  SRC: %SRC%
echo  DST: %DST%
echo ============================================================
echo.

if not exist "%SRC%" (
    echo [ERRO] Source nao encontrado: %SRC%
    exit /b 2
)
if not exist "%DST%" (
    echo [ERRO] Destination nao encontrado: %DST%
    exit /b 2
)

REM --- Fase 1: robocopy com exclusoes ---
echo [1/3] Copiando working tree...

robocopy "%SRC%" "%DST%" /E /XD ".git" ".venv" "venv" "env" "__pycache__" ".vscode" ".idea" ".claude" ".pytest_cache" ".mypy_cache" ".ruff_cache" "data" "logs" "scratch" "Credenciais" "node_modules" "apps" "src\skills\seeker_sales" "src\skills\seeker_sales_week" "src\skills\show_leads_daily" "src\skills\event_map_scout" "src\skills\cortex" "src\skills\revenue_hunter" /XF ".env" "*.env.local" "*.env.production" "service-account*.json" "*token*.json" "credentials*.json" "gcp-oauth.keys.json" "*.pyc" "*.pyo" "*.bak" "*.swp" "*.swo" "temp_bot.json" "benchmark_*.log" "matches*.txt" "audit*.py" "check_*.py" "push_*.py" "extract_*.py" "search_*.py" "download_*.py" "refactor_*.py" "validate_*.py" "drive_decompiled.py" "hunter_crew.py" "sales.py" "discovery_matrix*.py" /NFL /NDL /NJH /NJS /NP /R:1 /W:1

set RC=%ERRORLEVEL%
REM robocopy exit codes 0-7 sao sucesso; 8+ sao erro
if %RC% GEQ 8 (
    echo [ERRO] robocopy falhou com codigo %RC%
    exit /b %RC%
)
echo robocopy OK (code=%RC%)
echo.

REM --- Fase 2: sanitizer Python ---
echo [2/3] Sanitizando bot.py e validando codigo comercial...
python "%SRC%\scripts\sync_sanitize.py" "%DST%"
if errorlevel 1 (
    echo.
    echo [ERRO] sync_sanitize.py reportou problemas. ABORTANDO.
    echo Resolva as referencias comerciais listadas e rode de novo.
    exit /b 1
)
echo.

REM --- Fase 3: git status report ---
echo [3/3] Status do git em %DST%:
pushd "%DST%"
git status --short
echo.
echo Branch atual:
git branch --show-current
popd

echo.
echo ============================================================
echo  Sync concluido.
echo  Revise o diff acima, depois em D:\Seeker GitHub:
echo    git add -A
echo    git commit -m "sync from E: (descricao)"
echo    git push origin main
echo ============================================================
endlocal
