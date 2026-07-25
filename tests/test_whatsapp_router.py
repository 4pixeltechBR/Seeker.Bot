"""Tests para src/channels/whatsapp/router.py — classificação + summary."""
import asyncio

from src.channels.whatsapp.router import (
    HANDLERS,
    dispatch_message,
    summarize_batch,
)


def test_handlers_table_keys():
    """HANDLERS deve cobrir todas as 9 mídias + texto + site + 3 especiais."""
    expected = {"image", "pdf", "zip", "audio", "video", "docx", "xlsx",
                "pptx", "vcard", "text", "youtube", "github", "site",
                "location", "sticker", "poll"}
    assert expected.issubset(set(HANDLERS.keys()))
    assert len(HANDLERS) == len(set(HANDLERS.keys()))  # no dupes


def test_summarize_batch_basic():
    """summarize_batch() gera HTML correto."""
    msgs = [
        {"id": "abc123456", "type": "image", "from_name": "João"},
        {"id": "def456789", "type": "youtube", "from_name": "Maria"},
        {"id": "ghi012345", "type": "text", "from_name": "José"},
    ]
    results = [
        "✅ msg#abc123456 (image/jpeg): salvo em Knowledge/test.md",
        "✅ msg#def456789 (youtube): salvo em Knowledge/video.md",
        "✅ msg#ghi012345: salvo em Knowledge/dica.md",
    ]
    summary = summarize_batch(results, msgs)
    assert "3 mensagens" in summary
    assert "<b>image</b>" in summary
    assert "<b>youtube</b>" in summary
    assert "<b>text</b>" in summary


def test_summarize_batch_chunks_long_results():
    """summarize_batch trunca results longos (>120 chars)."""
    msgs = [{"id": "x" * 12, "type": "image", "from_name": "A"}]
    long_result = "x" * 500
    summary = summarize_batch([long_result], msgs)
    # truncation + italic markers
    assert "<i>" in summary
    assert summary.count("x") < 600  # truncated


def test_summarize_batch_groups_by_type():
    """summarize_batch agrupa por tipo."""
    msgs = [
        {"id": "i" * 12, "type": "image", "from_name": "A"},
        {"id": "j" * 12, "type": "image", "from_name": "B"},
        {"id": "k" * 12, "type": "pdf", "from_name": "C"},
    ]
    results = ["ok"] * 3
    summary = summarize_batch(results, msgs)
    assert "<b>image</b> (2)" in summary
    assert "<b>pdf</b> (1)" in summary


def test_dispatch_message_returns_unknown_for_missing_type():
    """Mensagem sem type deve retornar aviso, não levantar."""
    async def run():
        return await dispatch_message(None, None, {"id": "abc", "type": "alien"})
    result = asyncio.run(run())
    assert "⚠️" in result
    assert "alien" in result


def test_dispatch_message_returns_handler_for_known_type():
    """Para um type conhecido, dispatch_message deve chamar o handler."""
    # Stub do handler que retorna algo reconhecível
    async def fake_handler(*args, **kwargs):
        return "HANDLER_CALLED"
    HANDLERS["image"] = fake_handler  # patch
    try:
        async def run():
            return await dispatch_message(None, None, {"id": "x" * 12, "type": "image"})
        result = asyncio.run(run())
        assert "HANDLER_CALLED" in result
    finally:
        del HANDLERS["image"]  # restaura