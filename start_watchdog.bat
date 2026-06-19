@echo off
title Seeker Bot Watchdog
REM Seeker.Bot — Watchdog Starter
REM Executa o watchdog em uma janela de terminal


cd /d "%~dp0"
call .venv\Scripts\activate.bat 2>nul
python seeker_watchdog.py
pause
