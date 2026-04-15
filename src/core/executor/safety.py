"""SafetyGate — Approval & Policy Enforcement (Track B3)"""
import logging
from src.core.executor.models import ActionStep, ApprovalTier, SafetyGateDecision

log = logging.getLogger("executor.safety")

class SafetyGate:
    """Avalia e aprova/bloqueia ações baseado em policy"""

    # Bash commands whitelist por tier
    BASH_WHITELIST = {
        "L2_SILENT": ["ls", "cat", "grep", "find", "head", "tail", "wc", "git status", "pwd"],
        "L1_LOGGED": ["mkdir", "touch", "cp", "mv", "git add", "git diff", "git fetch"],
        "L0_MANUAL": ["rm", "rmdir", "chmod", "chown", "dd", "git rm", "git reset"],
    }

    # Budget limits
    MAX_COST_PER_ACTION = 0.20
    MAX_COST_PER_CYCLE = 0.20
    MAX_COST_PER_DAY = 1.00

    # AFK window enforcement (hours)
    AFK_WINDOWS = {
        ApprovalTier.L2_SILENT: 24,      # 24h for silent actions
        ApprovalTier.L1_LOGGED: 6,       # 6h for logged, then escalate
        ApprovalTier.L0_MANUAL: 0.083,   # 5 min for manual, then pause
    }

    def __init__(self):
        self.cycle_cost = 0.0
        self.day_cost = 0.0

    async def evaluate(self, step: ActionStep, user_afk_hours: float = 0.0) -> SafetyGateDecision:
        """
        Avalia se ação deve ser executada, bloqueada, ou pedir aprovação.

        Args:
            step: ActionStep a avaliar
            user_afk_hours: Quanto tempo user está offline

        Returns:
            SafetyGateDecision com aprovado/bloqueado + razão
        """
        # 1. Budget check
        if step.estimated_cost_usd > self.MAX_COST_PER_ACTION:
            return SafetyGateDecision(
                action_id=step.id,
                approved=False,
                approval_tier=ApprovalTier.L0_MANUAL,
                reason=f"Custo {step.estimated_cost_usd:.2f} excede máximo {self.MAX_COST_PER_ACTION}"
            )

        if (self.cycle_cost + step.estimated_cost_usd) > self.MAX_COST_PER_CYCLE:
            return SafetyGateDecision(
                action_id=step.id,
                approved=False,
                approval_tier=ApprovalTier.L0_MANUAL,
                reason=f"Custo de ciclo excedido (${self.cycle_cost:.2f} + ${step.estimated_cost_usd:.2f})"
            )

        # 2. Bash whitelist check
        if step.type.value == "bash":
            if not self._is_bash_whitelisted(step.command, step.approval_tier):
                return SafetyGateDecision(
                    action_id=step.id,
                    approved=False,
                    approval_tier=ApprovalTier.L0_MANUAL,
                    reason=f"Comando bash bloqueado por whitelist: {step.command}"
                )

        # 3. AFK window enforcement
        max_afk_hours = self.AFK_WINDOWS.get(step.approval_tier, 0.0)
        if user_afk_hours > max_afk_hours:
            return SafetyGateDecision(
                action_id=step.id,
                approved=False,
                approval_tier=ApprovalTier.L0_MANUAL,
                reason=f"User AFK {user_afk_hours:.1f}h > máximo {max_afk_hours}h para {step.approval_tier.value}"
            )

        # 4. Aprovado!
        self.cycle_cost += step.estimated_cost_usd
        return SafetyGateDecision(
            action_id=step.id,
            approved=True,
            approval_tier=step.approval_tier,
            reason=f"Aprovado por policy ({step.approval_tier.value})"
        )

    def _is_bash_whitelisted(self, command: str, tier: ApprovalTier) -> bool:
        """Verifica se comando está na whitelist"""
        cmd_tokens = command.split()
        if not cmd_tokens:
            return False

        main_cmd = cmd_tokens[0]

        # L2_SILENT permite tudo de L2
        if tier == ApprovalTier.L2_SILENT:
            return main_cmd in self.BASH_WHITELIST.get("L2_SILENT", [])

        # L1_LOGGED permite L2+L1
        if tier == ApprovalTier.L1_LOGGED:
            allowed = self.BASH_WHITELIST.get("L2_SILENT", []) + self.BASH_WHITELIST.get("L1_LOGGED", [])
            return main_cmd in allowed

        # L0_MANUAL permite tudo
        if tier == ApprovalTier.L0_MANUAL:
            all_allowed = []
            for tier_list in self.BASH_WHITELIST.values():
                all_allowed.extend(tier_list)
            return main_cmd in all_allowed

        return False

    def reset_cycle(self):
        """Reseta custo de ciclo (execução completada)"""
        self.cycle_cost = 0.0

    def reset_day(self):
        """Reseta custo de dia (midnight)"""
        self.day_cost = 0.0


# Aliases para compatibilidade com outras partes do código
SafetyGateEvaluator = SafetyGate


class ExecutorPolicy:
    """Policy executor para definir regras de execução"""

    def __init__(self):
        self.bash_whitelist = SafetyGate.BASH_WHITELIST
        self.max_cost_per_action = SafetyGate.MAX_COST_PER_ACTION
        self.max_cost_per_cycle = SafetyGate.MAX_COST_PER_CYCLE
        self.max_cost_per_day = SafetyGate.MAX_COST_PER_DAY
        self.afk_windows = SafetyGate.AFK_WINDOWS
