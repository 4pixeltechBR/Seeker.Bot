"""Tests para extractors novos (DOCX/XLSX/PPTX/vCard) e facade methods.
Phase 1b/1c do WhatsApp Integration v3.12.
"""
import io
import os

import pytest

from src.skills.knowledge_vault.extractors import (
    extract_from_docx,
    extract_from_xlsx,
    extract_from_pptx,
    extract_from_vcard,
)
from src.skills.knowledge_vault.facade import KnowledgeVault


@pytest.mark.asyncio
async def test_extract_from_docx_real_file():
    """DOCX com 1 parágrafo e 1 tabela."""
    import docx as pydocx

    buf = io.BytesIO()
    d = pydocx.Document()
    d.add_paragraph("Hello World from DOCX")
    d.add_paragraph("Segunda linha de teste")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Col1"
    table.cell(0, 1).text = "Col2"
    d.save(buf)
    out = await extract_from_docx(buf.getvalue())
    assert "Hello World from DOCX" in out
    assert "Segunda linha" in out
    assert "Col1" in out


@pytest.mark.asyncio
async def test_extract_from_xlsx_simple():
    """XLSX com 1 sheet 2x2."""
    from openpyxl import Workbook

    buf = io.BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = "Dados"
    ws.cell(1, 1, "A1")
    ws.cell(1, 2, "B1")
    ws.cell(2, 1, 42)
    ws.cell(2, 2, "X")
    wb.save(buf)
    out = await extract_from_xlsx(buf.getvalue())
    assert "Dados" in out
    assert "A1" in out
    assert "42" in out


@pytest.mark.asyncio
async def test_extract_from_pptx_two_slides():
    """PPTX com 2 slides, cada um com título + corpo."""
    from pptx import Presentation

    buf = io.BytesIO()
    prs = Presentation()
    slide_layout = prs.slide_layouts[1]
    s1 = prs.slides.add_slide(slide_layout)
    s1.shapes.title.text = "Slide Um"
    s1.placeholders[1].text = "Conteúdo do slide um"
    s2 = prs.slides.add_slide(slide_layout)
    s2.shapes.title.text = "Slide Dois"
    s2.placeholders[1].text = "Conteúdo do slide dois"
    prs.save(buf)
    out = await extract_from_pptx(buf.getvalue())
    assert "Slide 1" in out
    assert "Slide Um" in out
    assert "Slide Dois" in out
    assert "Conteúdo" in out


@pytest.mark.asyncio
async def test_extract_from_vcard_basic():
    """vCard 3.0 com 1 contato."""
    vcf = b"""BEGIN:VCARD
VERSION:3.0
FN:Victor Silva
N:Silva;Victor;;;
TEL;TYPE=CELL:+5511999999999
EMAIL:victor@example.com
ORG:Seeker Corp
END:VCARD
"""
    out = await extract_from_vcard(vcf)
    assert "Victor Silva" in out
    assert "5511999999999" in out
    assert "victor@example.com" in out
    assert "Seeker Corp" in out


@pytest.mark.asyncio
async def test_extract_from_docx_empty():
    """DOCX vazio retorna mensagem amigável."""
    out = await extract_from_docx(b"")
    assert "vazio" in out.lower()


@pytest.mark.asyncio
async def test_extract_from_xlsx_corrupted():
    """XLSX corrompido retorna erro, não levanta exceção."""
    out = await extract_from_xlsx(b"GARBAGE_NOT_XLSX")
    assert "ERRO" in out or "inválido" in out.lower()


@pytest.mark.asyncio
async def test_extract_from_pptx_corrupted():
    """PPTX corrompido retorna erro, não levanta exceção."""
    out = await extract_from_pptx(b"GARBAGE_NOT_PPTX")
    assert "ERRO" in out or "inválido" in out.lower()


@pytest.mark.asyncio
async def test_facade_process_docx_writes_note(tmp_path, monkeypatch):
    """Integration test: process_docx → arquivo .md aparece no Obsidian Vault."""
    import docx as pydocx

    vault_dir = tmp_path / "knowledge"
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))

    buf = io.BytesIO()
    d = pydocx.Document()
    d.add_paragraph("Conteúdo teste DOCX")
    d.save(buf)

    vault = KnowledgeVault(
        cascade_adapter=None,
        inbox_path=str(vault_dir),
    )
    out = await vault.process_docx(buf.getvalue(), user_hint="teste integração")

    assert "salvo" in out.lower() or "DOCX" in out
    files = list(vault_dir.glob("*.md"))
    assert len(files) >= 1
    content = files[0].read_text(encoding="utf-8")
    assert "Conteúdo teste DOCX" in content or "teste" in content.lower()
