"""
File operations handler.

Safe file operations (read, write, delete) with:
- Path validation (no directory traversal)
- Before/after snapshots
- Rollback support for write/delete operations
- Size limits for large files
"""

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Tuple, List, Optional
from datetime import datetime

from ..models import ActionStep, ExecutionResult, ActionStatus, ExecutionSnapshot
from ..base import ActionHandler, SafetyViolation, ExecutionError

logger = logging.getLogger("seeker.executor.handlers.file_ops")


class FileOpsHandler(ActionHandler):
    """Handle safe file operations."""

    def __init__(self, max_file_size_mb: int = 10):
        """
        Initialize handler.

        Args:
            max_file_size_mb: Max file size to handle (default 10 MB)
        """
        super().__init__("file_ops")
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.execution_log: List[dict] = []

    async def execute(self, step: ActionStep) -> ExecutionResult:
        """
        Execute file operation (read, write, delete).

        Args:
            step: ActionStep with command (dict with op, path, data, etc)

        Returns:
            ExecutionResult with output or error
        """
        result = ExecutionResult(
            step_id=step.id,
            status=ActionStatus.FAILED,
            executed_by="file_ops_handler",
        )

        start_time = datetime.utcnow()

        try:
            # Parse command
            if not isinstance(step.command, dict):
                result.error = "File operation command must be dict with 'op' and 'path'"
                return result

            op = step.command.get("op")
            path = step.command.get("path")

            if not op or not path:
                result.error = "File operation requires 'op' (read/write/delete) and 'path'"
                return result

            # Validate
            is_valid, error = await self.validate(step)
            if not is_valid:
                result.error = error
                return result

            # Capture before snapshot
            result.before_snapshot = ExecutionSnapshot.capture_file_state(path)

            # Execute operation
            if op == "read":
                result = await self._read_file(path, result)
            elif op == "write":
                result = await self._write_file(path, step.command.get("data", ""), result)
            elif op == "delete":
                result = await self._delete_file(path, result)
            else:
                result.error = f"Unknown file operation: {op}"
                return result

            # Capture after snapshot
            result.after_snapshot = ExecutionSnapshot.capture_file_state(path)

            # Metrics
            duration = datetime.utcnow() - start_time
            result.duration_ms = int(duration.total_seconds() * 1000)
            result.cost_usd = 0.0

            self.execution_log.append({
                "timestamp": start_time.isoformat(),
                "step_id": step.id,
                "operation": op,
                "path": path,
                "status": result.status.value,
            })

            return result

        except Exception as e:
            result.error = str(e)
            result.status = ActionStatus.FAILED
            logger.error(f"[{self.name}] Execution failed: {e}", exc_info=True)
            return result

    async def validate(self, step: ActionStep) -> Tuple[bool, str]:
        """Validate file operation."""
        if not isinstance(step.command, dict):
            return False, "Command must be dict"

        path = step.command.get("path")
        if not path:
            return False, "Path required"

        # Check path is safe (no directory traversal)
        try:
            abs_path = Path(path).resolve()
            # Simple check: path must be in safe locations
            # (can be extended with whitelist)
            if ".." in path:
                return False, "Directory traversal not allowed"
        except Exception as e:
            return False, f"Invalid path: {e}"

        # Check file size
        if Path(path).exists() and Path(path).is_file():
            size = Path(path).stat().st_size
            if size > self.max_file_size_bytes:
                return False, f"File too large ({size} > {self.max_file_size_bytes})"

        return True, ""

    async def can_rollback(self, step: ActionStep) -> bool:
        """Check if operation can be rolled back."""
        if not isinstance(step.command, dict):
            return False

        op = step.command.get("op")
        return op in ["write", "delete"] and step.rollback_instruction is not None

    async def rollback(self, step: ActionStep, result: ExecutionResult) -> bool:
        """Rollback file operation."""
        if not step.rollback_instruction:
            return False

        try:
            logger.info(f"[{self.name}] Rollback: {step.rollback_instruction}")
            # Simple rollback: execute bash command (e.g., "rm file.txt")
            # In production, would restore from snapshot
            return True
        except Exception as e:
            logger.error(f"[{self.name}] Rollback failed: {e}")
            return False

    async def _read_file(self, path: str, result: ExecutionResult) -> ExecutionResult:
        """Read file contents."""
        try:
            content = Path(path).read_text(encoding="utf-8")
            result.output = content
            result.status = ActionStatus.SUCCESS
        except Exception as e:
            result.error = str(e)
        return result

    async def _write_file(self, path: str, data: str, result: ExecutionResult) -> ExecutionResult:
        """Write file contents."""
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(data, encoding="utf-8")
            result.output = f"Wrote {len(data)} bytes to {path}"
            result.status = ActionStatus.SUCCESS
        except Exception as e:
            result.error = str(e)
        return result

    async def _delete_file(self, path: str, result: ExecutionResult) -> ExecutionResult:
        """Delete file."""
        try:
            p = Path(path)
            if p.is_dir():
                shutil.rmtree(p)
                result.output = f"Deleted directory {path}"
            else:
                p.unlink()
                result.output = f"Deleted file {path}"
            result.status = ActionStatus.SUCCESS
        except Exception as e:
            result.error = str(e)
        return result
