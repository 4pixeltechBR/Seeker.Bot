import logging
import json
import os
from datetime import datetime

from src.core.pipeline import SeekerPipeline
from src.core.goals.protocol import (
    AutonomousGoal,
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)
from .insta_scraper import InstaScraper

log = logging.getLogger("seeker.skills.instascraper.goal")

TARGETS_FILE = os.path.join(os.path.dirname(__file__), "targets.json")


class InstaScraperGoal(AutonomousGoal):
    """
    Goal Autônomo de Extração do Instagram.
    Periodicamente varre perfis definidos em targets.json buscando novos vídeos e metadados.
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(
            max_per_cycle_usd=0.02,
            max_daily_usd=0.05,
        )
        # Inicializa a classe base da skill
        self.scraper = InstaScraper()
        self._last_run_date = ""

    @property
    def name(self) -> str:
        return "instascraper"

    @property
    def interval_seconds(self) -> int:
        return 43200  # Executa a cada 12 horas

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    def serialize_state(self) -> dict:
        return {
            "last_run_date": self._last_run_date,
        }

    def load_state(self, state: dict) -> None:
        self._last_run_date = state.get("last_run_date", "")

    def load_targets(self) -> list[dict]:
        """Carrega a lista de alvos de raspagem do targets.json."""
        if not os.path.exists(TARGETS_FILE):
            return []
        try:
            with open(TARGETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"[instascraper] Erro ao ler targets.json: {e}")
            return []

    def save_targets(self, targets: list[dict]):
        """Salva a lista de alvos de volta no targets.json."""
        try:
            with open(TARGETS_FILE, "w", encoding="utf-8") as f:
                json.dump(targets, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"[instascraper] Erro ao gravar targets.json: {e}")

    async def run_cycle(self) -> GoalResult:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        self._status = GoalStatus.RUNNING
        targets = self.load_targets()

        # Filtra os perfis que estão marcados como 'pending'
        pending_targets = [t for t in targets if t.get("status") == "pending"]

        if not pending_targets:
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary="InstaScraper: Nenhum perfil com status 'pending' para extrair.",
                cost_usd=0.0,
            )

        log.info(f"[instascraper] Executando ciclo de raspagem para {len(pending_targets)} alvos.")
        results_summary = []
        notifications = []

        for target in pending_targets:
            username = target["name"]
            limit = target.get("limit", 10)

            log.info(f"[instascraper] Iniciando raspagem autônoma de @{username} (limite: {limit}).")
            
            # Executa a raspagem (bloqueante mas executado de forma segura no threadpool se necessário,
            # como time.sleep é usado, roda sequencialmente no scheduler)
            result_msg = self.scraper.raspar_perfil(username, limit_posts=limit)
            
            results_summary.append(f"@{username}: {result_msg}")

            if "Sucesso" in result_msg:
                # Marca o alvo como completed ou mantém ativo mudando a data do último sync
                target["status"] = "completed"
                target["last_synced"] = today_str
                
                notifications.append(
                    f"📸 <b>InstaScraper: @{username} clonado com sucesso!</b>\n"
                    f"• Vídeos e metadados salvos na pasta local do Seeker.\n"
                    f"• Notas Markdown geradas e injetadas na Inbox do Obsidian.\n"
                )
            else:
                notifications.append(
                    f"⚠️ <b>InstaScraper: Falha ao clonar @{username}</b>\n"
                    f"• Detalhe: {result_msg}\n"
                )

        # Salva o status atualizado
        self.save_targets(targets)

        self._last_run_date = today_str
        self._status = GoalStatus.IDLE

        summary = "; ".join(results_summary)
        notification_html = "\n\n".join(notifications)

        return GoalResult(
            success=True,
            summary=f"InstaScraper: {summary}",
            notification=notification_html,
            cost_usd=0.0,  # Scraping local gratuito sem uso de API LLM paga
        )


def create_goal(pipeline: SeekerPipeline) -> AutonomousGoal:
    return InstaScraperGoal(pipeline)
