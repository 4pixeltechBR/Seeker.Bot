"""HTTP API Handler — Remote Executor Track B2"""
import asyncio
import httpx
import logging
import json
from src.core.executor.models import ActionStep, ActionResult

log = logging.getLogger("executor.handlers.api")

class APIHandler:
    """Executa chamadas HTTP com timeout e retry"""
    
    def __init__(self, timeout: float = 30.0, max_retries: int = 1):
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=timeout)
    
    async def execute(self, step: ActionStep) -> ActionResult:
        """
        Executa chamada HTTP.
        
        Args:
            step: ActionStep com comando format "GET:url" ou "POST:url:json_data"
        
        Returns:
            ActionResult com response
        """
        import time
        start_time = time.time()
        
        try:
            cmd_parts = step.command.split(":", 2)
            method = cmd_parts[0].upper()
            url = cmd_parts[1]
            data = cmd_parts[2] if len(cmd_parts) > 2 else None
            
            if method not in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            # Realizar requisição com retry
            for attempt in range(self.max_retries + 1):
                try:
                    response = await self._client.request(method, url, json=json.loads(data) if data else None)
                    
                    duration_ms = int((time.time() - start_time) * 1000)
                    
                    if response.status_code < 400:
                        return ActionResult(
                            step_id=step.id,
                            status="success",
                            output=response.text[:5000],
                            duration_ms=duration_ms,
                        )
                    else:
                        return ActionResult(
                            step_id=step.id,
                            status="failed",
                            output=response.text[:1000],
                            error_message=f"HTTP {response.status_code}",
                            duration_ms=duration_ms,
                        )
                except httpx.TimeoutException:
                    if attempt < self.max_retries:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise
        
        except Exception as e:
            return ActionResult(
                step_id=step.id,
                status="failed",
                output="",
                error_message=str(e),
            )
    
    async def close(self):
        """Fecha conexão HTTP"""
        await self._client.aclose()
