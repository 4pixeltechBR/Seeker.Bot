"""
Testes para a skill knowledge_vault (Cofre Obsidian).
Sprint 12.1 — Completar Cofre.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from src.skills.knowledge_vault.facade import KnowledgeVault
from src.core.search.web import SearchResult, SearchResponse


@dataclass
class MockSearchResult:
    title: str
    url: str
    snippet: str
    score: float = 0.8

    def to_context(self):
        return f"[{self.title}]\n{self.snippet}\n{self.url}"


@dataclass
class MockSearchResponse:
    results: list = None
    query: str = ""

    def __post_init__(self):
        if self.results is None:
            self.results = []

    def to_context(self, max_results=5):
        if not self.results:
            return ""
        lines = [f"=== {self.query} ==="]
        for r in self.results[:max_results]:
            lines.append(r.to_context())
        return "\n".join(lines)


@pytest.mark.asyncio
class TestKnowledgeVault:
    """Testes da façade KnowledgeVault."""

    @pytest.fixture
    async def mock_vault(self):
        """Cria uma KnowledgeVault com mocks."""
        cascade_adapter = AsyncMock()
        cascade_adapter.call = AsyncMock(return_value={
            "content": '{"title": "Teste", "summary": "Resumo teste", '
                      '"tags": ["teste"], "key_insights": [], '
                      '"category": "Teste", "related_topics": []}'
        })

        vlm_client = AsyncMock()
        vlm_client.ocr_fast = AsyncMock(return_value="Texto extraído")
        vlm_client.analyze_screenshot = AsyncMock(return_value="Contexto visual")

        web_searcher = AsyncMock()
        web_searcher.search = AsyncMock(return_value=MockSearchResponse(
            query="teste",
            results=[
                MockSearchResult(
                    title="Resultado 1",
                    url="https://exemplo1.com",
                    snippet="Snippet do resultado 1"
                )
            ]
        ))

        vault = KnowledgeVault(cascade_adapter, vlm_client, web_searcher)
        vault.writer = AsyncMock()
        vault.writer.write_note = MagicMock(return_value="/path/to/note.md")

        return vault, cascade_adapter, vlm_client, web_searcher

    async def test_derive_query(self, mock_vault):
        """Testa extração de query do texto."""
        vault, _, _, _ = mock_vault

        # Com título
        query = vault._derive_query("Lorem ipsum dolor", title="Meu Título")
        assert query == "Meu Título"

        # Sem título: primeiras 12 palavras
        text = " ".join([f"word{i}" for i in range(20)])
        query = vault._derive_query(text)
        assert "word0" in query
        assert len(query.split()) <= 12

    async def test_research_no_web_searcher(self, mock_vault):
        """Testa _research quando web_searcher é None."""
        cascade_adapter = AsyncMock()
        vault = KnowledgeVault(cascade_adapter, vlm_client=None, web_searcher=None)

        context = await vault._research("teste query")
        assert context == ""

    async def test_research_with_web_searcher(self, mock_vault):
        """Testa _research com web_searcher disponível."""
        vault, _, _, web_searcher = mock_vault

        context = await vault._research("teste")
        assert web_searcher.search.called
        assert "Resultado 1" in context or context != ""

    async def test_process_text(self, mock_vault):
        """Testa processo_text: texto → nota salva."""
        vault, cascade_adapter, _, _ = mock_vault

        result = await vault.process_text("Minha ideia brilhante")

        # Deve chamar analyze_and_tag
        assert cascade_adapter.call.called
        # Deve chamar write_note
        assert vault.writer.write_note.called
        # Deve retornar sucesso
        assert "✅" in result

    async def test_process_audio_idea(self, mock_vault):
        """Testa processo_audio_idea: áudio → ideia salva."""
        vault, _, _, _ = mock_vault

        with patch("src.skills.knowledge_vault.facade.extract_from_audio") as mock_extract:
            mock_extract = AsyncMock(return_value="Transcrição do áudio")
            with patch.object(vault, "process_text", new_callable=AsyncMock) as mock_process_text:
                mock_process_text.return_value = "✅ Nota salva"
                result = await vault.process_audio_idea(b"audio_bytes")

                # Deve chamar process_text
                assert mock_process_text.called
                assert "✅" in result

    async def test_process_url_youtube(self, mock_vault):
        """Testa roteamento de URL para YouTube."""
        vault, _, _, _ = mock_vault

        result = await vault.process_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        # Deve chamar process_youtube (internamente)
        assert vault.writer.write_note.called

    async def test_process_url_github(self, mock_vault):
        """Testa roteamento de URL para GitHub."""
        vault, _, _, _ = mock_vault

        with patch("src.core.search.web.fetch_page_text") as mock_fetch:
            mock_fetch.return_value = "# Meu Repositório\n\nDescrição..."
            result = await vault.process_url("https://github.com/user/repo")

            # Deve chamar write_note (processo_repo)
            assert vault.writer.write_note.called

    async def test_process_url_site(self, mock_vault):
        """Testa roteamento de URL para site genérico."""
        vault, _, _, _ = mock_vault

        with patch("src.core.search.web.fetch_page_text") as mock_fetch:
            mock_fetch.return_value = "Conteúdo do site"
            result = await vault.process_url("https://exemplo.com/artigo")

            # Deve chamar process_site (internamente)
            assert vault.writer.write_note.called

    async def test_process_pdf(self, mock_vault):
        """Testa processo_pdf: PDF → nota salva."""
        vault, _, _, _ = mock_vault

        with patch("src.skills.knowledge_vault.extractors.extract_from_pdf") as mock_extract:
            mock_extract.return_value = "Texto extraído do PDF"
            result = await vault.process_pdf(b"pdf_bytes")

            # Deve chamar extract_from_pdf
            assert mock_extract.called
            # Deve chamar write_note
            assert vault.writer.write_note.called
            assert "✅" in result

    async def test_process_repo(self, mock_vault):
        """Testa processo_repo: GitHub → nota com README."""
        vault, cascade_adapter, _, _ = mock_vault

        with patch("src.skills.knowledge_vault.facade.fetch_github_readme") as mock_readme:
            with patch("src.skills.knowledge_vault.facade.fetch_github_metadata") as mock_meta:
                mock_readme.return_value = "# Meu Repo\n\n- Feature A\n- Feature B"
                mock_meta.return_value = {
                    "description": "Um projeto legal",
                    "language": "Python",
                    "stars": 42,
                    "topics": ["ai", "bot"],
                    "homepage": "https://projeto.example.com",
                }
                result = await vault.process_repo("https://github.com/victor/projeto")

                # Deve buscar README e metadados
                assert mock_readme.called
                assert mock_meta.called
                # Deve chamar analyze_and_tag com source_type "repo"
                assert cascade_adapter.call.called
                # Deve chamar write_note
                assert vault.writer.write_note.called
                assert "✅" in result

    async def test_search_and_answer_no_results(self, mock_vault):
        """Testa search_and_answer quando não há notas no cofre."""
        vault, cascade_adapter, _, _ = mock_vault

        vault.searcher = MagicMock()
        vault.searcher.search = MagicMock(return_value=[])

        result = await vault.search_and_answer("termo inexistente")
        assert "Nenhuma nota encontrada" in result
        assert not cascade_adapter.call.called

    async def test_search_and_answer_with_synthesis(self, mock_vault):
        """Testa search_and_answer: encontra notas, sintetiza resposta via LLM."""
        vault, cascade_adapter, _, _ = mock_vault

        from pathlib import Path
        from src.skills.knowledge_vault.vault_searcher import VaultNote

        note = VaultNote(
            path=Path("/vault/Inbox/nota.md"),
            title="Fine-tuning de LLMs",
            date="2026-01-01",
            tags=["ia", "fine-tune"],
            source_type="ideia-victor",
            source_url="",
            body="Conteúdo sobre fine-tuning de modelos.",
        )

        vault.searcher = MagicMock()
        vault.searcher.search = MagicMock(return_value=[note])

        cascade_adapter.call = AsyncMock(return_value={
            "content": "O cofre tem uma nota sobre fine-tuning de LLMs."
        })

        result = await vault.search_and_answer("fine-tuning")

        assert cascade_adapter.call.called
        assert "fine-tuning" in result.lower()
        assert "Fine-tuning de LLMs" in result
        assert "Fontes" in result

    async def test_search_and_answer_synthesis_failure_degrades(self, mock_vault):
        """Testa que search_and_answer degrada para lista simples se LLM falhar."""
        vault, cascade_adapter, _, _ = mock_vault

        from pathlib import Path
        from src.skills.knowledge_vault.vault_searcher import VaultNote

        note = VaultNote(
            path=Path("/vault/Inbox/nota.md"),
            title="Nota Teste",
            date="2026-01-01",
            tags=["teste"],
            source_type="ideia-victor",
            source_url="",
            body="Conteúdo de teste.",
        )

        vault.searcher = MagicMock()
        vault.searcher.search = MagicMock(return_value=[note])

        cascade_adapter.call = AsyncMock(side_effect=Exception("LLM indisponível"))

        result = await vault.search_and_answer("teste")
        assert "Nota Teste" in result
        assert "Resultados no Cofre" in result

    async def test_process_text_degradation_no_web_search(self):
        """Testa que process_text funciona sem web_searcher (graceful degradation)."""
        cascade_adapter = AsyncMock()
        cascade_adapter.call = AsyncMock(return_value={
            "content": '{"title": "Ideia", "summary": "Resumo", '
                      '"tags": ["teste"], "key_insights": [], '
                      '"category": "Ideia", "related_topics": []}'
        })

        vault = KnowledgeVault(cascade_adapter, vlm_client=None, web_searcher=None)
        vault.writer = AsyncMock()
        vault.writer.write_note = MagicMock(return_value="/path/to/note.md")

        # Deve funcionar mesmo sem web_searcher
        result = await vault.process_text("Minha ideia")
        assert "✅" in result
        assert vault.writer.write_note.called
