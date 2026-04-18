"""
Seeker.Bot — Event Map Scout Goal
src/skills/event_map_scout/goal.py

Coordena a varredura contínua de cidades.
"""

import logging
from typing import Optional, Dict, Any, List

from src.core.goals.protocol import AutonomousGoal
from src.core.pipeline import SeekerPipeline
from src.skills.event_map_scout.scout import EventMapEngine

log = logging.getLogger("seeker.event_map.goal")

class EventMapGoal(AutonomousGoal):
    """
    Goal que varre uma cidade da fila por dia e envia o mapa gerado para o usuário.
    """
    @property
    def id(self) -> str:
        return "event_map_scout"
        
    @property
    def name(self) -> str:
        return "Event Map Scout"
        
    @property
    def description(self) -> str:
        return "Mapeamento cirúrgico preditivo de eventos B2B por município."
        
    @property
    def interval_seconds(self) -> int:
        return 86400  # 1 vez por dia

    @property
    def execution_window(self) -> tuple[int, int]:
        return (7, 10)  # Roda entre 7h e 10h da manhã

    async def execute(self, pipeline: SeekerPipeline) -> Optional[Dict[str, Any]]:
        engine = EventMapEngine(pipeline)
        
        # Puxa a proxima cidade da fila
        async with pipeline.memory._db.execute(
            "SELECT cidade, estado FROM city_scan_queue WHERE status = 'pending' LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
            
        if not row:
            log.info("[event_map_goal] Nenhuma cidade pendente na fila.")
            return {"status": "skipped", "reason": "empty_queue"}
            
        cidade, estado = row
        log.info(f"[event_map_goal] Iniciando cidade da fila: {cidade} - {estado}")
        
        # Marca como processando
        await pipeline.memory._db.execute(
            "UPDATE city_scan_queue SET status='scanning' WHERE cidade=? AND estado=?",
            (cidade, estado)
        )
        await pipeline.memory._db.commit()
        
        # Executa o Mapeamento
        result = await engine.scan_city(cidade, estado)
        
        # Marca como concluido
        await pipeline.memory._db.execute(
            "UPDATE city_scan_queue SET status='done', last_scanned=CURRENT_TIMESTAMP WHERE cidade=? AND estado=?",
            (cidade, estado)
        )
        await pipeline.memory._db.commit()
        
        total_unique = result.get('total_unique', 0)
        pdf_path = result.get('pdf_path', '')
        
        mensagem = (
            f"🎯 <b>Event Map Scout Finalizado!</b>\n\n"
            f"🗺️ <b>Cidade:</b> {cidade} - {estado}\n"
            f"🔍 <b>Eventos Preditivos Salvos:</b> {total_unique}\n\n"
            f"O Dossiê PDF foi gerado."
        )
        
        # Notifica no Telegram
        telegram_bot = getattr(pipeline, 'telegram', None)
        if telegram_bot:
            try:
                chat_id = telegram_bot.admin_chat_id
                if pdf_path:
                    await pipeline.telegram.send_document(
                        chat_id=chat_id,
                        document_path=pdf_path,
                        caption=mensagem,
                        parse_mode="HTML"
                    )
                else:
                    await pipeline.telegram.send_message(
                        chat_id=chat_id,
                        text=mensagem,
                        parse_mode="HTML"
                    )
            except Exception as e:
                log.error(f"Erro ao enviar PDF pro Telegram: {e}")
                
        return result

def create_goal(pipeline: SeekerPipeline = None) -> AutonomousGoal:
    return EventMapGoal()
