"""
Seeker.Bot — Weekly Leads Report
src/skills/revenue_weekly/goal.py

Toda Segunda-feira às 08h, coleleta os PDFs de leads dos últimos 7 dias,
compacta em um ZIP e envia via Telegram.
"""
import os
import zipfile
import time
from datetime import datetime
import logging

from src.core.pipeline import SeekerPipeline
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel,
)

log = logging.getLogger("seeker.hunter.weekly")


class WeeklyLeadsReportGoal(AutonomousGoal):
    """
    Agrupa os leads (PDFs) gerados na semana anterior e envia um dossiê em ZIP.
    Executa toda Segunda-feira por volta das 08h00.
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._budget = GoalBudget(max_per_cycle_usd=0.0, max_daily_usd=0.0)
        self._status = GoalStatus.IDLE
        self._last_run_day = ""

    @property
    def name(self) -> str:
        return "revenue_weekly_report"

    @property
    def interval_seconds(self) -> int:
        return 600  # Checa a cada 10 minutos para garantir o gatilho das 07:30

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    async def run_cycle(self) -> GoalResult:
        now = datetime.now()
        hoje_str = now.strftime("%Y-%m-%d")

        # Só roda na Segunda-feira (weekday() == 0) entre 07h30 e 07h59
        if now.weekday() != 0 or now.hour != 7 or now.minute < 30:
            return GoalResult(
                success=True,
                summary="Aguardando Segunda-feira 07:30",
                cost_usd=0.0,
            )

        if self._last_run_day == hoje_str:
            return GoalResult(
                success=True,
                summary="Relatório semanal já enviado hoje",
                cost_usd=0.0,
            )

        self._status = GoalStatus.RUNNING
        leads_dir = os.path.join(os.getcwd(), "data", "leads")
        os.makedirs(leads_dir, exist_ok=True)

        one_week_ago = time.time() - (7 * 86400)

        recent_pdfs = []
        for fname in os.listdir(leads_dir):
            if fname.endswith(".pdf"):
                fpath = os.path.join(leads_dir, fname)
                if os.path.getmtime(fpath) >= one_week_ago:
                    recent_pdfs.append(fpath)

        if not recent_pdfs:
            self._last_run_day = hoje_str
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary="Semanal enviado (vazio)",
                notification=(
                    "📊 <b>Relatório Semanal de Leads</b>\n\n"
                    "Nenhum Lead BANT ≥ 7.0 capturado na última semana."
                ),
                cost_usd=0.0,
            )

        # Compacta todos os PDFs em um ZIP
        zip_name = f"Leads_Semana_{now.strftime('%Y_%W')}.zip"
        zip_path = os.path.join(leads_dir, zip_name)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for pdf in recent_pdfs:
                zf.write(pdf, arcname=os.path.basename(pdf))

        self._last_run_day = hoje_str
        self._status = GoalStatus.IDLE

        return GoalResult(
            success=True,
            summary=f"{len(recent_pdfs)} leads compactados no relatório semanal",
            notification=(
                f"📊 <b>Relatório Semanal Ativo!</b>\n\n"
                f"Coletei <b>{len(recent_pdfs)}</b> dossiês de prospects "
                f"da semana passada e empacotei para você no anexo abaixo. "
                f"Bons negócios!"
            ),
            cost_usd=0.0,
            data={"pdf_path": zip_path},
        )

    def serialize_state(self) -> dict:
        return {"last_run_day": self._last_run_day}

    def load_state(self, state: dict) -> None:
        self._last_run_day = state.get("last_run_day", "")


def create_goal(pipeline: SeekerPipeline) -> WeeklyLeadsReportGoal:
    return WeeklyLeadsReportGoal(pipeline)
