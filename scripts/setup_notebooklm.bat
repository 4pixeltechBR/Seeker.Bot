@echo off
REM ============================================================
REM Seeker.Bot — Login NotebookLM (multi-modo)
REM ============================================================
echo.
echo  Seeker.Bot - Configurando NotebookLM...
echo.

cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo  [ERRO] Ambiente virtual nao encontrado em .venv\Scripts\
    pause
    exit /b 1
)

set "MODE=%~1"

if "%MODE%"=="" (
    .venv\Scripts\python.exe scripts\seeker_nb_login.py
) else (
    .venv\Scripts\python.exe scripts\seeker_nb_login.py %MODE%
)

echo.
pause