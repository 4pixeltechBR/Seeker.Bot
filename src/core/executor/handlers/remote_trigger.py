"""Remote Trigger handler - delegates to Claude Code."""

import logging
from typing import Tuple
from ..models import ActionStep, ExecutionResult, ActionStatus
from ..base import ActionHandler

logger = logging.getLogger("seeker.executor.handlers.remote_trigger")

class RemoteTriggerHandler(ActionHandler):
    def __init__(self):
        super().__init__("remote_trigger")

    async def execute(self, step: ActionStep) -> ExecutionResult:
        result = ExecutionResult(step_id=step.id, status=ActionStatus.PENDING)
        logger.info(f"[{self.name}] execute() stub - Phase B2")
        return result

    async def validate(self, step: ActionStep) -> Tuple[bool, str]:
        logger.info(f"[{self.name}] validate() stub - Phase B2")
        return True, ""

    async def can_rollback(self, step: ActionStep) -> bool:
        return False  # Can't rollback remote trigger actions

    async def rollback(self, step: ActionStep, result: ExecutionResult) -> bool:
        logger.info(f"[{self.name}] rollback() stub - Phase B2")
        return False

    async def health_check(self) -> bool:
        """Check if Claude Code API is available."""
        # TODO: Phase B2 - check /v1/code/triggers availability
        logger.info(f"[{self.name}] health_check() stub - Phase B2")
        return True
