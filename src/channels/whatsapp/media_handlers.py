"""WhatsApp media downloaders and MIME-type to vault dispatch."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("seeker.whatsapp.media")

MIME_DISPATCH = {
    ("image/jpeg", "image/png", "image/webp", "image/heic"): "process_images",
    ("application/pdf",): "process_pdf",
    ("application/zip", "application/x-zip-compressed"): "process_zip",
    (
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ): "process_docx",
    (
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ): "process_xlsx",
    (
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ): "process_pptx",
    ("text/vcard", "text/x-vcard", "application/vcard"): "process_vcard",
}


def _message_label(msg_id: Any) -> str:
    return str(msg_id or "")[:12]


async def download_and_process(
    client,
    vault,
    msg: dict[str, Any],
    max_size_bytes: int = 50 * 1024 * 1024,
) -> str:
    """Download media and dispatch it to the matching vault processor."""
    mimetype = str(msg.get("media_mimetype", "") or "").lower().strip()
    msg_id_full = str(msg.get("id", "") or "")
    msg_id = _message_label(msg_id_full)

    if not media_url and not msg_id_full:
        return f"⚠️ msg#{msg_id}: sem URL de mídia ou ID de mensagem"

    try:
        media_bytes = await client.download_media(media_url, message_id=msg_id_full)
    except Exception as e:
        log.warning("[whatsapp] media download falhou: %s", e)
        return f"❌ msg#{msg_id}: download falhou"

    if not media_bytes:
        return f"❌ msg#{msg_id}: download falhou"
    if len(media_bytes) > max_size_bytes:
        return (
            f"⚠️ msg#{msg_id}: arquivo muito grande "
            f"({len(media_bytes) / 1024 / 1024:.1f}MB > "
            f"{max_size_bytes / 1024 / 1024:.0f}MB)"
        )

    method_name = None
    for mimes, candidate in MIME_DISPATCH.items():
        if mimetype in mimes:
            method_name = candidate
            break

    if not method_name and mimetype.startswith("audio/"):
        method_name = "process_audio_idea"
    if not method_name and mimetype.startswith("video/"):
        method_name = "process_video"

    if not method_name:
        return f"⚠️ msg#{msg_id}: mimetype {mimetype} não suportado"

    method = getattr(vault, method_name, None)
    if method is None:
        return f"❌ msg#{msg_id}: vault sem método {method_name}"

    try:
        if method_name == "process_images":
            result = await method([media_bytes], user_hint=text)
        elif method_name == "process_audio_idea":
            result = await method(media_bytes)
        else:
            result = await method(media_bytes, user_hint=text)
        return f"✅ msg#{msg_id} ({mimetype}): {result}"
    except Exception as e:
        log.warning("[whatsapp] media handler falhou: %s", e)
        return f"❌ msg#{msg_id}: {type(e).__name__}: {str(e)[:80]}"


async def process_text_or_url(vault, msg: dict[str, Any]) -> str:
    """Process a text message as a URL, repository link, or plain text."""
    text = str(msg.get("text", "") or "").strip()
    msg_id = _message_label(msg.get("id", ""))
    if not text:
        return f"⚠️ msg#{msg_id}: texto vazio"

    t_lower = text.lower()
    if "youtube.com" in t_lower or "youtu.be" in t_lower:
        method_name = "process_youtube"
    elif "github.com/" in t_lower and "/" in text:
        method_name = "process_repo"
    elif "http://" in t_lower or "https://" in t_lower:
        method_name = "process_site"
    else:
        method_name = "process_text"

    method = getattr(vault, method_name, None)
    if method is None:
        return f"⚠️ msg#{msg_id}: vault indisponível para texto"

    try:
        result = await method(text)
        return f"✅ msg#{msg_id}: {result}"
    except Exception as e:
        log.warning("[whatsapp] text/url handler falhou: %s", e)
        return f"❌ msg#{msg_id}: {type(e).__name__}: {str(e)[:80]}"


async def process_special(vault, msg: dict[str, Any]) -> str:
    """Process location, sticker, and poll messages."""
    msg_type = str(msg.get("type", "") or "")
    msg_id = _message_label(msg.get("id", ""))
    raw = msg.get("raw", {})
    raw_message = raw.get("message", {}) if isinstance(raw, dict) else {}
    if not isinstance(raw_message, dict):
        raw_message = {}

    if msg_type == "location":
        location = raw_message.get("locationMessage", raw_message)
        if not isinstance(location, dict):
            location = {}
        lat = location.get("degreesLatitude", location.get("latitude"))
        lon = location.get("degreesLongitude", location.get("longitude"))
        if lat is None or lon is None:
            return f"⚠️ msg#{msg_id}: location sem lat/lon"
        try:
            result = await vault.process_location(
                float(lat), float(lon), name=str(msg.get("text", "") or "")
            )
        except Exception as e:
            log.warning("[whatsapp] location handler falhou: %s", e)
            return f"❌ msg#{msg_id}: {type(e).__name__}: {str(e)[:80]}"
        return f"✅ msg#{msg_id} (location): {result}"

    if msg_type == "sticker":
        try:
            result = await vault.process_sticker(
                source_label=str(msg.get("from_name", "Sticker") or "Sticker")
            )
        except Exception as e:
            log.warning("[whatsapp] sticker handler falhou: %s", e)
            return f"❌ msg#{msg_id}: {type(e).__name__}: {str(e)[:80]}"
        return f"✅ msg#{msg_id} (sticker): {result}"

    if msg_type == "poll":
        raw_poll = raw_message.get("pollCreationMessage", {})
        if not isinstance(raw_poll, dict):
            raw_poll = {}
        question = str(raw_poll.get("name", msg.get("text", "Enquete")) or "Enquete")
        options_raw = raw_poll.get("options", [])
        options = [
            str(option.get("optionName", "") or "")
            for option in options_raw
            if isinstance(option, dict)
        ]
        options = options or ["?"]
        votes: dict[str, int] = {}
        votes_raw = raw_poll.get("votes", [])
        if isinstance(votes_raw, dict):
            for key, value in votes_raw.items():
                if isinstance(value, (int, float)):
                    votes[str(key)] = int(value)
        elif isinstance(votes_raw, list):
            for vote in votes_raw:
                if not isinstance(vote, dict):
                    continue
                selected = vote.get("selectedOptions", [])
                if not isinstance(selected, list):
                    continue
                for option_index in selected:
                    key = str(option_index)
                    votes[key] = votes.get(key, 0) + 1
        try:
            result = await vault.process_poll(question, options, votes)
        except Exception as e:
            log.warning("[whatsapp] poll handler falhou: %s", e)
            return f"❌ msg#{msg_id}: {type(e).__name__}: {str(e)[:80]}"
        return f"✅ msg#{msg_id} (poll): {result}"

    return f"⚠️ msg#{msg_id}: tipo {msg_type} desconhecido"
