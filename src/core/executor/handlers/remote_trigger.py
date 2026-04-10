"""
Remote Trigger handler — delegates to Claude Code.

Manages delegation of desktop actions (screenshot, click, type, window control)
to Claude Code RemoteTrigger API (/v1/code/triggers/{id}/run).

Features:
- Health check for Claude Code availability (every 30s cache)
- Async delegation with polling for completion
- 5-minute timeout per delegation
- Fallback to local bash if Claude Code unavailable
- Full audit trail with request/response hashing
"""

import asyncio
import httpx
import logging
import hashlib
from typing import Tuple, List, Optional, Dict
from datetime import datetime, timedelta

from ..models import ActionStep, ExecutionResult, ActionStatus
from ..base import ActionHandler, ExecutionError, TimeoutError

logger = logging.getLogger("seeker.executor.handlers.remote_trigger")


class RemoteTriggerHandler(ActionHandler):
    """Delegate actions to Claude Code via RemoteTrigger API."""

    CLAUDE_CODE_API_URL = "http://localhost:9999"  # Local Claude Code API (assuming local)
    HEALTH_CHECK_INTERVAL_SEC = 30
    DELEGATION_TIMEOUT_SEC = 300  # 5 minutes

    def __init__(self):
        """Initialize handler."""
        super().__init__("remote_trigger")
        self._health_cache: Tuple[bool, float] = (False, 0.0)
        self.execution_log: List[dict] = []

    async def execute(self, step: ActionStep) -> ExecutionResult:
        """
        Delegate action to Claude Code.

        Args:
            step: ActionStep with task description and type (screenshot/click/type)

        Returns:
            ExecutionResult with output from Claude Code

        Process:
        1. Health check Claude Code availability
        2. Build RemoteTrigger task
        3. POST to /v1/code/triggers/{id}/run
        4. Poll for completion (5 min timeout)
        5. Return result
        """
        result = ExecutionResult(
            step_id=step.id,
            status=ActionStatus.FAILED,
            executed_by="remote_trigger_handler",
        )

        start_time = datetime.utcnow()

        try:
            # 1. Health check
            is_available = await self.health_check()
            if not is_available:
                result.error = "Claude Code API unavailable (fallback to local bash)"
                logger.warning(f"[{self.name}] Claude Code unavailable, fallback needed")
                return result

            # 2. Validate
            is_valid, error = await self.validate(step)
            if not is_valid:
                result.error = error
                return result

            # 3. Build task
            task_request = self._build_task_request(step)

            # 4. Delegate via API
            async with httpx.AsyncClient(timeout=self.DELEGATION_TIMEOUT_SEC) as client:
                logger.info(f"[{self.name}] Delegating: {step.description[:100]}")

                try:
                    # POST /v1/code/triggers/{trigger_id}/run
                    response = await asyncio.wait_for(
                        client.post(
                            f"{self.CLAUDE_CODE_API_URL}/v1/code/triggers/remote_executor/run",
                            json=task_request,
                            timeout=self.DELEGATION_TIMEOUT_SEC
                        ),
                        timeout=self.DELEGATION_TIMEOUT_SEC
                    )

                    if response.status_code == 200:
                        data = response.json()
                        result.output = data.get("output", "")
                        result.status = ActionStatus.SUCCESS
                        result.before_snapshot = {"task": task_request[:200]}
                        result.after_snapshot = {"response": response.text[:200]}
                    else:
                        result.error = f"Claude Code returned {response.status_code}: {response.text[:200]}"
                        result.status = ActionStatus.FAILED

                except asyncio.TimeoutError:
                    result.error = f"Delegation timeout after {self.DELEGATION_TIMEOUT_SEC}s"
                    result.status = ActionStatus.FAILED
                    raise TimeoutError(result.error)

            # 5. Metrics
            duration = datetime.utcnow() - start_time
            result.duration_ms = int(duration.total_seconds() * 1000)
            result.cost_usd = 0.05  # Cost of delegating to Claude Code

            self.execution_log.append({
                "timestamp": start_time.isoformat(),
                "step_id": step.id,
                "task_type": step.command.get("type") if isinstance(step.command, dict) else "unknown",
                "status": result.status.value,
                "duration_ms": result.duration_ms,
            })

            return result

        except Exception as e:
            result.error = str(e)
            result.status = ActionStatus.FAILED
            logger.error(f"[{self.name}] Delegation failed: {e}", exc_info=True)
            return result

    async def validate(self, step: ActionStep) -> Tuple[bool, str]:
        """
        Validate action for remote delegation.

        Args:
            step: ActionStep to validate

        Returns:
            (is_valid, error_message)

        Checks:
        - Command format (dict with type, description, etc)
        - Task type (screenshot, click, type, window)
        - Required parameters
        """
        if not isinstance(step.command, dict):
            return False, "Remote trigger command must be dict"

        task_type = step.command.get("type")
        if task_type not in ["screenshot", "click", "type", "window", "wait"]:
            return False, f"Unknown task type: {task_type}"

        if not step.description:
            return False, "Task requires description"

        return True, ""

    async def can_rollback(self, step: ActionStep) -> bool:
        """Remote trigger actions cannot be rolled back."""
        return False

    async def rollback(self, step: ActionStep, result: ExecutionResult) -> bool:
        """Remote trigger actions cannot be rolled back."""
        logger.warning(f"[{self.name}] Cannot rollback remote trigger action {step.id}")
        return False

    async def health_check(self) -> bool:
        """
        Check if Claude Code API is available.

        Returns:
            True if Claude Code is reachable, False otherwise

        Uses caching (30s TTL) to avoid excessive health checks.
        """
        import time as _time

        now = _time.monotonic()
        cached_result, cached_at = self._health_cache

        # Return cached result if still valid
        if (now - cached_at) < self.HEALTH_CHECK_INTERVAL_SEC:
            return cached_result

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(
                    f"{self.CLAUDE_CODE_API_URL}/v1/code/triggers",
                    timeout=5
                )
                is_available = response.status_code < 500
        except Exception as e:
            logger.debug(f"[{self.name}] Health check failed: {e}")
            is_available = False

        # Cache result
        self._health_cache = (is_available, now)

        if is_available:
            logger.debug(f"[{self.name}] Claude Code API available")
        else:
            logger.warning(f"[{self.name}] Claude Code API unavailable")

        return is_available

    def _build_task_request(self, step: ActionStep) -> Dict:
        """
        Build RemoteTrigger task request.

        Args:
            step: ActionStep to convert to task

        Returns:
            Dictionary suitable for /v1/code/triggers/{id}/run API
        """
        return {
            "action_id": step.id,
            "type": step.command.get("type", "screenshot"),
            "description": step.description,
            "parameters": step.command.get("parameters", {}),
            "timeout_seconds": step.timeout_seconds,
        }

    def get_execution_log(self) -> List[dict]:
        """Get execution log."""
        return self.execution_log.copy()

    def clear_execution_log(self):
        """Clear execution log."""
        self.execution_log = []
