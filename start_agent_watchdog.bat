@echo off
title Seeker Agent Watchdog
REM Seeker.Agent — Watchdog Starter
REM Executa o watchdog do gateway em uma janela de terminal


cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo [ERRO] Venv nao encontrada em .venv\. Execute install.bat primeiro.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
python seeker_agent_watchdog.py
pause
