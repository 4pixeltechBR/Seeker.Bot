"""
WhatsAppClient — async HTTP client for Evolution API v2.3.7.

Evolution API is a self-hosted Baileys-based REST server for WhatsApp Web.
The Seeker polls this server periodically to fetch new messages from a target
group, then dispatches them to the KnowledgeVault via WhatsAppRouter.

Endpoints used:
  GET  /group/findAllGroups/{instance}      → list all groups the bot joined
  POST /chat/findMessages/{instance}        → fetch messages with filters
  GET  /message/findMedia/{instance}        → download base64-encoded media
  GET  /instance/connectionState/{instance} → check WhatsApp session status

Reference: https://docs.evolutionfoundation.com.br/

Config (loaded from env via os.getenv):
  EVOLUTION_BASE_URL  default "http://localhost:8080"
  EVOLUTION_API_KEY    required (in .env as AUTHENTICATION_API_KEY equivalent)
  EVOLUTION_INSTANCE   default "seeker-main"
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import aiohttp

log = logging.getLogger("seeker.whatsapp.client")


class WhatsAppClient:
    """Async HTTP client for Evolution API. Uses `apikey` header for auth."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        instance: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("EVOLUTION_BASE_URL", "http://localhost:8080")).rstrip("/")
        self.api_key = api_key or os.getenv("EVOLUTION_API_KEY", "")
        self.instance = instance or os.getenv("EVOLUTION_INSTANCE", "seeker-main")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key) and bool(self.base_url)

    @property
    def headers(self) -> dict[str, str]:
        return {
            "apikey": self.api_key,
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
            self._session = aiohttp.ClientSession(
                timeout=self.timeout, connector=connector
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generic HTTP request wrapper with error handling."""
        if not self.is_configured:
            return {"error": "not_configured", "message": "EVOLUTION_API_KEY not set"}
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        try:
            async with session.request(
                method,
                url,
                headers=self.headers,
                json=json_body,
                params=params,
            ) as resp:
                body = await resp.json() if resp.content_length != 0 else {}
                if resp.status >= 400:
                    log.warning(
                        f"[whatsapp] {method} {path} → HTTP {resp.status}: {body}"
                    )
                    return {"error": f"http_{resp.status}", "body": body}
                return body
        except asyncio.TimeoutError:
            log.warning(f"[whatsapp] {method} {path} → timeout após {self.timeout.total}s")
            return {"error": "timeout"}
        except aiohttp.ClientError as e:
            log.warning(f"[whatsapp] {method} {path} → connection error: {e}")
            return {"error": "connection_error", "message": str(e)}

    async def connection_state(self) -> dict[str, Any]:
        """Check WhatsApp session status.

        Returns: {"state": "open"|"close"|"connecting", "instance": "seeker-main"}
        On error: {"error": "...", ...}
        """
        return await self._request(
            "GET", f"/instance/connectionState/{self.instance}"
        )

    async def find_groups(self) -> list[dict[str, Any]]:
        """List all groups the bot joined.

        Returns list of {"id": "120363..@g.us", "subject": "...", "size": 47, "subject_time": 123, "last_message_ts": 123}
        Empty list on error.
        """
        result = await self._request(
            "GET", f"/group/fetchAllGroups/{self.instance}?getParticipants=false"
        )
        # A resposta da Evolution API pode ser:
        #   1) {"error": "..."}  → erro
        #   2) {"groups": [...]}  → envelope (raro nesta versão)
        #   3) [...]  → lista direta (caso comum em v2.3.x)
        if isinstance(result, dict) and "error" in result:
            return []
        if isinstance(result, list):
            groups = result
        elif isinstance(result, dict):
            groups = result.get("groups", [])
        else:
            groups = []
        return [
            {
                "id": g.get("id") or g.get("jid") or g.get("groupJid", ""),
                "subject": g.get("subject") or g.get("name", ""),
                "size": g.get("size") or g.get("participants", 0),
                "subject_time": g.get("subjectTime") or g.get("subject_time") or 0,
                "last_message_ts": g.get("lastMessageTimestamp") or g.get("last_message_timestamp") or g.get("lastMessageTs") or 0,
                "creation": g.get("creation") or 0,
            }
            for g in groups
            if isinstance(g, dict)
        ]

    async def find_recent_groups(self, limit: int = 15) -> list[dict[str, Any]]:
        """List the most recently active groups.

        Sorts by best-available activity proxy:
          1. last_message_ts (if Evolution API provides it)
          2. subject_time (when subject was last changed — proxy for admin activity)
          3. creation (group age)

        Returns up to `limit` groups, most recent first.
        Empty list on error.
        """
        all_groups = await self.find_groups()
        if not all_groups:
            return []

        def _activity_key(g: dict[str, Any]) -> tuple[int, int, int]:
            return (
                int(g.get("last_message_ts") or 0),
                int(g.get("subject_time") or 0),
                int(g.get("creation") or 0),
            )

        all_groups.sort(key=_activity_key, reverse=True)
        return all_groups[:limit]

    async def fetch_messages(
        self,
        group_id: str,
        since_ts_ms: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch messages from a group with timestamp >= since_ts_ms.

        Returns list of normalized message dicts:
          {
            "id": "...",       # WhatsApp message ID
            "timestamp": 12345, # epoch ms
            "from": "5511..",   # sender (without @s.whatsapp.net)
            "from_name": "Victor",
            "type": "image|pdf|zip|youtube|site|text|location|sticker|poll|audio|video|document",
            "text": "caption or message body",
            "media_url": "...",  # if has media (full URL or just mediaKey)
            "media_mimetype": "image/jpeg",
            "media_size": 12345,
            "raw": {...}        # original evolution-api payload
          }
        Returns [] on error or if no messages.

        NOTE: Evolution API v2 has TWO different fetch endpoints depending on version.
        We use POST /chat/findMessages/{instance} which is the canonical one.
        Body: {"where": {"key": {"remoteJid": group_id}}, "limit": limit}
        For time filter, append: "since": since_ts_ms (ms epoch) — only returns newer.
        """
        if not group_id:
            return []
        body: dict[str, Any] = {
            "where": {"key": {"remoteJid": group_id}},
            "limit": limit,
        }
        if since_ts_ms > 0:
            # newer than X (epoch ms) — uses internal "since" filter
            body["since"] = since_ts_ms

        result = await self._request(
            "POST", f"/chat/findMessages/{self.instance}", json_body=body
        )
        if "error" in result:
            log.warning(f"[whatsapp] fetch_messages falhou: {result.get('error')}")
            return []

        # Evolution API returns either {"messages": {...}} with timestamp-keyed dict,
        # or a flat list. Normalize to list.
        msgs_data = result.get("messages", {})
        if isinstance(msgs_data, dict):
            # timestamp-keyed dict: {ts1: msg1, ts2: msg2, ...}
            messages = list(msgs_data.values())
        elif isinstance(msgs_data, list):
            messages = msgs_data
        else:
            messages = []

        normalized = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            norm = self._normalize_message(m)
            if norm is not None:
                normalized.append(norm)
        # Sort ascending by timestamp
        normalized.sort(key=lambda x: x.get("timestamp", 0))
        return normalized

    def _normalize_message(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Convert Evolution API message → internal normalized format.

        Type detection logic (most specific first):
          - Has "messageType": "location" → "location"
          - Has "messageType": "pollCreationMessage" → "poll"
          - Has "messageType": "stickerMessage" → "sticker"
          - Has "mediaUrl" + mimetype → extension-based (image/pdf/zip/etc.)
          - "conversation" or "extendedTextMessage" with text → check for URLs → "youtube"|"site"|"text"
          - Fallback "text"
        """
        msg_type = (raw.get("messageType") or raw.get("type") or "").lower()
        ts = raw.get("messageTimestamp") or raw.get("timestamp")
        if isinstance(ts, (int, float)):
            ts_int = int(ts * 1000) if ts < 10_000_000_000 else int(ts)
        else:
            ts_int = int(time.time() * 1000)

        text = (raw.get("message") or {}).get("conversation") or \
               (raw.get("message") or {}).get("extendedTextMessage", {}).get("text") or ""
        if not text and "message" in raw and isinstance(raw["message"], str):
            text = raw["message"]

        # Sender extraction
        sender_jid = raw.get("key", {}).get("participant") or raw.get("key", {}).get("remoteJid", "")
        sender = sender_jid.split("@")[0] if "@" in sender_jid else sender_jid
        sender_name = (
            raw.get("pushName") or raw.get("notifyName") or
            (raw.get("participant", {}).get("name") if isinstance(raw.get("participant"), dict) else "") or
            sender
        )

        # Media detection
        msg_obj = raw.get("message", {})
        mimetype = ""
        media_url = ""
        media_key = ""
        media_size = 0
        if isinstance(msg_obj, dict):
            for mtype in ("imageMessage", "videoMessage", "audioMessage", "documentMessage",
                          "stickerMessage", "pttMessage"):
                m = msg_obj.get(mtype)
                if isinstance(m, dict):
                    mimetype = m.get("mimetype", "")
                    media_url = m.get("mediaUrl") or m.get("url") or ""
                    media_key = m.get("mediaKey", "") or m.get("fileLength", "")
                    media_size = m.get("fileLength", 0) or 0
                    break

        # Type classification
        classified_type = "text"
        if msg_type == "location" or "locationMessage" in msg_obj:
            classified_type = "location"
        elif msg_type == "stickerMessage" or "stickerMessage" in msg_obj:
            classified_type = "sticker"
        elif msg_type == "pollcreationmessage" or "pollCreationMessage" in msg_obj:
            classified_type = "poll"
        elif mimetype:
            if mimetype.startswith("image/"):
                classified_type = "image"
            elif mimetype.startswith("audio/"):
                classified_type = "audio"
            elif mimetype.startswith("video/"):
                classified_type = "video"
            elif mimetype in ("application/pdf",):
                classified_type = "pdf"
            elif mimetype in ("application/zip", "application/x-zip-compressed"):
                classified_type = "zip"
            elif "word" in mimetype or "officedocument.wordprocessing" in mimetype:
                classified_type = "docx"
            elif "excel" in mimetype or "officedocument.spreadsheet" in mimetype:
                classified_type = "xlsx"
            elif "powerpoint" in mimetype or "officedocument.presentation" in mimetype:
                classified_type = "pptx"
        elif text:
            # URL-based classification
            t_lower = text.lower()
            if "youtube.com" in t_lower or "youtu.be" in t_lower:
                classified_type = "youtube"
            elif "github.com/" in t_lower:
                classified_type = "github"
            elif "http://" in t_lower or "https://" in t_lower:
                classified_type = "site"

        # Stability: avoid returning totally empty messages
        if classified_type == "text" and not text.strip():
            return None

        return {
            "id": raw.get("key", {}).get("id", ""),
            "timestamp": ts_int,
            "from": sender,
            "from_name": sender_name,
            "type": classified_type,
            "text": text.strip(),
            "media_url": media_url,
            "media_mimetype": mimetype,
            "media_size": media_size,
            "media_key": media_key,
            "raw": raw,
        }

    async def fetch_media_by_id(self, message_id: str, media_key: str = "") -> bytes:
        """Fetch base64-encoded media using Evolution API's /message/findMedia endpoint."""
        if not message_id:
            return b""
        import base64
        body: dict[str, Any] = {
            "message": {
                "key": {
                    "id": message_id
                }
            }
        }
        if media_key:
            body["mediaKey"] = media_key

        res = await self._request("POST", f"/message/findMedia/{self.instance}", json_body=body)
        if isinstance(res, dict) and "error" not in res:
            b64_str = res.get("base64") or res.get("media", "")
            if isinstance(b64_str, str) and b64_str:
                if "," in b64_str:
                    b64_str = b64_str.split(",", 1)[1]
                try:
                    return base64.b64decode(b64_str)
                except Exception as e:
                    log.warning(f"[whatsapp] base64 decode falhou: {e}")
        return b""

    async def download_media(self, media_url_or_key: str, message_id: str = "") -> bytes:
        """Download media bytes from Evolution API.

        If media_url_or_key is a full URL, fetches it directly.
        If it fails or is missing, falls back to /message/findMedia using message_id.
        """
        if media_url_or_key and media_url_or_key.startswith("http"):
            data = await self._download_url_bytes(media_url_or_key)
            if data:
                return data

        if message_id:
            return await self.fetch_media_by_id(message_id, media_key=media_url_or_key)

        return b""

    async def _download_url_bytes(self, url: str) -> bytes:
        session = await self._get_session()
        try:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status != 200:
                    log.warning(f"[whatsapp] media download failed: {resp.status}")
                    return b""
                return await resp.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning(f"[whatsapp] media download error: {e}")
            return b""

    async def send_text(self, to_jid: str, text: str) -> dict[str, Any]:
        """Send a text message back to a chat/group (optional utility, used for tests)."""
        if not to_jid:
            return {"error": "missing_to_jid"}
        body = {"number": to_jid, "text": text}
        return await self._request(
            "POST", f"/message/sendText/{self.instance}", json_body=body
        )
