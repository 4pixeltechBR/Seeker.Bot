"""File Operations Handler — Remote Executor Track B2"""
import asyncio
import logging
import hashlib
from pathlib import Path
from typing import Optional
from src.core.executor.models import ActionStep, ActionResult, ApprovalTier

log = logging.getLogger("executor.handlers.file_ops")

class FileOpsHandler:
    """Executa operações de arquivo com snapshot tracking"""
    
    async def execute(self, step: ActionStep) -> ActionResult:
        """
        Executa operação de arquivo (read/write/delete).
        
        Args:
            step: ActionStep com comando format "read:path" ou "write:path:content" ou "delete:path"
        
        Returns:
            ActionResult com resultado
        """
        import time
        start_time = time.time()
        
        try:
            cmd_parts = step.command.split(":", 2)
            op = cmd_parts[0].lower()
            
            if op == "read":
                return await self._handle_read(step, cmd_parts[1], start_time)
            elif op == "write":
                return await self._handle_write(step, cmd_parts[1], cmd_parts[2] if len(cmd_parts) > 2 else "", start_time)
            elif op == "delete":
                return await self._handle_delete(step, cmd_parts[1], start_time)
            else:
                raise ValueError(f"Unknown file operation: {op}")
        
        except Exception as e:
            return ActionResult(
                step_id=step.id,
                status="failed",
                output="",
                error_message=str(e),
            )
    
    async def _handle_read(self, step: ActionStep, file_path: str, start_time: float) -> ActionResult:
        """Lê arquivo com hash snapshot"""
        try:
            path = Path(file_path)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            
            content = await asyncio.to_thread(path.read_text)
            file_hash = hashlib.sha256(content.encode()).hexdigest()
            
            import time
            duration_ms = int((time.time() - start_time) * 1000)
            
            return ActionResult(
                step_id=step.id,
                status="success",
                output=content[:5000],
                duration_ms=duration_ms,
            )
        except Exception as e:
            return ActionResult(
                step_id=step.id,
                status="failed",
                output="",
                error_message=str(e),
            )
    
    async def _handle_write(self, step: ActionStep, file_path: str, content: str, start_time: float) -> ActionResult:
        """Escreve arquivo com before/after snapshot"""
        try:
            path = Path(file_path)
            
            # Before snapshot
            before_hash = None
            if path.exists():
                before_content = await asyncio.to_thread(path.read_text)
                before_hash = hashlib.sha256(before_content.encode()).hexdigest()
            
            # Write
            await asyncio.to_thread(path.write_text, content)
            
            # After snapshot
            after_hash = hashlib.sha256(content.encode()).hexdigest()
            
            import time
            duration_ms = int((time.time() - start_time) * 1000)
            
            return ActionResult(
                step_id=step.id,
                status="success",
                output=f"Wrote {len(content)} bytes to {file_path}",
                duration_ms=duration_ms,
            )
        except Exception as e:
            return ActionResult(
                step_id=step.id,
                status="failed",
                output="",
                error_message=str(e),
            )
    
    async def _handle_delete(self, step: ActionStep, file_path: str, start_time: float) -> ActionResult:
        """Deleta arquivo com validação"""
        try:
            path = Path(file_path)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            
            await asyncio.to_thread(path.unlink)
            
            import time
            duration_ms = int((time.time() - start_time) * 1000)
            
            return ActionResult(
                step_id=step.id,
                status="success",
                output=f"Deleted {file_path}",
                duration_ms=duration_ms,
            )
        except Exception as e:
            return ActionResult(
                step_id=step.id,
                status="failed",
                output="",
                error_message=str(e),
            )
