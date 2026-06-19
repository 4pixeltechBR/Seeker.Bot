@echo off
title Seeker.Bot + Agent Starter
echo ══════════════════════════════════════════════
echo   SEEKER.BOT + AGENT — Inicializacao Completa
echo ══════════════════════════════════════════════
echo.
cd /d "%~dp0"

echo [1/2] Iniciando Watchdog do Bot Conversacional (Telegram)...
start "Seeker Bot Watchdog" cmd /c "call .venv\Scripts\activate.bat && python seeker_watchdog.py"

echo [2/2] Iniciando Watchdog do Seeker Agent (Gateway / Crons)...
start "Seeker Agent Watchdog" cmd /c "call .venv\Scripts\activate.bat && python seeker_agent_watchdog.py"

echo.
exit
