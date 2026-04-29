"""
ObsidianWriter v2.0 — Escrita direta no filesystem do Obsidian.

Melhorias:
- Suporte a extra_frontmatter (metadados ricos por tipo)
- Prefixo de emoji no nome do arquivo por tipo (💡 para ideias)
- Validação de escrita com log do path completo
"""
import os
import re
import yaml
from datetime import datetime
from pathlib import Path
import logging
from typing import Dict, Optional

log = logging.getLogger("seeker.knowledge_vault.writer")

VAULT_PATH = r"D:\Obsidian\Segundo Cérebro\Segundo Cérebro"
INBOX_PATH = os.path.join(VAULT_PATH, "Inbox")

# Prefixos por source_type no nome do arquivo (ASCII-safe para Windows)
SOURCE_PREFIX = {
    "ideia-victor": "[IDEIA]",
    "youtube": "[YT]",
    "site": "[ART]",
    "print": "[PRINT]",
    "ocr": "[OCR]",
    "audio": "[AUDIO]",
    "nota": "[NOTA]",
}


class ObsidianWriter:
    def __init__(self, inbox_path: str = INBOX_PATH):
        self.inbox_path = Path(inbox_path)
        self._ensure_inbox()

    def _ensure_inbox(self):
        if not self.inbox_path.exists():
            try:
                self.inbox_path.mkdir(parents=True, exist_ok=True)
                log.info(f"[obsidian] Inbox criada em: {self.inbox_path}")
            except Exception as e:
                log.error(f"[obsidian] Erro ao criar Inbox: {e}")

    def sanitize_filename(self, filename: str) -> str:
        """Remove caracteres inválidos para nome de arquivo no Windows."""
        # Remove emojis problemáticos para filesystem e chars especiais
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename).strip()
        return filename[:100]  # Limita tamanho

    def write_note(
        self,
        title: str,
        body: str,
        tags: list[str],
        source_type: str,
        source_url: str = "",
        extra_frontmatter: Optional[Dict] = None,
    ) -> Path:
        """
        Escreve uma nova nota no Inbox do Obsidian.
        
        Args:
            title: Título da nota
            body: Corpo em Markdown
            tags: Lista de tags Obsidian
            source_type: Tipo da fonte (youtube, site, ideia-victor, print, etc.)
            source_url: URL de origem (opcional)
            extra_frontmatter: Metadados adicionais para o frontmatter YAML
        """
        emoji = SOURCE_PREFIX.get(source_type, "[DOC]")
        safe_title = self.sanitize_filename(title)
        date_str = datetime.now().strftime("%Y-%m-%d")

        # Nome do arquivo com emoji e data
        filename = f"{date_str} {emoji} {safe_title}.md"
        file_path = self.inbox_path / filename

        # Evita sobrescrever
        counter = 1
        while file_path.exists():
            filename = f"{date_str} {emoji} {safe_title} ({counter}).md"
            file_path = self.inbox_path / filename
            counter += 1

        # Monta frontmatter base
        frontmatter = {
            "title": title,
            "date": date_str,
            "type": source_type,
            "tags": tags,
            "captured_by": "seeker",
        }
        if source_url:
            frontmatter["source"] = source_url

        # Adiciona metadados extras (canal, duração, autor, etc.)
        if extra_frontmatter:
            # Filtra valores None/vazios para não poluir o frontmatter
            filtered = {k: v for k, v in extra_frontmatter.items() if v}
            frontmatter.update(filtered)

        content = f"---\n{yaml.dump(frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False)}---\n\n{body}\n"

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            log.info(f"[obsidian] ✅ Nota salva: {file_path}")
            return file_path
        except Exception as e:
            log.error(f"[obsidian] ❌ Erro ao salvar nota '{filename}': {e}")
            raise

    def check_duplicate(self, title: str) -> bool:
        """Verifica se existe uma nota recente com título similar no Inbox."""
        import difflib

        safe_title = self.sanitize_filename(title).lower()

        if not self.inbox_path.exists():
            return False

        for file_path in self.inbox_path.glob("*.md"):
            name = file_path.stem
            # Remove data e emoji do nome
            name_clean = re.sub(r"^\d{4}-\d{2}-\d{2}\s*[\U00010000-\U0010ffff\U00002600-\U000027ff]?\s*", "", name, flags=re.UNICODE).lower()

            ratio = difflib.SequenceMatcher(None, safe_title, name_clean).ratio()
            if ratio > 0.85:
                log.info(f"[obsidian] Possível duplicata ignorada: '{title}' vs '{name}' (ratio: {ratio:.2f})")
                return True

        return False
