"""
VaultSearcher - Pesquisa e leitura do cofre Obsidian
"""

import yaml
import logging
import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
import time

from src.core.memory.tfidf_search import TFIDFSearch

log = logging.getLogger("seeker.knowledge_vault.searcher")


@dataclass
class VaultNote:
    path: Path
    title: str
    date: str
    tags: List[str]
    source_type: str
    source_url: str
    body: str

    @property
    def preview(self) -> str:
        return self.body[:500] + "..." if len(self.body) > 500 else self.body


class VaultSearcher:
    def __init__(
        self, vault_path: str = r"D:\Obsidian\Segundo Cérebro\Segundo Cérebro"
    ):
        self.vault_path = Path(vault_path)
        self._cache = {}
        self._last_index_time = 0
        self._index_ttl = 300  # 5 minutos
        self._tfidf = TFIDFSearch()
        self._id_to_path: dict[int, str] = {}

    def _parse_note(self, file_path: Path) -> Optional[VaultNote]:
        """Parseia uma nota Markdown com frontmatter YAML."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Regex para extrair frontmatter --- ... ---
            match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
            if not match:
                # Nota sem frontmatter ou mal formatada
                return VaultNote(
                    path=file_path,
                    title=file_path.stem,
                    date="",
                    tags=[],
                    source_type="markdown",
                    source_url="",
                    body=content.strip(),
                )

            frontmatter_raw = match.group(1)
            body = match.group(2).strip()

            data = yaml.safe_load(frontmatter_raw) or {}

            return VaultNote(
                path=file_path,
                title=data.get("title", file_path.stem),
                date=str(data.get("date", "")),
                tags=data.get("tags", []),
                source_type=data.get("type", "note"),
                source_url=data.get("source", ""),
                body=body,
            )
        except Exception as e:
            log.error(f"[vault_searcher] Erro ao parsear {file_path}: {e}")
            return None

    def _build_index(self):
        """Reconstrói o cache de notas se o TTL expirou."""
        now = time.time()
        if now - self._last_index_time < self._index_ttl and self._cache:
            return

        log.debug("[vault_searcher] Reconstruindo índice do cofre...")
        new_cache = {}

        # Busca recursiva em todo o cofre
        for file_path in self.vault_path.rglob("*.md"):
            if ".obsidian" in file_path.parts:
                continue

            note = self._parse_note(file_path)
            if note:
                new_cache[str(file_path)] = note

        self._cache = new_cache
        self._last_index_time = now

        # Reconstrói índice TF-IDF: título + tags pesam mais (repetidos no doc)
        self._tfidf = TFIDFSearch()
        self._id_to_path = {}
        for i, (path_str, note) in enumerate(self._cache.items()):
            doc_text = (
                f"{note.title} {note.title} "
                f"{' '.join(note.tags)} {' '.join(note.tags)} "
                f"{note.body}"
            )
            self._tfidf.add_document(i, doc_text)
            self._id_to_path[i] = path_str

        log.info(
            f"[vault_searcher] Índice reconstruído: {len(self._cache)} notas encontradas."
        )

    def search(self, query: str, max_results: int = 5) -> List[VaultNote]:
        """
        Busca notas por similaridade TF-IDF (título/tags/corpo).
        Faz fallback para busca por palavra-chave se TF-IDF não retornar nada
        (ex.: query com termos raros que não aparecem em nenhum documento).
        """
        self._build_index()

        if not self._cache:
            return []

        tfidf_results = self._tfidf.search(query, top_k=max_results, min_similarity=0.05)
        if tfidf_results:
            return [
                self._cache[self._id_to_path[doc_id]]
                for doc_id, _score in tfidf_results
                if doc_id in self._id_to_path
            ]

        return self._keyword_search(query, max_results)

    def _keyword_search(self, query: str, max_results: int = 5) -> List[VaultNote]:
        """Busca por substring exata — fallback quando TF-IDF não acha nada."""
        query = query.lower()
        results = []

        for note in self._cache.values():
            score = 0
            if query in note.title.lower():
                score += 10

            for tag in note.tags:
                if query in tag.lower():
                    score += 5
                    break

            if query in note.body.lower():
                score += 1

            if score > 0:
                results.append((score, note))

        results.sort(key=lambda x: x[0], reverse=True)
        return [note for score, note in results[:max_results]]

    def get_context_for_llm(self, query: str, max_chars: int = 3000) -> str:
        """Retorna o conteúdo das notas relevantes formatado para contexto de LLM."""
        notes = self.search(query)
        if not notes:
            return ""

        context_parts = ["━━━ COFRE OBSIDIAN: CONTEÚDO RELACIONADO ━━━"]
        current_chars = len(context_parts[0])

        for note in notes:
            header = f"\n[Nota: {note.title}] (Tags: {', '.join(note.tags)})"
            body_fragment = note.body[:1000]  # Limita cada nota individualmente

            snippet = f"{header}\n{body_fragment}\n"

            if current_chars + len(snippet) > max_chars:
                break

            context_parts.append(snippet)
            current_chars += len(snippet)

        return "\n".join(context_parts)

    def list_recent(self, days: int = 7) -> List[VaultNote]:
        """Lista notas criadas nos últimos N dias."""
        self._build_index()

        from datetime import datetime, timedelta

        limit_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        recent = []
        for note in self._cache.values():
            if note.date >= limit_date:
                recent.append(note)

        # Ordena por data descendente
        recent.sort(key=lambda x: x.date, reverse=True)
        return recent
