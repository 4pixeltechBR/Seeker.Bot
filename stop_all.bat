@echo off
title Parando Seeker.Bot
echo ==================================================
echo   Parando Seeker.Bot e Agente de forma definitiva...
echo ==================================================
echo.
taskkill /F /IM python.exe /T 2>nul
taskkill /F /FI "WINDOWTITLE eq Seeker Bot Watchdog" 2>nul
taskkill /F /FI "WINDOWTITLE eq Seeker Agent Watchdog" 2>nul
taskkill /F /FI "WINDOWTITLE eq Seeker Unified Logs" 2>nul
echo.
echo [v] Todos os processos do Seeker foram parados com sucesso!
pause
