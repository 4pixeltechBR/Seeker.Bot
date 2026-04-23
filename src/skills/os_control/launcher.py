import os
import subprocess
import logging

log = logging.getLogger("seeker.os.launcher")

class AppLauncher:
    """Ferramenta para abrir aplicativos e URLs no Windows de forma nativa e rápida."""
    
    # Dicionário de aliases conhecidos
    COMMON_APPS = {
        "chrome": "chrome.exe",
        "edge": "msedge.exe",
        "notepad": "notepad.exe",
        "calculadora": "calc.exe",
        "calc": "calc.exe",
        "excel": "excel.exe",
        "word": "winword.exe",
        "spotify": "spotify.exe",
        "explorador": "explorer.exe",
        "explorer": "explorer.exe",
        "terminal": "wt.exe", # Windows Terminal
    }

    @classmethod
    def launch(cls, target: str) -> str:
        """
        Abre o aplicativo ou URL passado.
        Pode ser um alias, um arquivo absoluto, ou uma URL.
        """
        target_lower = target.lower().strip()
        
        try:
            # 1. É uma URL web?
            if target_lower.startswith("http://") or target_lower.startswith("https://") or target_lower.startswith("www."):
                os.startfile(target)
                return f"[OS] URL aberta no navegador padrão: {target}"

            # 2. É um atalho conhecido?
            if target_lower in cls.COMMON_APPS:
                exe = cls.COMMON_APPS[target_lower]
                os.startfile(exe)
                return f"[OS] App lançado via catálogo local: {exe}"

            # 3. É um caminho de arquivo/pasta absoluto?
            if os.path.exists(target):
                os.startfile(target)
                return f"[OS] Caminho aberto: {target}"

            # 4. Fallback: tentar rodar como comando shell livre no Windows
            subprocess.Popen(target, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
            return f"[OS] Tentativa de inicialização via Shell: {target}"

        except Exception as e:
            log.error(f"[launcher] Falha ao abrir '{target}': {e}", exc_info=True)
            return f"[OS Falha] Erro ao abrir {target}: {e}"
