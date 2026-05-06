"""
Base classes and protocols for Remote Executor.

ActionHandler:
    Protocol for pluggable action execution handlers.
    Implementations: BashHandler, FileOpsHandler, APIHandler, RemoteTriggerHandler
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from .models import ActionStep, ExecutionResult, ActionStatus

logger = logging.getLogger("seeker.executor.base")


class ActionHandler(ABC):
    """
    Abstract base class for action handlers.

    Each handler implements async execute() to run a specific action type.
    Handlers are responsible for:
    - Validating inputs (whitelist, safety gates)
    - Executing the action with timeout
    - Capturing before/after snapshots
    - Handling errors and rollback
    - Tracking cost and duration
    """

    def __init__(self, name: str):
        """Initialize handler."""
        self.name = name
        self.logger = logging.getLogger(f"seeker.executor.handlers.{name}")

    @abstractmethod
    async def execute(self, step: ActionStep) -> ExecutionResult:
        """
        Execute a single action step.

        Args:
            step: ActionStep to execute

        Returns:
            ExecutionResult with outcome

        Must:
        - Respect step.timeout_seconds
        - Populate before/after snapshots if applicable
        - Calculate cost_usd
        - Handle errors gracefully
        - Return status in result
        """
        pass

    @abstractmethod
    async def validate(self, step: ActionStep) -> tuple[bool, str]:
        """
        Validate action step before execution.

        Args:
            step: ActionStep to validate

        Returns:
            (is_valid, error_message)

        Should check:
        - Command whitelist
        - Parameter safety
        - Resource availability
        """
        pass

    @abstractmethod
    async def can_rollback(self, step: ActionStep) -> bool:
        """
        Check if this action can be rolled back.

        Args:
            step: ActionStep with rollback_instruction

        Returns:
            True if rollback is possible

        Some actions are reversible (mkdir → rmdir),
        others are not (file delete).
        """
        pass

    @abstractmethod
    async def rollback(self, step: ActionStep, result: ExecutionResult) -> bool:
        """
        Attempt to roll back this action.

        Args:
            step: ActionStep with rollback_instruction
            result: ExecutionResult of original execution

        Returns:
            True if rollback successful

        Called if action fails and step.rollback_instruction is set.
        """
        pass

    async def health_check(self) -> bool:
        """
        Check if handler is ready to execute.

        Override for handlers with external dependencies.
        E.g., RemoteTriggerHandler checks Claude Code availability.
        """
        return True


class ExecutorPolicy:
    """
    Configurable safety and execution policy.

    Defines:
    - Action approval tiers (L0/L1/L2)
    - AFK window thresholds
    - Budget limits
    - Command whitelists/blacklists
    """

    def __init__(self):
        self.afk_window_l1_hours = 12  # L1_LOGGED executes up to 12h AFK
        self.afk_window_l0_timeout_sec = 300  # L0 waits 5 min for approval
        self.afk_window_l0_max_retries = 3  # 3 retry attempts (5/35/65 min)

        self.budget_per_action_max = 0.20
        self.budget_per_cycle_max = 0.20
        self.budget_per_day_max = 1.00

        # Bash whitelist (action type → commands)
        self.bash_whitelist_l2_silent = [
            "ls", "cat", "grep", "find", "head", "tail", "wc",
            "git status", "git log", "git diff", "npm list"
        ]
        self.bash_whitelist_l1_logged = [
            "mkdir", "touch", "cp", "mv", "echo", "git add", "git commit"
        ]
        self.bash_blacklist_l0_manual = [
            "rm", "rmdir", "del", "chmod", "chown", "dd", "format",
            "git reset --hard", "git push --force"
        ]


class SafetyViolation(Exception):
    """Raised when action violates safety policy."""
    pass


class ExecutionError(Exception):
    """Raised when action execution fails."""
    pass


class ApprovalRequired(Exception):
    """Raised when L0_MANUAL action needs user approval."""
    pass


class TimeoutError(ExecutionError):
    """Raised when action exceeds timeout."""
    pass
