"""
E2E Test — research_machine pipeline completa.

Valida o fluxo: /research <query> → YouTube → NotebookLM → Síntese → Obsidian.
Executa com mock de LLM para não gastar tokens (ou real se --live).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Configura logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("seeker.e2e_research")

# Adiciona raiz do projeto ao path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.skills.research_machine.pipeline import ResearchPipeline
from src.skills.research_machine.notebooklm import NotebookLMClient
from src.skills.research_machine.yt_search import YouTubeSearch, YouTubeVideo
from src.skills.research_machine.synthesizer import Synthesizer, SynthesisResult
from src.skills.knowledge_vault.vault_writer import ObsidianWriter


class MockPipeline:
    """Mock do SeekerPipeline para testes."""
    def __init__(self):
        self.api_keys = {}
        self.model_router = MagicMock()
        self.cost_tracker = MagicMock()
        self.cost_tracker.daily_cost = 0.0
        
    class searcher:
        @staticmethod
        async def search(query, max_results=5):
            class Result:
                def to_context(self, max_results=5):
                    return f"Mock search results for: {query}"
            return Result()


async def test_yt_search():
    """Testa busca no YouTube (real)."""
    log.info("🔍 Testando YouTubeSearch...")
    yt = YouTubeSearch()
    videos = yt.search("Python async tutorial", max_results=3)
    assert len(videos) > 0, "Deveria retornar pelo menos 1 vídeo"
    assert all(isinstance(v, YouTubeVideo) for v in videos)
    log.info(f"  ✅ {len(videos)} vídeos encontrados")
    for v in videos[:2]:
        log.info(f"    - {v.title[:50]}... ({v.view_count} views)")
    return videos


async def test_notebooklm():
    """Testa NotebookLM client (real se autenticado, mock caso contrário)."""
    log.info("📓 Testando NotebookLMClient...")
    nb = NotebookLMClient()
    ok = await nb.initialize()
    if not ok:
        log.warning("  ⚠️ NotebookLM não autenticado (rode 'notebooklm login') — usando mock")
        # Testa com mock
        nb._client = MagicMock()
        nb._client.notebooks.create = AsyncMock(return_value=MagicMock(
            id="test123", title="Test", url="https://notebooklm.google.com/notebook/test123"
        ))
        nb._client.sources.add_url = AsyncMock()
        nb._available = True
    
    nbo = await nb.create_notebook("Teste E2E")
    assert nbo is not None
    assert nbo.notebook_id
    log.info(f"  ✅ Notebook criado: {nbo.notebook_id[:8]}...")
    await nb.close()
    return True


async def test_synthesizer():
    """Testa síntese via LLM (mock)."""
    log.info("🧠 Testando Synthesizer...")
    
    mock_pipeline = MockPipeline()
    
    # Mock do invoke_with_fallback
    with patch("src.skills.research_machine.synthesizer.invoke_with_fallback") as mock_invoke:
        mock_resp = MagicMock()
        mock_resp.text = """## Resumo Executivo
- Tópico principal testado
- Insight 1
- Insight 2

## Análise por Vídeo
- Vídeo 1: Python async tutorial

## Insights e Conexões
- Conexão entre async e threading

## Flashcards
**Pergunta:** O que é async?
**Resposta:** Programação assíncrona
---
**Pergunta:** Como funciona await?
**Resposta:** Pausa execução até promise resolver

