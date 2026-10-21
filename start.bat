@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Python 3.12 nao encontrado.
    exit /b 1
  )
  .venv\Scripts\python.exe -m pip install -e .
)
if not exist .env copy /Y .env.example .env >nul
if not exist config.toml copy /Y config.example.toml config.toml >nul
.venv\Scripts\python.exe -m seeker
