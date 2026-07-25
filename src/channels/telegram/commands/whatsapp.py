"""Telegram /wa + /wa_resend commands — atalhos de status e reprocessamento."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import Message

from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.telegram.whatsapp")


def setup_whatsapp_handlers(dp: Dispatcher, pipeline: SeekerPipeline):

    @dp.message(F.text.regexp(r"^/wa(\s|$)"))
    async def cmd_wa(message: Message):
        """Atalho rápido de status do WhatsApp."""
        text = (message.text or "").strip()
        # /wa_resend é tratado em outro handler — não confundir
        if text.startswith("/wa_resend") or text.startswith("/wa_config"):
            return
        try:
            from src.channels.whatsapp.client import WhatsAppClient
            client = WhatsAppClient()
            cfg = _load_config_for_status()
            enabled = bool(cfg.get("enabled", False))
            target = cfg.get("target", {}) or {}
            group_full = target.get("group_id", "")
            group_short = group_full.split("@")[0][-12:] if group_full else "?"

            if not client.is_configured:
                await message.answer(
                    "⚠️ WhatsApp: <b>não configurado</b>\n"
                    "Defina <code>EVOLUTION_API_KEY</code> no .env e use "
                    "<code>/wa_config</code> para habilitar.",
                    parse_mode=ParseMode.HTML,
                )
                return

            state = await client.connection_state()
            await client.close()
            conn_state = state.get("state", "?") if isinstance(state, dict) else "?"
            conn_icon = "🟢" if conn_state == "open" else "🔴"

            text_out = (
                f"{conn_icon} <b>WhatsApp</b>\n\n"
                f"<b>Conexão:</b> {conn_state}\n"
                f"<b>Status:</b> {'✅ ativo' if enabled else '❌ desabilitado'}\n"
                f"<b>Grupo:</b> <code>{group_short}</code>\n"
                f"<b>Modo:</b> <code>{cfg.get('mode', 'evolution_api')}</code>\n\n"
                "<i>/wa_config para configurar · /wa_resend &lt;id&gt; para reprocessar</i>"
            )
            await message.answer(text_out, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.exception("[wa] cmd_wa falhou")
            await message.answer(f"❌ Erro: <code>{e}</code>", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/wa_resend"))
    async def cmd_wa_resend(message: Message):
        """Re-processa uma mensagem específica pelo ID."""
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.answer(
                "❌ Uso: <code>/wa_resend &lt;message_id&gt;</code>\n"
                "<i>Encontre o ID nos logs ou em /wa_config.</i>",
                parse_mode=ParseMode.HTML,
            )
            return
        msg_id = parts[1].strip()
        await message.answer(
            f"🔍 Buscando mensagem <code>{msg_id[:24]}</code> na Evolution API...",
            parse_mode=ParseMode.HTML,
        )

        try:
            from src.channels.whatsapp.client import WhatsAppClient
            from src.channels.whatsapp import router as whatsapp_router

            client = WhatsAppClient()
            if not client.is_configured:
                await message.answer("❌ Evolution API não configurada.")
                return

            cfg = _load_config_for_status()
            group_id = cfg.get("target", {}).get("group_id", "")

            # Busca a mensagem específica
            body = {"where": {"key": {"id": msg_id}}}
            raw_res = await client._request("POST", f"/chat/findMessages/{client.instance}", json_body=body)
            msgs_raw = raw_res.get("messages", []) if isinstance(raw_res, dict) else []
            if isinstance(msgs_raw, dict):
                msgs_raw = list(msgs_raw.values())

            target_raw = None
            if isinstance(msgs_raw, list) and len(msgs_raw) > 0:
                target_raw = msgs_raw[0]

            if not target_raw and group_id:
                # Fallback: busca mensagens recentes do grupo
                recent_msgs = await client.fetch_messages(group_id, limit=50)
                for m in recent_msgs:
                    if str(m.get("id", "")) == msg_id:
                        target_raw = m.get("raw", {})
                        break

            if not target_raw:
                await message.answer(f"⚠️ Mensagem <code>{msg_id[:24]}</code> não encontrada.")
                await client.close()
                return

            norm_msg = client._normalize_message(target_raw) if not target_raw.get("type") else target_raw
            if not norm_msg:
                await message.answer("⚠️ Falha ao normalizar mensagem.")
                await client.close()
                return

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

            res = await whatsapp_router.dispatch_message(client, vault, norm_msg)
            await client.close()

            await message.answer(
                f"🔄 <b>Reprocessamento do WhatsApp:</b>\n"
                f"ID: <code>{msg_id[:16]}</code>\n"
                f"Resultado: {res}",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            log.exception("[wa] cmd_wa_resend falhou")
            await message.answer(f"❌ Erro ao reprocessar: <code>{e}</code>", parse_mode=ParseMode.HTML)


def _load_config_for_status() -> dict[str, Any]:
    """Helper minimal para ler config (lazy import para evitar ciclo)."""
    from src.channels.telegram.commands.whatsapp_config import _load_config
    return _load_config()
