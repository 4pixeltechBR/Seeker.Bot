"""
Safety gate evaluation for Remote Executor.

SafetyGateEvaluator:
    Evaluates ExecutionPlan against ExecutorPolicy.
    Determines approval tier (L0/L1/L2) for each action.
    Enforces budget caps and AFK window constraints.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

from .models import (
    ExecutionPlan,
    ActionStep,
    SafetyGate,
    AutonomyTier,
    ExecutionContext,
)
from .base import ExecutorPolicy, SafetyViolation

logger = logging.getLogger("seeker.executor.safety")


class SafetyGateEvaluator:
    """
    Evaluates plan against safety policy.

    Determines:
    - Whether each action passes safety gates
    - Approval tier (L0/L1/L2) for each step
    - Whether plan violates budget or time constraints
    """

    def __init__(self, policy: Optional[ExecutorPolicy] = None):
        """
        Initialize evaluator.

        Args:
            policy: ExecutorPolicy (uses defaults if None)
        """
        self.policy = policy or ExecutorPolicy()
        self.audit_log: List[dict] = []

    async def evaluate_plan(
        self, plan: ExecutionPlan, context: ExecutionContext
    ) -> Tuple[bool, List[str]]:
        """
        Evaluate entire execution plan.

        Args:
            plan: ExecutionPlan to evaluate
            context: ExecutionContext (user, budget, AFK time)

        Returns:
            (is_safe, list_of_violations)

        Raises:
            SafetyViolation: If plan violates critical constraints
        """
        violations = []

        # Check plan-level constraints
        if len(plan.steps) > plan.max_steps:
            violations.append(
                f"Plan exceeds max steps ({len(plan.steps)} > {plan.max_steps})"
            )

        if plan.estimated_total_cost_usd > plan.max_cost_usd:
            violations.append(
                f"Plan exceeds max cost (${plan.estimated_total_cost_usd:.2f} > ${plan.max_cost_usd:.2f})"
            )

        # Check budget
        if plan.estimated_total_cost_usd > context.budget_remaining_usd:
            violations.append(
                f"Insufficient budget (${plan.estimated_total_cost_usd:.2f} > ${context.budget_remaining_usd:.2f})"
            )

        # Evaluate each step
        for step in plan.steps:
            step_safe, step_violations = await self.evaluate_step(step, context)
            if not step_safe:
                violations.extend(step_violations)

        is_safe = len(violations) == 0
        self.audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "plan_id": plan.plan_id,
            "is_safe": is_safe,
            "violations": violations,
            "afk_time": context.afk_time_seconds,
        })

        return is_safe, violations

    async def evaluate_step(
        self, step: ActionStep, context: ExecutionContext
    ) -> Tuple[bool, List[str]]:
        """
        Evaluate single action step.

        Args:
            step: ActionStep to evaluate
            context: ExecutionContext

        Returns:
            (is_safe, list_of_violations)

        Evaluates:
        - Bash command whitelist
        - API endpoint safety
        - AFK window constraints
        - Cost limits
        """
        violations = []

        # Type-specific evaluation
        if step.type.value == "bash":
            bash_safe, bash_violations = self._evaluate_bash(step)
            violations.extend(bash_violations)

        # AFK window check for L1_LOGGED
        if step.approval_tier == AutonomyTier.L1_LOGGED:
            afk_hours = context.afk_time_seconds / 3600
            if afk_hours > context.afk_window_l1_hours:
                violations.append(
                    f"AFK window exceeded for L1 action ({afk_hours:.1f}h > {context.afk_window_l1_hours}h)"
                )
                # Escalate to L0_MANUAL if AFK too long
                step.approval_tier = AutonomyTier.L0_MANUAL

        # Cost limit check
        if step.estimated_cost_usd > self.policy.budget_per_action_max:
            violations.append(
                f"Action exceeds budget limit (${step.estimated_cost_usd:.4f} > ${self.policy.budget_per_action_max:.2f})"
            )

        # Timeout check
        if step.timeout_seconds > self.policy.max_timeout_seconds:
            violations.append(
                f"Action timeout exceeds max ({step.timeout_seconds}s > {self.policy.max_timeout_seconds}s)"
            )

        is_safe = len(violations) == 0
        return is_safe, violations

    def _evaluate_bash(self, step: ActionStep) -> Tuple[bool, List[str]]:
        """
        Evaluate bash command safety.

        Returns:
            (is_safe, list_of_violations)

        Checks whitelist/blacklist and sets approval tier accordingly.
        """
        violations = []

        if not isinstance(step.command, str):
            violations.append("Bash command must be string")
            return False, violations

        cmd = step.command.strip()

        # Check blacklist (L0_MANUAL commands)
        for blacklisted in self.policy.bash_blacklist_l0_manual:
            if blacklisted in cmd:
                if step.approval_tier != AutonomyTier.L0_MANUAL:
                    step.approval_tier = AutonomyTier.L0_MANUAL
                violations.append(
                    f"Bash command contains dangerous operation: {blacklisted}"
                )

        # Check whitelist for L2_SILENT
        is_whitelisted_l2 = any(
            cmd.startswith(allowed) for allowed in self.policy.bash_whitelist_l2_silent
        )
        is_whitelisted_l1 = any(
            cmd.startswith(allowed) for allowed in self.policy.bash_whitelist_l1_logged
        )

        if not (is_whitelisted_l2 or is_whitelisted_l1) and step.approval_tier == AutonomyTier.L2_SILENT:
            step.approval_tier = AutonomyTier.L1_LOGGED
            violations.append("Command not in L2 whitelist, downgrading to L1_LOGGED")

        return len(violations) == 0, violations

    def get_audit_log(self) -> List[dict]:
        """Get evaluation audit log."""
        return self.audit_log.copy()

    def clear_audit_log(self):
        """Clear audit log."""
        self.audit_log = []
