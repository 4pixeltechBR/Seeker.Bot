@echo off
chcp 65001 >nul
title Seeker Unified Console
cd /d E:\Seeker.Bot

:: Usa diretamente o Python do venv para evitar ambiguidade
.venv\Scripts\python.exe seeker_orchestrator.py

echo.
echo [v] Tudo encerrado.
pause
