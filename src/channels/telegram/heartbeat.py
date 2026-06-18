import asyncio
import logging
import os
import time

log = logging.getLogger("seeker.telegram.heartbeat")

HEARTBEAT_FILE = "logs/bot_heartbeat.txt"

async def start_heartbeat_loop(pipeline, stop_event: asyncio.Event = None):
    """
    Loop assíncrono recorrente de batimentos cardíacos e proatividade autônoma.
    Roda a cada 5 minutos.
    """
    log.info("[heartbeat] Loop de batimento cardíaco iniciado.")
    
    # Cria pasta logs se não existir
    os.makedirs("logs", exist_ok=True)
    
    while True:
        try:
            # 1. Escreve o timestamp de batimento cardíaco para o watchdog
            with open(HEARTBEAT_FILE, "w") as f:
                f.write(str(time.time()))
            log.debug("[heartbeat] Heartbeat atualizado para o watchdog.")
            
            # 2. Executa rotina preventiva: limpeza de scratch files antigos (com mais de 7 dias)
            scratch_dir = os.getenv("SCRATCH_DIR", "scratch")
            if os.path.exists(scratch_dir):
                now = time.time()
                cleaned = 0
                for f_name in os.listdir(scratch_dir):
                    path = os.path.join(scratch_dir, f_name)
                    if os.path.isfile(path):
                        if now - os.path.getmtime(path) > 7 * 86400: # 7 dias
                            try:
                                os.remove(path)
                                cleaned += 1
                            except Exception as e:
                                log.warning(f"[heartbeat] Falha ao limpar scratch file {f_name}: {e}")
                if cleaned > 0:
                    log.info(f"[heartbeat] Limpeza preventiva concluída: {cleaned} arquivos removidos da pasta scratch.")

            # 3. Executa rotina preventiva: monitora integridade do storage principal (GDRIVE_PATH)
            gdrive_path = os.getenv("GDRIVE_PATH")
            if gdrive_path and not os.path.exists(gdrive_path):
                log.error(f"[heartbeat] GDRIVE_PATH definido mas inacessível: {gdrive_path}")
            
        except Exception as e:
            log.error(f"[heartbeat] Erro no loop de batimento cardíaco: {e}", exc_info=True)
            
        if stop_event and stop_event.is_set():
            break

        # Aguarda 5 minutos antes do próximo ciclo
        try:
            if stop_event:
                await asyncio.wait_for(stop_event.wait(), timeout=300)
            else:
                await asyncio.sleep(300)
        except asyncio.TimeoutError:
            # Timeout normal do sleep/wait
            continue
        except asyncio.CancelledError:
            break

    log.info("[heartbeat] Loop de batimento cardíaco encerrado.")
