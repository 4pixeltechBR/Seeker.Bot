"""
Bash command executor handler.

Safe execution of bash commands with:
- Command whitelist/blacklist validation
- Subprocess execution with timeout
- Before/after snapshots for audit trail
- Error handling and rollback support
- Logging and cost tracking
"""

import asyncio
import subprocess
import logging
from typing import Tuple, Optional, List
from datetime import datetime

from ..models import ActionStep, ExecutionResult, ActionStatus, ActionType, AutonomyTier
from ..base import ActionHandler, ExecutorPolicy, SafetyViolation, ExecutionError, TimeoutError

logger = logging.getLogger("seeker.executor.handlers.bash")


class BashHandler(ActionHandler):
    """Execute bash commands safely."""

    def __init__(self, policy: Optional[ExecutorPolicy] = None):
        """
        Initialize handler.

        Args:
            policy: ExecutorPolicy for whitelist/blacklist validation
        """
        super().__init__("bash")
        self.policy = policy or ExecutorPolicy()
        self.execution_log: List[dict] = []

    async def execute(self, step: ActionStep) -> ExecutionResult:
        """
        Execute bash command safely.

        Args:
            step: ActionStep with bash command

        Returns:
            ExecutionResult with output, cost, duration

        Process:
        1. Validate command
        2. Capture before snapshot
        3. Execute with timeout
        4. Capture after snapshot
        5. Log execution
        """
        result = ExecutionResult(
            step_id=step.id,
            status=ActionStatus.FAILED,  # Default to failed
            executed_by="bash_handler",
        )

        start_time = datetime.utcnow()

        try:
            # 1. Validate
            is_valid, error = await self.validate(step)
            if not is_valid:
                result.error = f"Validation failed: {error}"
                result.status = ActionStatus.FAILED
                return result

            # 2. Before snapshot
            try:
                cwd_result = await asyncio.wait_for(
                    self._run_subprocess("pwd"),
                    timeout=5
                )
                cwd = cwd_result["stdout"].strip()
            except:
                cwd = "unknown"

            result.before_snapshot = {
                "cwd": cwd,
                "timestamp": start_time.isoformat(),
            }

            # 3. Execute with timeout
            logger.info(f"[{self.name}] Executing: {step.command[:100]}")

            try:
                proc_result = await asyncio.wait_for(
                    self._run_subprocess(step.command),
                    timeout=step.timeout_seconds
                )

                result.output = proc_result["stdout"]
                result.error = proc_result.get("stderr", "")
                result.status = (
                    ActionStatus.SUCCESS if proc_result["returncode"] == 0
                    else ActionStatus.FAILED
                )

            except asyncio.TimeoutError:
                result.error = f"Command timeout after {step.timeout_seconds}s"
                result.status = ActionStatus.FAILED
                raise TimeoutError(result.error)

            # 4. After snapshot
            try:
                cwd_result = await asyncio.wait_for(
                    self._run_subprocess("pwd"),
                    timeout=5
                )
                cwd = cwd_result["stdout"].strip()
            except:
                cwd = "unknown"

            result.after_snapshot = {
                "cwd": cwd,
                "timestamp": datetime.utcnow().isoformat(),
            }

            # 5. Calculate metrics
            duration = datetime.utcnow() - start_time
            result.duration_ms = int(duration.total_seconds() * 1000)
            result.cost_usd = 0.0  # Bash execution is free

            # Log execution
            self.execution_log.append({
                "timestamp": start_time.isoformat(),
                "step_id": step.id,
                "command": step.command[:200],
                "status": result.status.value,
                "duration_ms": result.duration_ms,
                "output_length": len(result.output),
            })

            logger.info(
                f"[{self.name}] Execution complete: {result.status.value} ({result.duration_ms}ms)"
            )

            return result

        except Exception as e:
            result.error = str(e)
            result.status = ActionStatus.FAILED
            logger.error(f"[{self.name}] Execution failed: {e}", exc_info=True)
            return result

    async def validate(self, step: ActionStep) -> Tuple[bool, str]:
        """
        Validate bash command against whitelist/blacklist.

        Args:
            step: ActionStep to validate

        Returns:
            (is_valid, error_message)

        Validation rules:
        - Command must be string
        - Command must not be empty
        - Command must not contain shell injection patterns
        """
        # Type check
        if not isinstance(step.command, str):
            return False, "Bash command must be string"

        cmd = step.command.strip()

        # Empty check
        if not cmd:
            return False, "Bash command cannot be empty"

        # Blacklist check
        for blacklisted in self.policy.bash_blacklist_l0_manual:
            if blacklisted in cmd:
                if step.approval_tier != AutonomyTier.L0_MANUAL:
                    return False, f"Command uses blacklisted operation: {blacklisted}"

        return True, ""

    async def can_rollback(self, step: ActionStep) -> bool:
        """
        Check if bash command can be rolled back.

        Args:
            step: ActionStep with rollback_instruction

        Returns:
            True if rollback is possible

        Bash commands can be rolled back if rollback_instruction is provided.
        """
        return step.rollback_instruction is not None

    async def rollback(self, step: ActionStep, result: ExecutionResult) -> bool:
        """
        Rollback bash command execution.

        Args:
            step: ActionStep with rollback_instruction
            result: ExecutionResult from original execution

        Returns:
            True if rollback successful
        """
        if not step.rollback_instruction:
            logger.warning(f"[{self.name}] No rollback instruction for {step.id}")
            return False

        try:
            logger.info(f"[{self.name}] Attempting rollback: {step.rollback_instruction}")

            rollback_result = await asyncio.wait_for(
                self._run_subprocess(step.rollback_instruction),
                timeout=step.timeout_seconds
            )

            success = rollback_result["returncode"] == 0

            self.execution_log.append({
                "timestamp": datetime.utcnow().isoformat(),
                "action": "rollback",
                "step_id": step.id,
                "instruction": step.rollback_instruction[:200],
                "success": success,
            })

            if success:
                logger.info(f"[{self.name}] Rollback successful for {step.id}")
            else:
                logger.error(f"[{self.name}] Rollback failed: {rollback_result.get('stderr', '')}")

            return success

        except Exception as e:
            logger.error(f"[{self.name}] Rollback exception: {e}", exc_info=True)
            return False

    async def _run_subprocess(self, command: str) -> dict:
        """
        Run subprocess and capture output.

        Args:
            command: Bash command to run

        Returns:
            {"returncode": int, "stdout": str, "stderr": str}
        """
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=None
            )

            stdout, stderr = await proc.communicate()

            return {
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            }

        except Exception as e:
            logger.error(f"[{self.name}] Subprocess error: {e}")
            raise ExecutionError(f"Failed to execute bash command: {e}")

    def get_execution_log(self) -> List[dict]:
        """Get bash execution log."""
        return self.execution_log.copy()

    def clear_execution_log(self):
        """Clear execution log."""
        self.execution_log = []
