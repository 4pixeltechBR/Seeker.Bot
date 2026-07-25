"""WhatsAppRouter — top-level dispatcher for normalized WhatsApp messages."""

from __future__ import annotations

import html
import logging
from typing import Any

from . import media_handlers

log = logging.getLogger("seeker.whatsapp.router")

HANDLERS = {
    "image": media_handlers.download_and_process,
    "pdf": media_handlers.download_and_process,
    "zip": media_handlers.download_and_process,
    "audio": media_handlers.download_and_process,
    "video": media_handlers.download_and_process,
    "docx": media_handlers.download_and_process,
    "xlsx": media_handlers.download_and_process,
    "pptx": media_handlers.download_and_process,
    "vcard": media_handlers.download_and_process,
    "youtube": media_handlers.process_text_or_url,
    "github": media_handlers.process_text_or_url,
    "site": media_handlers.process_text_or_url,
    "text": media_handlers.process_text_or_url,
    "location": media_handlers.process_special,
    "sticker": media_handlers.process_special,
    "poll": media_handlers.process_special,
}


async def dispatch_message(client, vault, msg: dict[str, Any]) -> str:
    """Dispatch a normalized WhatsApp message to its handler."""
    msg_type = str(msg.get("type", "unknown") or "unknown")
    msg_id = str(msg.get("id", "") or "")[:12]
    handler = HANDLERS.get(msg_type)
    if handler is None:
        return f"⚠️ msg#{msg_id}: tipo {msg_type} sem handler"

    if handler is media_handlers.download_and_process:
        return await handler(client, vault, msg)
    return await handler(vault, msg)


def summarize_batch(results: list[str], msgs: list[dict[str, Any]]) -> str:
    """Build a Telegram-readable HTML summary of processed messages."""
    type_emoji = {
        "image": "📸",
        "pdf": "📄",
        "zip": "📦",
        "audio": "🎵",
        "video": "🎬",
        "docx": "📃",
        "xlsx": "📊",
        "pptx": "🎞️",
        "vcard": "👤",
        "youtube": "🎬",
        "github": "🐙",
        "site": "🌐",
        "text": "💬",
        "location": "📍",
        "sticker": "🎨",
        "poll": "📊",
        "pdf_url": "📄",
    }

    by_type: dict[str, list[str]] = {}
    for result, msg in zip(results, msgs):
        msg_type = str(msg.get("type", "unknown") or "unknown")
        by_type.setdefault(msg_type, []).append(str(result))

    lines = [f"🟢 WhatsApp batch: <b>{len(results)} mensagens processadas</b>"]
    for msg_type, items in sorted(by_type.items()):
        emoji = type_emoji.get(msg_type, "📌")
        lines.append(f"\n{emoji} <b>{html.escape(msg_type)}</b> ({len(items)})")
        for item in items[:3]:
            short = html.escape(item[:120])
            lines.append(f"  · <i>{short}</i>")
        if len(items) > 3:
            lines.append(f"  · +{len(items) - 3} mais")
    return "\n".join(lines)
