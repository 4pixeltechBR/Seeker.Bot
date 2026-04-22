"""
ObsidianWriter - Escrita direta no filesystem do Obsidian
"""
import os
import re
import yaml
from datetime import datetime
from pathlib import Path
import logging

log = logging.getLogger("seeker.knowledge_vault.writer")

VAULT_PATH = r"D:\Obsidian\Segundo Cérebro\Segundo Cérebro"
INBOX_PATH = os.path.join(VAULT_PATH, "Inbox")

class ObsidianWriter:
    def __init__(self, inbox_path: str = INBOX_PATH):
        self.inbox_path = Path(inbox_path)
        self._ensure_inbox()

    def _ensure_inbox(self):
        """Garante que a pasta Inbox exista."""
        if not self.inbox_path.exists():
            try:
                self.inbox_path.mkdir(parents=True, exist_ok=True)
                log.info(f"[obsidian] Inbox criada em: {self.inbox_path}")
            except Exception as e:
                log.error(f"[obsidian] Erro ao criar Inbox: {e}")

    def sanitize_filename(self, filename: str) -> str:
        """Remove caracteres inválidos para nome de arquivo no Windows."""
        return re.sub(r'[<>:"/\\|?*]', '', filename).strip()

    def write_note(self, title: str, body: str, tags: list[str], source_type: str, source_url: str = "") -> Path:
        """Escreve uma nova nota no Inbox."""
        safe_title = self.sanitize_filename(title)
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{date_str} - {safe_title}.md"
        
        file_path = self.inbox_path / filename

        # Evita sobrescrever se já existir exatamente o mesmo nome
        counter = 1
        while file_path.exists():
            filename = f"{date_str} - {safe_title} ({counter}).md"
            file_path = self.inbox_path / filename
            counter += 1

        # Prepara Frontmatter YAML
        frontmatter = {
            "title": title,
            "date": date_str,
            "source": source_url,
            "type": source_type,
            "tags": tags,
            "captured_by": "seeker"
        }

        content = f"---\n{yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)}---\n\n{body}\n"

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            log.info(f"[obsidian] Nota salva com sucesso: {file_path}")
            return file_path
        except Exception as e:
            log.error(f"[obsidian] Erro ao salvar nota {filename}: {e}")
            raise e

    def check_duplicate(self, title: str) -> bool:
        """Verifica se existe uma nota recente com título similar no Inbox."""
        import difflib
        
        safe_title = self.sanitize_filename(title).lower()
        
        if not self.inbox_path.exists():
            return False

        for file_path in self.inbox_path.glob("*.md"):
            # Remove data (YYYY-MM-DD - ) do nome do arquivo
            name = file_path.stem
            name_no_date = re.sub(r"^\d{4}-\d{2}-\d{2}\s*-\s*", "", name).lower()
            
            # Fuzzy match
            ratio = difflib.SequenceMatcher(None, safe_title, name_no_date).ratio()
            if ratio > 0.85:
                log.info(f"[obsidian] Possível duplicata ignorada: '{title}' vs '{name}' (ratio: {ratio:.2f})")
                return True
                
        return False
