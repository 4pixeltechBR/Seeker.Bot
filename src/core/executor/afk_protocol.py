"""AFK Protocol — User Status Tracking & Escalation (Track B3)"""
import logging
from datetime import datetime, timedelta
from enum import Enum

log = logging.getLogger("executor.afk_protocol")

class UserStatus(Enum):
    """Status do usuário"""
    ONLINE = "online"          # Respondendo ativamente
    IDLE = "idle"              # Offline mas sem ação manual necessária
    AWAY = "away"              # AFK > 30 min
    SLEEP = "sleep"            # AFK > 8h

class AFKProtocol:
    """Rastreia status do usuário e escalona ações quando AFK"""

    def __init__(self, user_id: str = "unknown"):
        self.user_id = user_id
        self.last_interaction: datetime = datetime.utcnow()
        self.status: UserStatus = UserStatus.ONLINE
        self.afk_start: datetime = None

    def update_interaction(self):
        """Registra interação do usuário (mensagem Telegram, resposta, etc)"""
        self.last_interaction = datetime.utcnow()
        self.status = UserStatus.ONLINE
        self.afk_start = None
        log.info("[afk] User online")

    def get_afk_hours(self) -> float:
        """Retorna quantas horas user está AFK"""
        if self.status == UserStatus.ONLINE:
            return 0.0

        elapsed = datetime.utcnow() - self.last_interaction
        return elapsed.total_seconds() / 3600

    def update_status(self, status: "UserStatus" = None) -> UserStatus:
        """
        Atualiza status baseado em tempo decorrido ou status fornecido.

        Args:
            status: Status to set directly (optional)

        Returns:
            Status atual
        """
        if status is not None:
            self.status = status
            return self.status

        if self.status == UserStatus.ONLINE:
            return self.status

        afk_hours = self.get_afk_hours()

        if afk_hours > 8:
            self.status = UserStatus.SLEEP
        elif afk_hours > 0.5:
            self.status = UserStatus.AWAY
        else:
            self.status = UserStatus.IDLE

        return self.status

    def is_action_allowed(self, approval_tier: "ApprovalTier") -> bool:
        """
        Verifica se ação é permitida baseado no status AFK e tier de aprovação.

        Args:
            approval_tier: ApprovalTier da ação

        Returns:
            True se ação é permitida
        """
        from src.core.executor import ApprovalTier

        # L2_SILENT sempre permitido
        if approval_tier == ApprovalTier.L2_SILENT:
            return True

        # L1_LOGGED permitido até 6h AFK
        if approval_tier == ApprovalTier.L1_LOGGED:
            afk_hours = self.get_afk_hours()
            return afk_hours <= 6

        # L0_MANUAL só permitido se online
        if approval_tier == ApprovalTier.L0_MANUAL:
            return self.status == UserStatus.ONLINE

        return False

    async def escalate_if_needed(self, telegram_client, action_id: str, approval_tier: str):
        """Escalona para Telegram se ação precisa aprovação manual"""
        if approval_tier == "l0_manual":
            msg = f"⚠️ Ação {action_id} requer aprovação manual. Responda com 'sim' ou 'não'"
            await telegram_client.send_message(msg)
            log.info(f"[afk] Escalado para Telegram: {action_id}")


# Alias para compatibilidade
AFKProtocolCoordinator = AFKProtocol
