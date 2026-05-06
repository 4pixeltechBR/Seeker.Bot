@echo off
REM Seeker.Bot — Watchdog Starter
REM Executa o watchdog em uma janela de terminal

cd /d "%~dp0"
call .venv\Scripts\activate.bat 2>nul
python watchdog.py
pause
