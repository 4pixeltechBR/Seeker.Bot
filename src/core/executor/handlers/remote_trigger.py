"""Remote Trigger Handler (Claude Code Delegation) — Remote Executor Track B2"""
import logging
import asyncio
from src.core.executor.models import ActionStep, ActionResult

log = logging.getLogger("executor.handlers.remote_trigger")

class RemoteTriggerHandler:
    """Delega ações para Claude Code via Remote Trigger API"""
    
    def __init__(self, claude_code_client=None):
        self.claude_code = claude_code_client
        self._health_check_interval = 30.0  # 30s health check
    
    async def execute(self, step: ActionStep) -> ActionResult:
        """
        Executa ação delegando para Claude Code.
        
        Args:
            step: ActionStep com comando format "screenshot" ou "click:x,y" ou "type:text"
        
        Returns:
            ActionResult com resultado da delegação
        """
        import time
        start_time = time.time()
        
        try:
            # Health check: Claude Code disponível?
            is_healthy = await self._health_check()
            if not is_healthy:
                return ActionResult(
                    step_id=step.id,
                    status="failed",
                    output="",
                    error_message="Claude Code não disponível (health check falhou)",
                )
            
            # Parse comando
            cmd_parts = step.command.split(":", 1)
            action = cmd_parts[0].lower()
            
            if action == "screenshot":
                result = await self._delegate_screenshot(step)
            elif action == "click":
                x, y = cmd_parts[1].split(",")
                result = await self._delegate_click(step, int(x), int(y))
            elif action == "type":
                text = cmd_parts[1] if len(cmd_parts) > 1 else ""
                result = await self._delegate_type(step, text)
            else:
                raise ValueError(f"Unknown remote action: {action}")
            
            duration_ms = int((time.time() - start_time) * 1000)
            result.duration_ms = duration_ms
            return result
        
        except Exception as e:
            return ActionResult(
                step_id=step.id,
                status="failed",
                output="",
                error_message=str(e),
            )
    
    async def _health_check(self) -> bool:
        """Verifica se Claude Code está online"""
        if not self.claude_code:
            log.warning("[remote_trigger] Claude Code client não configurado")
            return False
        
        try:
            # TODO: implementar health check via API
            # await asyncio.wait_for(self.claude_code.health_check(), timeout=5.0)
            return True
        except Exception as e:
            log.warning(f"[remote_trigger] Health check falhou: {e}")
            return False
    
    async def _delegate_screenshot(self, step: ActionStep) -> ActionResult:
        """Delega screenshot para Claude Code"""
        # TODO: implementar delegação via API
        return ActionResult(
            step_id=step.id,
            status="success",
            output="[screenshot_data_base64]",
        )
    
    async def _delegate_click(self, step: ActionStep, x: int, y: int) -> ActionResult:
        """Delega click para Claude Code"""
        # TODO: implementar delegação via API
        return ActionResult(
            step_id=step.id,
            status="success",
            output=f"Clicked at ({x}, {y})",
        )
    
    async def _delegate_type(self, step: ActionStep, text: str) -> ActionResult:
        """Delega type para Claude Code"""
        # TODO: implementar delegação via API
        return ActionResult(
            step_id=step.id,
            status="success",
            output=f"Typed: {text}",
        )
