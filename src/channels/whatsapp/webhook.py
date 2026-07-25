"""WhatsApp Webhook Handler — realiza ingestão em tempo real (<2s) a cada mensagem recebida via Push da Evolution API."""

from __future__ import annotations

import logging
from typing import Any
from pathlib import Path

from src.channels.whatsapp.client import WhatsAppClient
from src.channels.whatsapp import router as whatsapp_router
from src.skills.whatsapp_vault.seen_ids_store import SeenIdsStore

log = logging.getLogger("seeker.whatsapp.webhook")

_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "whatsapp_vault"
_SEEN_IDS = SeenIdsStore(_DATA_DIR / "seen_ids.json")


async def process_webhook_payload(payload: dict[str, Any], pipeline) -> dict[str, Any]:
    """Process an incoming Evolution API webhook payload.

    Expected payload structures from Evolution API v2.3.x:
      Event: MESSAGES_UPSERT / messages.upsert
      Body: {
        "event": "messages.upsert",
        "instance": "seeker-main",
        "data": {
            "key": {"remoteJid": "120363...@g.us", "id": "..."},
            "message": {...},
            ...
        }
      }
    """
    if not isinstance(payload, dict):
        return {"status": "ignored", "reason": "invalid_payload"}

    event = str(payload.get("event", "") or "").lower()
    if event and "message" not in event:
        return {"status": "ignored", "reason": f"unhandled_event_{event}"}

    data = payload.get("data")
    if not isinstance(data, dict):
        return {"status": "ignored", "reason": "no_data_field"}

    # Carrega config do whatsapp.yaml para validar o grupo alvo e status habilitado
    from src.channels.telegram.commands.whatsapp_config import _load_config
    cfg = _load_config()
    if not bool(cfg.get("enabled", False)):
        return {"status": "disabled", "reason": "whatsapp_vault_disabled_in_config"}

    target_group = str(cfg.get("target", {}).get("group_id", "") or "")
    sender_jid = str(data.get("key", {}).get("remoteJid", "") or "")

    if target_group and sender_jid and target_group not in sender_jid and sender_jid not in target_group:
        return {"status": "ignored", "reason": f"remoteJid_{sender_jid}_not_target"}

    client = WhatsAppClient()
    norm_msg = client._normalize_message(data)
    if not norm_msg:
        return {"status": "ignored", "reason": "could_not_normalize_message"}

    msg_id = str(norm_msg.get("id", "") or "")
    if msg_id and _SEEN_IDS.is_seen(msg_id):
        return {"status": "ignored", "reason": "already_seen", "id": msg_id}

    vault = getattr(pipeline, "knowledge_vault", None)
    if vault is None:
        vault = getattr(pipeline, "vault", None)
    if vault is None:
        from src.skills.knowledge_vault import KnowledgeVault
        vault = KnowledgeVault(
            cascade_adapter=getattr(pipeline, "cascade_adapter", None),
            vlm_client=getattr(pipeline, "vlm_client", None),
            web_searcher=getattr(pipeline, "web_searcher", None),
        )

    log.info(f"[whatsapp/webhook] Processando mensagem instantânea msg#{msg_id[:12]} ({norm_msg.get('type')})")
    result = await whatsapp_router.dispatch_message(client, vault, norm_msg)

    if msg_id:
        _SEEN_IDS.add(msg_id, save_immediately=True)

    await client.close()
    return {
        "status": "success",
        "id": msg_id,
        "type": norm_msg.get("type"),
        "result": result,
    }
