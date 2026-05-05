"""
Seeker.Bot — Entrypoint
python -m src → inicia o bot
"""

import asyncio
import subprocess
import os
import sys
from src.channels.telegram.bot import main

def ensure_storage():
    """Tenta garantir que o Google Drive Desktop (I:) está montado antes do boot."""
    script_path = os.path.join(os.getcwd(), "scripts", "mount_storage.ps1")
    if os.path.exists(script_path):
        try:
            # Executa PowerShell Bypass para evitar bloqueio de execução de scripts locais
            subprocess.run([
                "powershell.exe", 
                "-ExecutionPolicy", "Bypass", 
                "-File", script_path
            ], check=False)
        except Exception as e:
            print(f"Erro ao tentar rodar mount_storage: {e}")

if __name__ == "__main__":
    ensure_storage()
    asyncio.run(main())
