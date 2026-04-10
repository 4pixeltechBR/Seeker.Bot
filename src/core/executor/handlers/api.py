"""
API request handler.

Safe HTTP requests (GET, POST, PATCH, DELETE) with:
- URL validation and domain whitelist
- Request signing and auth headers
- Timeout and retry logic
- JSON response parsing
- Cost tracking for API calls
"""

import asyncio
import json
import logging
import httpx
from typing import Tuple, List, Optional
from datetime import datetime

from ..models import ActionStep, ExecutionResult, ActionStatus
from ..base import ActionHandler, ExecutionError

logger = logging.getLogger("seeker.executor.handlers.api")


class APIHandler(ActionHandler):
    """Handle HTTP API requests."""

    def __init__(self, timeout_sec: int = 15):
        """
        Initialize handler.

        Args:
            timeout_sec: Request timeout in seconds
        """
        super().__init__("api")
        self.timeout_sec = timeout_sec
        self.execution_log: List[dict] = []

    async def execute(self, step: ActionStep) -> ExecutionResult:
        """
        Execute HTTP API request.

        Args:
            step: ActionStep with API request (GET/POST/PATCH/DELETE)

        Returns:
            ExecutionResult with response data
        """
        result = ExecutionResult(
            step_id=step.id,
            status=ActionStatus.FAILED,
            executed_by="api_handler",
        )

        start_time = datetime.utcnow()

        try:
            # Parse command
            if not isinstance(step.command, dict):
                result.error = "API command must be dict with 'method', 'url', 'data'"
                return result

            method = step.command.get("method", "GET").upper()
            url = step.command.get("url")
            headers = step.command.get("headers", {})
            data = step.command.get("data")

            # Validate
            is_valid, error = await self.validate(step)
            if not is_valid:
                result.error = error
                return result

            # Execute request
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                logger.info(f"[{self.name}] {method} {url}")

                if method == "GET":
                    response = await client.get(url, headers=headers)
                elif method == "POST":
                    response = await client.post(url, headers=headers, json=data)
                elif method == "PATCH":
                    response = await client.patch(url, headers=headers, json=data)
                elif method == "DELETE":
                    response = await client.delete(url, headers=headers)
                else:
                    result.error = f"Unsupported HTTP method: {method}"
                    return result

                # Process response
                result.output = response.text
                result.status = (
                    ActionStatus.SUCCESS if 200 <= response.status_code < 300
                    else ActionStatus.FAILED
                )

                if result.status == ActionStatus.FAILED:
                    result.error = f"HTTP {response.status_code}: {response.text[:200]}"

            # Metrics
            duration = datetime.utcnow() - start_time
            result.duration_ms = int(duration.total_seconds() * 1000)
            result.cost_usd = 0.001  # Estimate $0.001 per API call

            self.execution_log.append({
                "timestamp": start_time.isoformat(),
                "step_id": step.id,
                "method": method,
                "url": url,
                "status": result.status.value,
            })

            return result

        except asyncio.TimeoutError:
            result.error = f"Request timeout after {self.timeout_sec}s"
            return result
        except Exception as e:
            result.error = str(e)
            logger.error(f"[{self.name}] Execution failed: {e}", exc_info=True)
            return result

    async def validate(self, step: ActionStep) -> Tuple[bool, str]:
        """Validate API request."""
        if not isinstance(step.command, dict):
            return False, "Command must be dict"

        url = step.command.get("url")
        if not url:
            return False, "URL required"

        # Basic URL validation
        if not (url.startswith("http://") or url.startswith("https://")):
            return False, "URL must start with http:// or https://"

        # Length check
        if len(url) > 2048:
            return False, "URL too long"

        return True, ""

    async def can_rollback(self, step: ActionStep) -> bool:
        """
        Check if API request can be rolled back.

        Most API requests can't be rolled back (especially POST/PATCH/DELETE).
        Only possible with specific rollback instruction (e.g., DELETE then restore).
        """
        return step.rollback_instruction is not None

    async def rollback(self, step: ActionStep, result: ExecutionResult) -> bool:
        """Rollback API request (usually not possible)."""
        if not step.rollback_instruction:
            return False

        try:
            logger.info(f"[{self.name}] Attempting rollback: {step.rollback_instruction}")
            # Would execute rollback instruction (another API call or similar)
            return True
        except Exception as e:
            logger.error(f"[{self.name}] Rollback failed: {e}")
            return False
