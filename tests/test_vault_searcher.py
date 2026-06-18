"""
Testes para VaultSearcher — busca TF-IDF no cofre Obsidian.
"""

import pytest

from src.skills.knowledge_vault.vault_searcher import VaultSearcher


def _write_note(tmp_path, filename, title, tags, body):
    content = (
        "---\n"
        f"title: {title}\n"
        f"date: '2026-01-01'\n"
        f"tags: [{', '.join(tags)}]\n"
        "type: ideia-victor\n"
        "---\n\n"
        f"{body}\n"
    )
    (tmp_path / filename).write_text(content, encoding="utf-8")


class TestVaultSearcherTFIDF:
    def test_search_ranks_by_relevance(self, tmp_path):
        _write_note(
            tmp_path, "fine-tuning.md", "Fine-tuning de LLMs", ["ia", "fine-tune"],
            "Como fazer fine-tuning de modelos de linguagem usando LoRA e QLoRA."
        )
        _write_note(
            tmp_path, "marketing.md", "Estratégia de Marketing", ["marketing", "growth"],
            "Plano de growth para o próximo trimestre, focado em aquisição."
        )

        searcher = VaultSearcher(vault_path=str(tmp_path))
        results = searcher.search("fine-tuning de LLM", max_results=5)

        assert len(results) >= 1
        assert results[0].title == "Fine-tuning de LLMs"

    def test_search_no_match_returns_empty(self, tmp_path):
        _write_note(
            tmp_path, "nota.md", "Nota Qualquer", ["geral"],
            "Conteúdo qualquer sobre o dia a dia."
        )

        searcher = VaultSearcher(vault_path=str(tmp_path))
        results = searcher.search("xenobiologia quântica intergaláctica", max_results=5)

        assert results == []

    def test_search_empty_vault(self, tmp_path):
        searcher = VaultSearcher(vault_path=str(tmp_path))
        results = searcher.search("qualquer coisa", max_results=5)
        assert results == []