## Infográfico
```
PYTHON ASYNC
    │
    ├── await
    ├── asyncio
    └── event loop
```"""
        mock_resp.cost_usd = 0.001
        mock_invoke.return_value = mock_resp
        
        synth = Synthesizer(mock_pipeline)
        result = await synth.synthesize(
            "Python async tutorial",
            "**Video 1** (Channel) - 1000 views\n> Description here"
        )
        
        assert isinstance(result, SynthesisResult)
        assert "Resumo Executivo" in result.summary_md
        assert len(result.flashcards) >= 2
        assert "PYTHON ASYNC" in result.infographic.upper()
        log.info(f"  ✅ Síntese gerada ({len(result.summary_md)} chars)")
        return True


async def test_obsidian_writer():
    """Testa escrita no Obsidian (usa temp dir)."""
    log.info("📝 Testando ObsidianWriter...")
    with tempfile.TemporaryDirectory() as tmpdir:
        vault_path = Path(tmpdir) / "TestVault" / "Inbox"
        writer = ObsidianWriter(inbox_path=str(vault_path))
        
        fpath = writer.write_note(
            title="Teste E2E Research",
            body="# Teste\n\nConteúdo do teste.",
            tags=["test", "e2e"],
            source_type="research_machine",
            source_url="https://youtube.com/watch?v=test",
        )
        
        assert fpath.exists()
        content = fpath.read_text(encoding="utf-8")
        assert "Teste E2E Research" in content
        assert "test" in content.lower()
        assert "e2e" in content.lower()
        log.info(f"  ✅ Nota salva em: {fpath}")
        return True


async def test_pipeline_integration():
    """Testa pipeline completa com mocks."""
    log.info("🔗 Testando pipeline completa (integração)...")
    
    mock_pipeline = MockPipeline()
    
    # Mocks para YouTube + NotebookLM + Synthesizer
    with patch("src.skills.research_machine.pipeline.YouTubeSearch") as mock_yt, \
         patch("src.skills.research_machine.pipeline.NotebookLMClient") as mock_nb_class, \
         patch("src.skills.research_machine.pipeline.Synthesizer") as mock_synth_class, \
         patch("src.skills.research_machine.pipeline.ObsidianWriter") as mock_vault_class:
        
        # YouTube
        mock_yt_instance = mock_yt.return_value
        mock_yt_instance.search.return_value = [
            YouTubeVideo(
                video_id=f"vid{i}", title=f"Video {i}", url=f"https://youtu.be/vid{i}",
                channel_name="Test Channel", view_count=1000, upload_date="20260101", duration_s=300
            ) for i in range(3)
        ]
        mock_yt_instance.enrich.return_value = mock_yt_instance.search.return_value[0]
        
        # NotebookLM
        mock_nb = MagicMock()
        mock_nb.initialize = AsyncMock(return_value=True)
        mock_nb.create_notebook = AsyncMock(return_value=MagicMock(
            notebook_id="nb123", title="Test", url="https://notebooklm.google.com/notebook/nb123"
        ))
        mock_nb.add_urls = AsyncMock(return_value=True)
        mock_nb.close = AsyncMock()
        mock_nb_class.return_value = mock_nb
        
        # Synthesizer
        mock_synth = MagicMock()
        mock_synth.synthesize = AsyncMock(return_value=SynthesisResult(
            summary_md="## Resumo\n- Teste",
            flashcards=["**P:** Q\n**R:** A"],
            infographic="```ASCII\nTESTE\n```",
            cost_usd=0.001
        ))
        mock_synth_class.return_value = mock_synth
        
        # Vault
        mock_vault = MagicMock()
        mock_vault.write_note.return_value = Path("/tmp/test.md")
        mock_vault_class.return_value = mock_vault
        
        # Executa pipeline
        pipeline = ResearchPipeline(mock_pipeline)
        result = await pipeline.research("test query", max_videos=3)
        
        assert "run_id" in result
        assert result["status"] == "completed"
        assert len(result["videos"]) >= 3
        assert "notebook_url" in result
        assert "obsidian_path" in result
        log.info(f"  ✅ Pipeline completa: run_id={result['run_id']}")
        return True


async def main():
    """Executa todos os testes."""
    log.info("=" * 60)
    log.info("E2E TEST — research_machine")
    log.info("=" * 60)
    
    tests = [
        ("YouTube Search", test_yt_search),
        ("NotebookLM", test_notebooklm),
        ("Synthesizer", test_synthesizer),
        ("Obsidian Writer", test_obsidian_writer),
        ("Pipeline Integration", test_pipeline_integration),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_fn in tests:
        try:
            log.info(f"\n▶ {name}")
            await test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            log.error(f"  ❌ {name}: {e}", exc_info=True)
    
    log.info("\n" + "=" * 60)
    log.info(f"RESULTADO: {passed} passaram, {failed} falharam")
    log.info("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)