"""WhatsAppVaultGoal — poll Evolution API and dispatch messages to KnowledgeVault."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from src.channels.whatsapp import client as whatsapp_client_mod
from src.channels.whatsapp import router as whatsapp_router
from src.core.goals.protocol import (
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)
from src.skills.whatsapp_vault.seen_ids_store import SeenIdsStore

log = logging.getLogger("seeker.whatsapp_vault.goal")

DEFAULT_WINDOWS: list[tuple[int, int]] = [
    (2, 0),
    (6, 0),
    (10, 0),
    (14, 0),
    (18, 0),
    (22, 0),
]
DEFAULT_GROUP_ID = ""
DEFAULT_INSTANCE = "seeker-main"
DEFAULT_MAX_PER_CYCLE = 20
BUDGET_USD_PER_CYCLE = 0.50


class WhatsAppVaultGoal:
    """Poll Evolution API and dispatch new messages to KnowledgeVault."""

    WINDOWS = DEFAULT_WINDOWS
    DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "whatsapp_vault"

    def __init__(self, pipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._last_run = ""
        self._last_msg_ts_ms = 0
        self._seen_ids = SeenIdsStore(self.DATA_DIR / "seen_ids.json")
        self._client: whatsapp_client_mod.WhatsAppClient | None = None
        self._config: dict[str, Any] = self._load_config()

    @property
    def name(self) -> str:
        return "whatsapp_vault"

    @property
    def interval_seconds(self) -> int:
        """Return seconds until the next scheduled window."""
        now = datetime.now()
        now_minutes = now.hour * 60 + now.minute
        for hour, minute in self.WINDOWS:
            window_minutes = hour * 60 + minute
            if window_minutes > now_minutes:
                return (window_minutes - now_minutes) * 60
        first_hour, first_minute = self.WINDOWS[0]
        first_window = first_hour * 60 + first_minute
        return ((24 * 60 - now_minutes) + first_window) * 60

    @property
    def budget(self) -> GoalBudget:
        return GoalBudget(
            max_per_cycle_usd=BUDGET_USD_PER_CYCLE,
            max_daily_usd=2.0,
        )

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    def serialize_state(self) -> dict[str, Any]:
        return {
            "last_run": self._last_run,
            "last_msg_ts_ms": self._last_msg_ts_ms,
            "seen_ids_path": str(self._seen_ids.path),
        }

    def load_state(self, state: dict[str, Any]) -> None:
        self._last_run = state.get("last_run", "")
        self._last_msg_ts_ms = int(state.get("last_msg_ts_ms", 0))

    def _load_config(self) -> dict[str, Any]:
        """Load config/whatsapp.yaml on every cycle."""
        config_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "config"
            / "whatsapp.yaml"
        )
        if not config_path.exists():
            return {}
        try:
            import yaml

            with config_path.open("r", encoding="utf-8") as config_file:
                data = yaml.safe_load(config_file) or {}
            config = data.get("whatsapp", {}) if isinstance(data, dict) else {}
            return config if isinstance(config, dict) else {}
        except Exception as e:
            log.warning("[whatsapp] config/whatsapp.yaml erro: %s", e)
            return {}

    def _is_in_window(self) -> bool:
        """Return True only once for the current scheduled minute."""
        now = datetime.now()
        marker = now.strftime("%Y-%m-%d:%H:%M")
        if self._last_run == marker:
            return False
        return any((hour, minute) == (now.hour, now.minute) for hour, minute in self.WINDOWS)

    async def run_cycle(self) -> GoalResult:
        self._config = self._load_config()
        if not self._is_in_window():
            return GoalResult(
                success=True,
                summary=f"⏰ Aguardando janela (próx: {self.interval_seconds}s)",
            )

        self._status = GoalStatus.RUNNING
        try:
            target = self._config.get("target", {})
            schedule = self._config.get("schedule", {})
            target = target if isinstance(target, dict) else {}
            schedule = schedule if isinstance(schedule, dict) else {}
            group_id = target.get("group_id", DEFAULT_GROUP_ID)
            enabled = bool(self._config.get("enabled", False))
            if not enabled or not group_id:
                self._status = GoalStatus.IDLE
                return GoalResult(success=True, summary="WhatsApp vault desabilitado no config")

            if self._client is None:
                self._client = whatsapp_client_mod.WhatsAppClient()
            if not self._client.is_configured:
                self._status = GoalStatus.IDLE
                return GoalResult(success=True, summary="EVOLUTION_API_KEY não configurada")

            state = await self._client.connection_state()
            if state.get("state") != "open":
                self._status = GoalStatus.IDLE
                return GoalResult(success=False, summary=f"⚠️ WhatsApp desconectado: {state}")

            limit = int(schedule.get("max_per_cycle", DEFAULT_MAX_PER_CYCLE))
            messages = await self._client.fetch_messages(
                group_id,
                since_ts_ms=self._last_msg_ts_ms,
                limit=limit,
            )
            if not messages:
                self._status = GoalStatus.IDLE
                self._last_run = datetime.now().strftime("%Y-%m-%d:%H:%M")
                return GoalResult(
                    success=True,
                    summary=f"✅ Sem mensagens novas em {str(group_id)[-10:]}",
                )

            vault = getattr(self.pipeline, "knowledge_vault", None)
            if vault is None:
                vault = getattr(self.pipeline, "vault", None)
            if vault is None:
                from src.skills.knowledge_vault import KnowledgeVault

                inbox_path = self._config.get("vault", {}).get("path", "")
                vault = KnowledgeVault(
                    cascade_adapter=getattr(self.pipeline, "cascade_adapter", None),
                    vlm_client=getattr(self.pipeline, "vlm_client", None),
                    web_searcher=getattr(self.pipeline, "web_searcher", None),
                    inbox_path=inbox_path or None,
                )

            results: list[str] = []
            processed: list[dict[str, Any]] = []
            for msg in messages:
                msg_id = str(msg.get("id", "") or "")
                if self._seen_ids.is_seen(msg_id):
                    results.append(f"⏭ msg#{msg_id[:12]} já visto")
                    processed.append(msg)
                    continue
                result = await whatsapp_router.dispatch_message(self._client, vault, msg)
                results.append(result)
                processed.append(msg)
                self._seen_ids.add(msg_id, save_immediately=False)
                timestamp = msg.get("timestamp", 0)
                if isinstance(timestamp, (int, float)) and timestamp > self._last_msg_ts_ms:
                    self._last_msg_ts_ms = int(timestamp)

            self._seen_ids.flush()
            self._last_run = datetime.now().strftime("%Y-%m-%d:%H:%M")
            summary = whatsapp_router.summarize_batch(results, processed)
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary=summary,
                notification=summary,
                cost_usd=0.0,
                data={"processed_count": len(processed)},
            )
        except Exception as e:
            log.exception("[whatsapp] cycle falhou: %s", e)
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=False,
                summary=f"❌ Erro no WhatsApp: {type(e).__name__}: {str(e)[:200]}",
                notification=(
                    f"❌ <b>WhatsApp Vault</b> erro:\n"
                    f"<pre>{type(e).__name__}: {str(e)[:300]}</pre>"
                ),
            )


def create_goal(pipeline) -> WhatsAppVaultGoal:
    return WhatsAppVaultGoal(pipeline)
