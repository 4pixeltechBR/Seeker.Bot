@echo off
title Seeker.Bot
echo ══════════════════════════════════════════════
echo   SEEKER.BOT — Inicio Rapido
echo ══════════════════════════════════════════════
echo.

cd /d "%~dp0"

:: Ativa o venv
call .venv\Scripts\activate.bat

:: Inicia o bot
echo [start] Iniciando Seeker.Bot...
echo [start] Ctrl+C para parar
echo.
python -m src

:: Se cair aqui, o bot parou
echo.
echo [start] Bot encerrado.
pause
