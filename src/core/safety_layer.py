"""
Seeker.Bot — Safety Layer
Tier-based autonomy + kill switch para ações irreversíveis.

Tiers:
- L1: Requer aprovação manual para TUDO
- L2: Requer aprovação para escrita/irreversível
- L3: Autonomo (com proteções + logging)

Uso:
    safety = SafetyLayer()
    if not await safety.check(action="delete_db", tier=3, reason="cleanup"):
        return  # Bloqueou
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

log = logging.getLogger("seeker.safety")


class AutonomyTier(int, Enum):
    """Níveis de autonomia permitida."""
    L1 = 1  # Manual approval
    L2 = 2  # Reversible (write) → auto, irreversible → manual
    L3 = 3  # Autonomous (com proteções)


class ActionType(str, Enum):
    """Tipos de ação com diferentes riscos."""
    READ = "read"                  # Sem risco
    WRITE = "write"                # Reversível
    DELETE = "delete"              # Irreversível
    EXEC = "exec"                  # Execução (scripts)
    TRANSFER = "transfer"          # Transferência de dados
    CONFIG = "config"              # Mudança de configuração


@dataclass
class ActionContext:
    """Contexto de uma ação para validação."""
    action: ActionType
    tier: AutonomyTier
    reason: str
    details: Optional[dict] = None
    user_id: Optional[int] = None


class SafetyLayer:
    """
    Camada de segurança com kill switch e tier-based autonomy.
    """

    def __init__(self, kill_switch_enabled: bool = True):
        self._kill_switch_enabled = kill_switch_enabled
        self._killed = False
        self._blocked_actions = 0
        self._approved_actions = 0

        # Whitelist de ações auto-permitidas por tier
        self._auto_allowed = {
            AutonomyTier.L1: [ActionType.READ],
            AutonomyTier.L2: [ActionType.READ, ActionType.WRITE],
            AutonomyTier.L3: [
                ActionType.READ,
                ActionType.WRITE,
                ActionType.CONFIG,  # Config changes allowed
            ],
        }

        # Blacklist: ações NUNCA permitidas
        self._never_allowed = [
            ActionType.DELETE,      # Deletion requer manual approval
            ActionType.TRANSFER,    # Money transfer requer manual approval
        ]

    def enable_kill_switch(self) -> None:
        """Ativa kill switch — bloqueia TUDO."""
        self._killed = True
        self._kill_switch_enabled = True
        log.critical("[safety] KILL SWITCH ATIVADO — BLOQUEANDO TODAS AS AÇÕES")

    def disable_kill_switch(self) -> None:
        """Desativa kill switch."""
        if self._killed:
            log.warning("[safety] Kill switch desativado")
        self._killed = False

    async def check(
        self,
        action: ActionType | str,
        tier: AutonomyTier | int = AutonomyTier.L3,
        reason: str = "",
        details: Optional[dict] = None,
        user_id: Optional[int] = None,
    ) -> bool:
        """
        Valida se ação é permitida.

        Returns:
            True: ação permitida
            False: ação bloqueada
        """
        # Converte strings para enums
        if isinstance(action, str):
            action = ActionType(action)
        if isinstance(tier, int):
            tier = AutonomyTier(tier)

        ctx = ActionContext(
            action=action,
            tier=tier,
            reason=reason,
            details=details,
            user_id=user_id,
        )

        # ────────────────────────────────────────────────
        # FASE 1: Kill Switch
        # ────────────────────────────────────────────────
        if self._kill_switch_enabled and self._killed:
            log.critical(
                f"[safety] KILL SWITCH ATIVO — Bloqueando: {action.value} "
                f"(tier={tier.name}, reason={reason})"
            )
            self._blocked_actions += 1
            return False

        # ────────────────────────────────────────────────
        # FASE 2: Blacklist (Nunca Permitidas)
        # ────────────────────────────────────────────────
        if action in self._never_allowed:
            log.warning(
                f"[safety] BLACKLIST: {action.value} requer aprovação manual "
                f"(tier={tier.name}, reason={reason})"
            )
            self._blocked_actions += 1
            return False  # Sempre requer manual approval

        # ────────────────────────────────────────────────
        # FASE 3: Whitelist por Tier
        # ────────────────────────────────────────────────
        allowed_for_tier = self._auto_allowed.get(tier, [])
        if action in allowed_for_tier:
            log.info(
                f"[safety] ✅ AUTO-APPROVED: {action.value} "
                f"(tier={tier.name}, reason={reason})"
            )
            self._approved_actions += 1
            return True

        # ────────────────────────────────────────────────
        # FASE 4: Fallback — Bloqueia e Loga
        # ────────────────────────────────────────────────
        log.warning(
            f"[safety] BLOQUEADO: {action.value} não permitido em tier {tier.name} "
            f"(reason={reason})"
        )
        self._blocked_actions += 1
        return False

    def get_stats(self) -> dict:
        """Retorna estatísticas de safety."""
        total = self._approved_actions + self._blocked_actions
        return {
            "approved": self._approved_actions,
            "blocked": self._blocked_actions,
            "total_checks": total,
            "approval_rate_pct": round(
                (self._approved_actions / total * 100) if total > 0 else 0, 1
            ),
            "kill_switch_active": self._killed,
        }

    async def audit_log(
        self,
        action: ActionType | str,
        tier: AutonomyTier | int,
        approved: bool,
        reason: str = "",
        user_id: Optional[int] = None,
    ) -> None:
        """Registra decisão de segurança para auditoria."""
        status = "APPROVED" if approved else "BLOCKED"
        log.info(
            f"[audit] {status} | action={action} | tier={tier} | "
            f"user={user_id} | reason={reason}"
        )


# Singleton global
_safety_layer: Optional[SafetyLayer] = None


def get_safety_layer() -> SafetyLayer:
    """Retorna instância global de SafetyLayer."""
    global _safety_layer
    if _safety_layer is None:
        _safety_layer = SafetyLayer()
    return _safety_layer
