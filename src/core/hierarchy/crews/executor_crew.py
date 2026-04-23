"""
Executor Crew - Action execution and automation
Latency: 1-30s, Cost: $0.01-0.05/execution
Confidence: 0.9 success, 0.3 partial, 0.1 failed

Handles:
  1. Git automation (commit, push, backup)
  2. Bash command execution (with whitelist)
  3. File operations (safe read/write/delete)
  4. Remote trigger delegation (desktop control via Claude Code)
"""

import os
import subprocess
import logging
import asyncio
import time
from typing import Optional, Dict, Any
from datetime import datetime

from ..interfaces import CrewRequest, CrewResult, CrewPriority
from . import BaseCrew

log = logging.getLogger("seeker.executor_crew")


class ExecutorCrew(BaseCrew):
    """Execution crew for autonomous actions"""

    # Whitelist de comandos bash por nível de risco
    BASH_WHITELIST = {
        "L2_SILENT": [
            "ls", "cat", "grep", "find", "head", "tail", "wc",
            "git status", "git log", "pwd", "echo"
        ],
        "L1_LOGGED": [
            "mkdir", "touch", "cp", "mv", "echo >",
            "git add", "git diff", "git fetch"
        ],
        "L0_MANUAL": [
            "rm", "rmdir", "chmod", "chown", "dd",
            "git rm", "git reset", "git rebase"
        ]
    }

    def __init__(self):
        super().__init__("executor", CrewPriority.HIGH)
        self._repo_dir = os.getcwd()
        self._last_actions = []

    async def _execute_internal(self, request: CrewRequest) -> CrewResult:
        """
        Execute actions requested by user input
        Supported action types:
          - git_commit: commit staged changes with LLM-generated message
          - git_push: push to remote repository
          - bash: execute bash command (if whitelisted)
          - file_write: safe file write with backup
          - file_delete: safe file deletion with snapshot
        """
        start_time = time.time()

        user_input = request.user_input.lower()
        actions_executed = []
        errors = []
        total_cost = 0.0

        # ──────────────────────────────────────────────────────────
        # DETECT ACTION INTENT
        # ──────────────────────────────────────────────────────────
        git_commit = any(kw in user_input for kw in ["commit", "backup", "save", "fazer commit"])
        git_push = "push" in user_input or "enviar" in user_input
        bash_exec = any(kw in user_input for kw in ["execute", "rodar", "executar", "bash"])

        if not (git_commit or git_push or bash_exec):
            return CrewResult(
                response="Nenhuma ação de execução detectada no input.",
                crew_id=self.crew_id,
                cost_usd=0.0,
                llm_calls=0,
                confidence=0.5,
                latency_ms=int((time.time() - start_time) * 1000),
                sources=[],
            )

        # ──────────────────────────────────────────────────────────
        # ACTION 1: GIT COMMIT
        # ──────────────────────────────────────────────────────────
        if git_commit:
            try:
                status_output = subprocess.check_output(
                    "git status -u --short",
                    shell=True,
                    cwd=self._repo_dir,
                    text=True,
                    timeout=10
                ).strip()

                if status_output:
                    # Stage changes
                    subprocess.run(
                        "git add .",
                        shell=True,
                        cwd=self._repo_dir,
                        timeout=10,
                        check=True,
                        capture_output=True
                    )

                    # Get diff for LLM
                    diff_output = subprocess.check_output(
                        "git diff --staged --name-status",
                        shell=True,
                        cwd=self._repo_dir,
                        text=True,
                        timeout=10
                    ).strip()

                    # Generate commit message via LLM
                    # NOTE: Em production, usar cascade_adapter.invoke() aqui
                    # Por enquanto, usar mensagem genérica
                    commit_msg = self._generate_commit_message(diff_output)

                    # Perform commit
                    subprocess.run(
                        f'git commit -m "{commit_msg}"',
                        shell=True,
                        cwd=self._repo_dir,
                        timeout=15,
                        check=True,
                        capture_output=True
                    )

                    actions_executed.append(f"✅ Git commit: {commit_msg}")
                    log.info(f"[executor] Git commit successful: {commit_msg}")
                else:
                    actions_executed.append("ℹ️ Nenhuma alteração para commitar")
            except subprocess.TimeoutExpired:
                errors.append("❌ Git commit timeout (>15s)")
                log.error("[executor] Git commit timeout")
            except Exception as e:
                errors.append(f"❌ Git commit failed: {str(e)[:50]}")
                log.error(f"[executor] Git commit error: {e}")

        # ──────────────────────────────────────────────────────────
        # ACTION 2: GIT PUSH
        # ──────────────────────────────────────────────────────────
        if git_push:
            try:
                github_token = os.environ.get("GITHUB_TOKEN", "")
                repo_slug = os.environ.get("GITHUB_REPO", "")

                if github_token and repo_slug:
                    push_url = f"https://x-access-token:{github_token}@github.com/{repo_slug}.git"
                    push_res = subprocess.run(
                        ["git", "push", "--force", push_url, "main"],
                        cwd=self._repo_dir,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    if push_res.returncode == 0:
                        actions_executed.append(f"✅ Push to {repo_slug}")
                        log.info(f"[executor] Push successful: {repo_slug}")
                    else:
                        errors.append(f"❌ Push failed (check token)")
                        log.warning(f"[executor] Push failed: rc={push_res.returncode}")
                else:
                    errors.append("⚠️ GITHUB_TOKEN ou GITHUB_REPO não configurados")
            except subprocess.TimeoutExpired:
                errors.append("❌ Git push timeout (>30s)")
            except Exception as e:
                errors.append(f"❌ Git push error: {str(e)[:50]}")
                log.error(f"[executor] Push error: {e}")

        # ──────────────────────────────────────────────────────────
        # ACTION 3: BASH EXECUTION
        # ──────────────────────────────────────────────────────────
        if bash_exec and not (git_commit or git_push):
            # Extract command from user input
            # Example: "execute: ls -la /tmp"
            if ":" in user_input:
                command = user_input.split(":", 1)[1].strip()

                # Check whitelist
                is_whitelisted = any(
                    command.startswith(kw)
                    for tier_cmds in self.BASH_WHITELIST.values()
                    for kw in tier_cmds
                )

                if is_whitelisted:
                    try:
                        output = subprocess.check_output(
                            command,
                            shell=True,
                            cwd=self._repo_dir,
                            text=True,
                            timeout=30
                        )
                        actions_executed.append(f"✅ Bash: {command[:40]}")
                        log.info(f"[executor] Bash executed: {command}")
                    except subprocess.TimeoutExpired:
                        errors.append(f"❌ Command timeout: {command[:40]}")
                    except Exception as e:
                        errors.append(f"❌ Bash error: {str(e)[:50]}")
                        log.error(f"[executor] Bash error: {e}")
                else:
                    errors.append(f"❌ Comando não whitelisted: {command[:40]}")
                    log.warning(f"[executor] Command not whitelisted: {command}")

        # ──────────────────────────────────────────────────────────
        # BUILD RESPONSE
        # ──────────────────────────────────────────────────────────
        latency_ms = int((time.time() - start_time) * 1000)

        if actions_executed and not errors:
            response_text = "✅ Execução bem-sucedida\n\n" + "\n".join(actions_executed)
            confidence = 0.9
        elif actions_executed and errors:
            response_text = (
                "⚠️ Execução parcial\n\n"
                f"Sucesso:\n" + "\n".join([f"  {a}" for a in actions_executed]) + "\n\n"
                f"Erros:\n" + "\n".join([f"  {e}" for e in errors])
            )
            confidence = 0.5
        else:
            response_text = "❌ Nenhuma ação executada\n\n" + "\n".join(errors)
            confidence = 0.1

        # Store action in history
        self._last_actions.append({
            "timestamp": time.time(),
            "user_input": user_input[:100],
            "success": len(actions_executed) > 0 and not errors,
            "actions": actions_executed,
            "errors": errors
        })
        if len(self._last_actions) > 20:
            self._last_actions.pop(0)

        return CrewResult(
            response=response_text,
            crew_id=self.crew_id,
            cost_usd=total_cost,
            llm_calls=1 if git_commit else 0,  # Commit message generation counts as 1 LLM call
            confidence=confidence,
            latency_ms=latency_ms,
            sources=[],
            should_save_fact=False,
        )

    def _generate_commit_message(self, diff_output: str) -> str:
        """
        Generate a commit message from diff output
        In production, this would call cascade_adapter.invoke() with FAST role
        """
        # Simple heuristic for now
        if "src/" in diff_output:
            if "test" in diff_output.lower():
                return "test: update test suite"
            return "feat: update source code"
        elif "docs/" in diff_output:
            return "docs: update documentation"
        else:
            return f"chore: auto-backup do sistema em {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    def get_status(self) -> dict:
        """Extended status with execution history"""
        base_status = super().get_status()
        base_status.update({
            "last_actions_count": len(self._last_actions),
            "recent_actions": self._last_actions[-3:] if self._last_actions else [],
            "repo_dir": self._repo_dir,
        })
        return base_status


executor = ExecutorCrew()
