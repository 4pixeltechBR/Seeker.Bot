"""
KnowledgeDigest Goal - Resumo semanal do cofre Obsidian
"""
import logging
from datetime import datetime, timedelta
from src.core.goals.protocol import GoalResult, GoalStatus, NotificationChannel, GoalBudget
from .vault_searcher import VaultSearcher
from .vault_writer import ObsidianWriter
from .prompts import DIGEST_PROMPT_SYSTEM, DIGEST_PROMPT_USER

log = logging.getLogger("seeker.knowledge_vault.digest")

class KnowledgeDigestGoal:
    """
    Digest semanal do cofre Obsidian.
    Toda segunda-feira às 08:00.
    """
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.searcher = VaultSearcher()
        self.writer = ObsidianWriter()
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.01, max_daily_usd=0.02)
        
        self.target_weekday = 0 # Segunda
        self.target_hour = 8
        self._last_run_date = ""

    @property
    def name(self) -> str:
        return "knowledge_digest"

    @property
    def interval_seconds(self) -> int:
        return 3600 # Checa a cada hora

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    def serialize_state(self) -> dict:
        return {"last_run_date": self._last_run_date}

    def load_state(self, state: dict) -> None:
        self._last_run_date = state.get("last_run_date", "")

    async def run_cycle(self) -> GoalResult:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        
        # Verifica se é segunda e se já rodou
        if now.weekday() != self.target_weekday or self._last_run_date == today_str:
            return GoalResult(success=True, summary="Fora do horário/dia de digest")

        if now.hour < self.target_hour:
            return GoalResult(success=True, summary="Aguardando 08:00")

        self._status = GoalStatus.RUNNING
        
        try:
            # 1. Coleta notas da semana
            recent_notes = self.searcher.list_recent(days=7)
            if not recent_notes:
                self._last_run_date = today_str
                self._status = GoalStatus.IDLE
                return GoalResult(success=True, summary="Nenhuma nota nova esta semana")

            # 2. Gera resumo executivo via LLM
            notes_summary = "\n".join([f"- {n.title} ({', '.join(n.tags)})" for n in recent_notes])
            
            prompt_user = DIGEST_PROMPT_USER.format(notes_summary=notes_summary)
            
            # Usa BALANCED para melhor síntese
            response = await self.pipeline.cascade_adapter.prompt(
                system_prompt=DIGEST_PROMPT_SYSTEM,
                user_prompt=prompt_user,
                role="balanced"
            )
            
            digest_text = response.strip()
            
            # 3. Salva digest como nota no cofre
            self.writer.write_note(
                title=f"Digest Semanal - {today_str}",
                body=digest_text,
                tags=["digest", "produtividade"],
                source_type="digest"
            )
            
            self._last_run_date = today_str
            self._status = GoalStatus.IDLE
            
            notification = (
                f"📚 **Digest Semanal do Cofre**\n\n"
                f"Foram capturadas **{len(recent_notes)}** novas notas esta semana.\n\n"
                f"{digest_text[:1000]}..." # Preview
            )
            
            return GoalResult(
                success=True,
                summary=f"Digest gerado: {len(recent_notes)} notas resumidas",
                notification=notification,
                cost_usd=0.002 # Estimativa
            )
            
        except Exception as e:
            self._status = GoalStatus.IDLE
            log.error(f"[digest] Erro ao gerar digest: {e}")
            return GoalResult(success=False, summary=f"Erro no digest: {e}")

def create_goal(pipeline):
    return KnowledgeDigestGoal(pipeline)
