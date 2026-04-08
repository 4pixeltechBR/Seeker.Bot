@echo off
REM Inicia Seeker.Bot e mantém a janela aberta mesmo se há erros
title Seeker.Bot
cd /d E:\Seeker.Bot
echo ========================================
echo Iniciando Seeker.Bot...
echo ========================================
python -m src
echo.
echo ========================================
echo Seeker encerrou. Pressione qualquer tecla para fechar...
echo ========================================
pause
