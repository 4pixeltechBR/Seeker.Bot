import os
import shutil
import logging
from typing import List, Dict

log = logging.getLogger("seeker.os.fileops")

class FileOpsEngine:
    """Motor para manipulação de arquivos do Windows."""
    
    @classmethod
    def list_directory(cls, path: str) -> str:
        """Lista conteúdos de um diretório de forma segura."""
        if not os.path.exists(path):
            return f"[FileOps] Erro: Caminho '{path}' não encontrado."
        if not os.path.isdir(path):
            return f"[FileOps] Erro: '{path}' não é um diretório."
            
        try:
            items = os.listdir(path)
            res = []
            for item in items:
                full = os.path.join(path, item)
                is_dir = os.path.isdir(full)
                size_kb = os.path.getsize(full) / 1024 if not is_dir else 0
                res.append(f"{'[DIR] ' if is_dir else '[FILE]'} {item} ({size_kb:.1f} KB)")
                
            return "\n".join(res[:100]) # Cap em 100 itens pra não estourar o contexto
        except Exception as e:
            return f"[FileOps] Erro listando '{path}': {e}"
            
    @classmethod
    def move_file(cls, src: str, dest: str) -> str:
        if not os.path.exists(src):
            return f"[FileOps] Erro: Origem '{src}' não existe."
        try:
            shutil.move(src, dest)
            return f"[FileOps] Movidode '{src}' para '{dest}' com sucesso."
        except Exception as e:
            return f"[FileOps] Falha ao mover arquivo: {e}"

    @classmethod
    def delete_file(cls, path: str) -> str:
        if not os.path.exists(path):
            return f"[FileOps] Erro: '{path}' não existe."
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return f"[FileOps] Deletado: '{path}'."
        except Exception as e:
            return f"[FileOps] Falha ao deletar: {e}"
