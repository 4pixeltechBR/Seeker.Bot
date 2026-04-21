"""
Seeker.Bot — Event Map Scout Goal
src/skills/event_map_scout/goal.py

Coordena a varredura contínua de cidades.
"""

import logging

from src.core.goals.protocol import AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel
from src.core.pipeline import SeekerPipeline
from src.skills.event_map_scout.scout import EventMapEngine

log = logging.getLogger("seeker.event_map.goal")

class EventMapGoal:
    """
    Goal que varre uma cidade da fila por dia e envia o mapa gerado para o usuário.
    Segue o protocolo AutonomousGoal: run_cycle() sem argumentos.
    """
    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.50, max_daily_usd=1.00)

    @property
    def name(self) -> str:
        return "Event Map Scout"

    @property
    def interval_seconds(self) -> int:
        return 86400  # 1 vez por dia

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    def serialize_state(self) -> dict:
        return {}

    def load_state(self, state: dict) -> None:
        pass

    async def run_cycle(self) -> GoalResult:
        """Ciclo principal: pega a próxima cidade da fila e gera o mapa."""
        engine = EventMapEngine(self.pipeline)
        self._status = GoalStatus.RUNNING

        try:
            # Puxa a proxima cidade da fila
            async with self.pipeline.memory._db.execute(
                "SELECT cidade, estado FROM city_scan_queue WHERE status = 'pending' LIMIT 1"
            ) as cur:
                row = await cur.fetchone()

            if not row:
                log.info("[event_map_goal] Nenhuma cidade pendente na fila.")
                self._status = GoalStatus.IDLE
                return GoalResult(
                    success=True,
                    summary="Nenhuma cidade pendente na fila do Event Map Scout.",
                    cost_usd=0.0,
                )

            cidade, estado = row
            log.info(f"[event_map_goal] Iniciando cidade da fila: {cidade} - {estado}")

            # Marca como processando
            await self.pipeline.memory._db.execute(
                "UPDATE city_scan_queue SET status='scanning' WHERE cidade=? AND estado=?",
                (cidade, estado)
            )
            await self.pipeline.memory._db.commit()

            # Executa o Mapeamento
            scan = await engine.scan_city(cidade, estado)

            # Marca como concluido
            await self.pipeline.memory._db.execute(
                "UPDATE city_scan_queue SET status='done', last_scanned=CURRENT_TIMESTAMP WHERE cidade=? AND estado=?",
                (cidade, estado)
            )
            await self.pipeline.memory._db.commit()

            total_unique = scan.get('total_unique', 0)
            pdf_path = scan.get('pdf_path', '')

            notification = (
                f"<b>Event Map Scout Finalizado!</b>\n\n"
                f"<b>Cidade:</b> {cidade} - {estado}\n"
                f"<b>Eventos Preditivos Salvos:</b> {total_unique}\n\n"
                f"O Dossie PDF foi gerado."
            )

            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary=f"Mapeamento de {cidade}-{estado} concluido: {total_unique} eventos.",
                notification=notification,
                data={"pdf_path": pdf_path, "cidade": cidade, "estado": estado},
                cost_usd=0.0,
            )

        except Exception as e:
            log.error(f"[event_map_goal] Falha critica: {e}", exc_info=True)
            self._status = GoalStatus.ERROR
            return GoalResult(
                success=False,
                summary=f"Falha no Event Map Scout: {e}",
                cost_usd=0.0,
            )


def create_goal(pipeline: SeekerPipeline = None) -> "EventMapGoal":
    return EventMapGoal(pipeline)
