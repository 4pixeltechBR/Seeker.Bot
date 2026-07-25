import json
import logging
import os

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
        """
        Clonagem autônoma de perfis DESATIVADA.

        O InstaScraper opera apenas em modo on-demand: o usuário solicita o download
        de um vídeo específico pelo chat e o bot baixa via download_single_post.
        A clonagem periódica de perfis foi removida para evitar conflitos de path,
        shadowban e downloads não solicitados.
        """
        self._status = GoalStatus.IDLE
        log.info("[instascraper] Ciclo autônomo de clonagem desativado — use /instascraper para baixar vídeos individuais.")
        return GoalResult(
            success=True,
            summary="InstaScraper: clonagem autônoma desativada. Use /instascraper para downloads sob demanda.",
            cost_usd=0.0,
        )


def create_goal(pipeline: SeekerPipeline) -> AutonomousGoal:
    return InstaScraperGoal(pipeline)
