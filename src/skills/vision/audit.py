import asyncio
import os
import json
import logging
from datetime import datetime

log = logging.getLogger("seeker.vision.audit")

class VisionAudit:
    """
    Log Imutável das ações de visão.
    Grava o screenshot 'before', o que o modelo interpretou e a ação executada.
    """
    LOG_DIR = os.path.join(os.getcwd(), "data", "vision_logs")

    def __init__(self):
        os.makedirs(self.LOG_DIR, exist_ok=True)

    async def init_session(self, action_id: str):
        """Prepara pasta da sessão: ex: 2026-03-31_143022_portal_goiania"""
        now_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.session_dir = os.path.join(self.LOG_DIR, f"{now_str}_{action_id}")
        os.makedirs(self.session_dir, exist_ok=True)
        self.metadata = {"timestamp": now_str, "action_id": action_id, "logs": []}

    async def log_frame(self, frame_name: str, screenshot_bytes: bytes, bbox: dict = None):
        if not hasattr(self, 'session_dir'):
            return
            
        img_path = os.path.join(self.session_dir, f"{frame_name}.png")
        try:
            with open(img_path, "wb") as f:
                f.write(screenshot_bytes)
                
            log_entry = {"frame": frame_name, "time": datetime.now().isoformat()}
            if bbox:
                log_entry["bbox_target"] = bbox
                
            self.metadata["logs"].append(log_entry)
            await self._flush()
            log.info(f"[Audit] Salvo {frame_name}.png")
        except Exception as e:
            log.error(f"[Audit] Falha ao salvar log de visão: {e}")

    async def _flush(self):
        meta_path = os.path.join(self.session_dir, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)
