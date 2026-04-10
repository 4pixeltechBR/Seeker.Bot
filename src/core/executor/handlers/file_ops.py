"""File operations handler."""

import logging
from typing import Tuple
from ..models import ActionStep, ExecutionResult, ActionStatus
from ..base import ActionHandler

logger = logging.getLogger("seeker.executor.handlers.file_ops")

class FileOpsHandler(ActionHandler):
    def __init__(self):
        super().__init__("file_ops")

    async def execute(self, step: ActionStep) -> ExecutionResult:
        result = ExecutionResult(step_id=step.id, status=ActionStatus.PENDING)
        logger.info(f"[{self.name}] execute() stub - Phase B2")
        return result

    async def validate(self, step: ActionStep) -> Tuple[bool, str]:
        logger.info(f"[{self.name}] validate() stub - Phase B2")
        return True, ""

    async def can_rollback(self, step: ActionStep) -> bool:
        return step.rollback_instruction is not None

    async def rollback(self, step: ActionStep, result: ExecutionResult) -> bool:
        logger.info(f"[{self.name}] rollback() stub - Phase B2")
        return False
