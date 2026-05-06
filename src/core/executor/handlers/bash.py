"""Bash Command Handler — Remote Executor Track B2"""
import subprocess
import logging
import asyncio
from typing import Optional, List
from src.core.executor.models import ActionStep, ActionResult, ApprovalTier, ActionStatus, ActionType

log = logging.getLogger("executor.handlers.bash")

# Bash Whitelist (3-tier security)
BASH_WHITELIST = {
    "L2_SILENT": ["ls", "cat", "grep", "find", "head", "tail", "wc", "git status", "pwd", "echo"],
    "L1_LOGGED": ["mkdir", "touch", "cp", "mv", "echo", ">", "git add", "git diff", "git fetch"],
    "L0_MANUAL": ["rm", "rmdir", "chmod", "chown", "dd", "git rm", "git reset", "git rebase"],
}

class BashHandler:
    """Executa comandos bash com segurança via whitelist"""
    
    def __init__(self):
        self.execution_history = []
    
    async def execute(self, step: ActionStep) -> ActionResult:
        """
        Executa comando bash com validação de whitelist.
        
        Args:
            step: ActionStep com comando bash
        
        Returns:
            ActionResult com output/error
        """
        import time
        start_time = time.time()
        
        try:
            # Validar contra whitelist
            if not self._is_whitelisted(step.command, step.approval_tier):
                return ActionResult(
                    step_id=step.id,
                    status="failed",
                    output="",
                    error_message=f"Comando bloqueado por whitelist: {step.command}",
                )
            
            # Executar com timeout
            result = await asyncio.wait_for(
                asyncio.to_thread(self._run_subprocess, step.command, step.timeout_seconds),
                timeout=step.timeout_seconds + 1.0
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            if result["returncode"] == 0:
                return ActionResult(
                    step_id=step.id,
                    status="success",
                    output=result["stdout"][:2000],
                    duration_ms=duration_ms,
                )
            else:
                return ActionResult(
                    step_id=step.id,
                    status="failed",
                    output=result["stdout"][:1000],
                    error_message=result["stderr"][:1000],
                    duration_ms=duration_ms,
                )
        
        except asyncio.TimeoutError:
            return ActionResult(
                step_id=step.id,
                status="timeout",
                output="",
                error_message=f"Comando excedeu timeout de {step.timeout_seconds}s",
            )
        except Exception as e:
            return ActionResult(
                step_id=step.id,
                status="failed",
                output="",
                error_message=str(e),
            )
    
    def _is_whitelisted(self, command: str, tier: ApprovalTier) -> bool:
        """Verifica se comando está na whitelist para o tier"""
        cmd_tokens = command.split()
        if not cmd_tokens:
            return False
        
        main_cmd = cmd_tokens[0]
        
        # L2_SILENT permite tudo de L2 e acima
        if tier == ApprovalTier.L2_SILENT:
            return main_cmd in BASH_WHITELIST["L2_SILENT"]
        
        # L1_LOGGED permite tudo de L1 e acima
        if tier == ApprovalTier.L1_LOGGED:
            allowed = BASH_WHITELIST["L2_SILENT"] + BASH_WHITELIST["L1_LOGGED"]
            return main_cmd in allowed
        
        # L0_MANUAL permite tudo
        if tier == ApprovalTier.L0_MANUAL:
            allowed = BASH_WHITELIST["L2_SILENT"] + BASH_WHITELIST["L1_LOGGED"] + BASH_WHITELIST["L0_MANUAL"]
            return main_cmd in allowed
        
        return False
    
    def _run_subprocess(self, command: str, timeout: int) -> dict:
        """Executa subprocess com captura de output"""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"Subprocess timeout after {timeout}s")
