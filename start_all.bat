@echo off
title Seeker Unified Console
cd /d "%~dp0"
call .venv\Scripts\activate.bat 2>nul
python seeker_orchestrator.py
pause
