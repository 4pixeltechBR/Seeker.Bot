import os
import subprocess
import logging
from datetime import datetime

from src.core.pipeline import SeekerPipeline
from src.providers.base import LLMRequest, invoke_with_fallback
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel
)
from config.models import CognitiveRole

log = logging.getLogger("seeker.git")

class GitBackupGoal:
    """
    Goal Autônomo de Git Automation (Backup e Controle de Versão Próprio).
    Verifica estado do repositório diariamente, gera commits interpretados via LLM e salva na nuvem.
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.01, max_daily_usd=0.05)
        self.repo_dir = os.getcwd()

    @property
    def name(self) -> str:
        return "git_backup"

    @property
    def interval_seconds(self) -> int:
        return 21600  # A cada 6 horas
    
    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    async def run_cycle(self) -> GoalResult:
        self._status = GoalStatus.RUNNING
        cycle_cost = 0.0
        
        try:
            # 1. Checa status
            status_output = subprocess.check_output(
                "git status -u --short", shell=True, cwd=self.repo_dir, text=True
            ).strip()

            if not status_output:
                self._status = GoalStatus.IDLE
                return GoalResult(success=True, summary="Sem alterações para commitar.", cost_usd=0.0)

            # 2. Add tudo 
            subprocess.run("git add .", shell=True, cwd=self.repo_dir, check=True)
            
            # Gera resumo dos diffs resumidos pro LLM gerar mensagem
            diff_output = subprocess.check_output(
                "git diff --staged --name-status", shell=True, cwd=self.repo_dir, text=True
            ).strip()

            # 3. LLM: Gerar mensagem do commit
            prompt = (
                f"Meus arquivos mudaram. Gere uma mensagem de commit de 1 linha seguindo o Conventional Commits.\n"
                f"Aqui está a lista de arquivos alterados/criados:\n{diff_output}\n\n"
                f"Retorne APENAS a string da mensagem de commit."
            )
            
            response = await invoke_with_fallback(
                CognitiveRole.FAST,
                LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    system="Você é um assistente dev local que foca em mensagens curtas. Retorne sem aspas e sem markdown.",
                    max_tokens=60,
                    temperature=0.1
                ),
                self.pipeline.model_router,
                self.pipeline.api_keys,
            )
            cycle_cost += response.cost_usd
            commit_msg = response.text.strip().replace('"', '').replace("'", "")
            
            if len(commit_msg) < 5:
                commit_msg = f"chore: auto-backup do sistema em {datetime.now().strftime('%Y-%m-%d %H:%M')}"

            # 4. Git Commit
            log.info(f"[git] Realizando commit: {commit_msg}")
            subprocess.run(f'git commit -m "{commit_msg}"', shell=True, cwd=self.repo_dir, check=True)

            # 5. Push com autenticação segura (token nunca persiste em .git/config)
            github_token = os.environ.get("GITHUB_TOKEN", "")
            repo_slug = os.environ.get("GITHUB_REPO", "")  # Ex: "4pixeltechBR/Seeker.Bot"

            pushed = "💾 apenas local (sem remote/token configurado)"
            if github_token:
                try:
                    # Passa URL diretamente ao push — token não fica em .git/config
                    # Usa lista de args (sem shell=True) para evitar exposição em ps/logs
                    push_url = f"https://x-access-token:{github_token}@github.com/{repo_slug}.git"
                    push_res = subprocess.run(
                        ["git", "push", "--force", push_url, "main"],
                        cwd=self.repo_dir,
                        capture_output=True,
                        text=True,
                    )
                    if push_res.returncode == 0:
                        pushed = f"✅ enviado ao remoto (GitHub {repo_slug})"
                    else:
                        # Redact token do stderr antes de logar
                        safe_stderr = push_res.stderr.replace(github_token, "***TOKEN***") if push_res.stderr else ""
                        pushed = "❌ Erro no push (verifique GITHUB_TOKEN e GITHUB_REPO)"
                        log.warning(f"[git] Push falhou (rc={push_res.returncode}): {safe_stderr[:300]}")
                except Exception as ex:
                    pushed = "❌ Falha de auth no push"
                    log.error(f"[git] Falha no push: {type(ex).__name__}", exc_info=True)
            else:
                # Tenta push com credenciais nativas do Windows (GCM)
                push_res = subprocess.run(
                    ["git", "push", "-u", "origin", "main"],
                    cwd=self.repo_dir,
                    capture_output=True,
                    text=True,
                )
                if push_res.returncode == 0:
                    pushed = "✅ enviado com credenciais nativas"

            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary=f"Git Commit realizado",
                notification=f"<b>🐙 GitHub Seeker</b>\n\nFiz um auto-backup do meu código.\n\n<code>{commit_msg}</code>\n\nStatus: {pushed}",
                cost_usd=cycle_cost
            )

        except Exception as e:
            self._status = GoalStatus.ERROR
            log.error(f"[git] Erro no fluxo de auto-backup: {e}", exc_info=True)
            return GoalResult(
                success=False,
                summary=f"Falha de versionamento: {e}",
                cost_usd=cycle_cost
            )

    def serialize_state(self) -> dict: return {}
    def load_state(self, state: dict) -> None: pass

def create_goal(pipeline) -> GitBackupGoal:
    return GitBackupGoal(pipeline)
