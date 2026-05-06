"""
Seeker.Bot — Enhanced Safety Layer (Sprint 7.3)
src/core/safety_layer_enhanced.py

Controla autonomia de goals através de:
- Autonomy Tiers: L0 (manual) → L1 (log) → L2 (silencioso)
- Action Whitelist/Blacklist: Autorização granular por tipo de ação

Substituir/estender safety_layer.py existente
"""

import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Set

log = logging.getLogger("seeker.safety")


class AutonomyTier(Enum):
    """Níveis de autonomia para goals e actions (valores decrescentes em restrição)"""
    L0_MANUAL = 100     # Requer aprovação manual antes de executar (mais restritivo)
    L1_LOGGED = 50      # Executa automaticamente mas com auditoria completa
    L2_SILENT = 0       # Executa silenciosamente (menos restritivo)


class ActionType(Enum):
    """Tipos de ações que podem ser executadas"""
    # Leitura (sempre permitido)
    READ_DATA = "read_data"
    READ_FILE = "read_file"
    READ_API = "read_api"

    # Escrita (requer L1+ com log)
    WRITE_DATA = "write_data"
    WRITE_FILE = "write_file"
    API_CALL = "api_call"
    SEND_MESSAGE = "send_message"

    # Destruição (requer L2 + whitelist explícita)
    DELETE_FILE = "delete_file"
    DELETE_DATA = "delete_data"
    MODIFY_SYSTEM = "modify_system"

    # Transferências (requer L1 com aprovação)
    TRANSFER_FUNDS = "transfer_funds"
    SEND_EMAIL_EXTERNAL = "send_email_external"


class SafetyPolicy:
    """Política de segurança para o Seeker.Bot"""

    def __init__(self):
        # Autonomy level padrão por tipo de ação
        self.default_tiers = {
            ActionType.READ_DATA: AutonomyTier.L2_SILENT,
            ActionType.READ_FILE: AutonomyTier.L2_SILENT,
            ActionType.READ_API: AutonomyTier.L2_SILENT,

            ActionType.WRITE_DATA: AutonomyTier.L1_LOGGED,
            ActionType.WRITE_FILE: AutonomyTier.L1_LOGGED,
            ActionType.API_CALL: AutonomyTier.L1_LOGGED,
            ActionType.SEND_MESSAGE: AutonomyTier.L1_LOGGED,

            ActionType.DELETE_FILE: AutonomyTier.L0_MANUAL,
            ActionType.DELETE_DATA: AutonomyTier.L0_MANUAL,
            ActionType.MODIFY_SYSTEM: AutonomyTier.L0_MANUAL,

            ActionType.TRANSFER_FUNDS: AutonomyTier.L0_MANUAL,
            ActionType.SEND_EMAIL_EXTERNAL: AutonomyTier.L1_LOGGED,
        }

        # Whitelist de ações permitidas (por tipo)
        # Se action está aqui, pode executar com seu tier padrão
        self.action_whitelist: Set[ActionType] = set(self.default_tiers.keys())

        # Blacklist de ações explicitamente proibidas
        self.action_blacklist: Set[ActionType] = set()

        # Custom tiers (sobrescreve defaults)
        self.custom_tiers: dict[ActionType, AutonomyTier] = {}

        # Goals com tier elevado (bypass L0 para ações específicas)
        self.trusted_goals: Set[str] = set()

    def allow_action(
        self,
        action_type: ActionType,
        goal_name: str = "unknown",
        current_tier: AutonomyTier = AutonomyTier.L1_LOGGED,
    ) -> tuple[bool, str]:
        """
        Verifica se uma ação é permitida.

        Returns: (allowed, reason)
        """
        # 1. Verificar blacklist
        if action_type in self.action_blacklist:
            return False, f"Ação {action_type.value} está bloqueada"

        # 2. Verificar whitelist
        if action_type not in self.action_whitelist:
            return False, f"Ação {action_type.value} não está na whitelist"

        # 3. Obter tier requerido
        required_tier = self.custom_tiers.get(
            action_type, self.default_tiers.get(action_type, AutonomyTier.L0_MANUAL)
        )

        # 4. Goals trusted podem fazer ações L0 com L1 (check antes de tier)
        if (required_tier == AutonomyTier.L0_MANUAL and
            goal_name in self.trusted_goals and
            current_tier == AutonomyTier.L1_LOGGED):
            return True, "Ação permitida (goal em whitelist de confiança)"

        # 5. Verificar tier atual vs requerido
        if current_tier.value < required_tier.value:
            return False, (
                f"Ação {action_type.value} requer {required_tier.name} "
                f"mas goal tem {current_tier.name}"
            )

        return True, f"Ação {action_type.value} permitida com {current_tier.name}"

    def set_autonomy_tier(self, action_type: ActionType, tier: AutonomyTier):
        """Define tier customizado para uma ação"""
        self.custom_tiers[action_type] = tier
        log.info(f"[safety] {action_type.value} agora requer {tier.name}")

    def add_trusted_goal(self, goal_name: str):
        """Adiciona goal para whitelist de confiança (L1 pode fazer L0)"""
        self.trusted_goals.add(goal_name)
        log.info(f"[safety] Goal '{goal_name}' adicionado à whitelist de confiança")

    def block_action(self, action_type: ActionType):
        """Bloqueia ação explicitamente (blacklist)"""
        self.action_blacklist.add(action_type)
        self.action_whitelist.discard(action_type)
        log.warning(f"[safety] {action_type.value} foi BLOQUEADO")

    def unblock_action(self, action_type: ActionType):
        """Remove ação de blacklist"""
        self.action_blacklist.discard(action_type)
        self.action_whitelist.add(action_type)
        log.info(f"[safety] {action_type.value} foi DESBLOQUEADO")

    def get_policy_report(self) -> dict:
        """Retorna relatório de política de segurança"""
        return {
            "whitelist": [a.value for a in self.action_whitelist],
            "blacklist": [a.value for a in self.action_blacklist],
            "trusted_goals": list(self.trusted_goals),
            "tier_customizations": {
                a.value: t.name for a, t in self.custom_tiers.items()
            },
        }


class SafetyLayer:
    """
    Camada de segurança que valida e registra todas as ações.
    Integrado no pipeline para verificação de permissões.
    """

    def __init__(self, policy: Optional[SafetyPolicy] = None):
        self.policy = policy or SafetyPolicy()
        self.audit_log: list[dict] = []

    async def check_action(
        self,
        action_type: ActionType,
        goal_name: str,
        current_tier: AutonomyTier,
        action_details: Optional[dict] = None,
    ) -> tuple[bool, str]:
        """
        Verifica se ação é permitida e registra auditoria.

        Args:
            action_type: Tipo de ação
            goal_name: Goal que quer executar a ação
            current_tier: Tier de autonomia atual
            action_details: Detalhes adicionais (arquivo, API, etc.)

        Returns: (allowed, reason)
        """
        allowed, reason = self.policy.allow_action(action_type, goal_name, current_tier)

        # Registrar em auditoria
        audit_entry = {
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            "goal": goal_name,
            "action": action_type.value,
            "tier": current_tier.name,
            "allowed": allowed,
            "reason": reason,
            "details": action_details or {},
        }
        self.audit_log.append(audit_entry)

        # Log se bloqueado
        if not allowed:
            log.warning(
                f"[safety] BLOQUEADO: {goal_name} tentou {action_type.value} "
                f"(tem {current_tier.name}): {reason}"
            )

        return allowed, reason

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """Retorna últimas N entradas do audit log"""
        return self.audit_log[-limit:]

    def export_policy(self) -> dict:
        """Exporta configuração atual de segurança"""
        return {
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            "policy": self.policy.get_policy_report(),
            "audit_entries": len(self.audit_log),
        }
