"""Persistência FIFO de IDs de mensagens WhatsApp já processadas."""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from pathlib import Path
from threading import RLock

log = logging.getLogger("seeker.whatsapp_vault.seen_ids")
DEFAULT_MAX = 5000


class SeenIdsStore:
    """FIFO deque de IDs vistos, persistida em JSON e protegida por lock."""

    def __init__(self, path: Path, max_size: int = DEFAULT_MAX):
        self.path = Path(path)
        self.max_size = max_size
        self._ids: deque[str] = deque(maxlen=max_size)
        self._loaded = False
        self._lock = RLock()

    def add(self, msg_id: str, save_immediately: bool = True) -> bool:
        """Return True when the message ID is new and added."""
        with self._lock:
            self._ensure_loaded()
            if msg_id in self._ids:
                return False
            self._ids.append(msg_id)
            if save_immediately:
                self._save()
            return True

    def is_seen(self, msg_id: str) -> bool:
        """Check if message ID has already been seen without adding it."""
        with self._lock:
            self._ensure_loaded()
            return msg_id in self._ids

    def flush(self) -> None:
        """Flush current in-memory seen IDs to disk in a single batch I/O operation."""
        with self._lock:
            self._save()

    def __contains__(self, msg_id: str) -> bool:
        with self._lock:
            self._ensure_loaded()
            return msg_id in self._ids

    def __len__(self) -> int:
        with self._lock:
            self._ensure_loaded()
            return len(self._ids)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                ids = data.get("ids", []) if isinstance(data, dict) else []
                if isinstance(ids, list):
                    for msg_id in ids:
                        if isinstance(msg_id, str):
                            self._ids.append(msg_id)
            except Exception as e:
                log.warning("[seen_ids] Falha ao ler %s: %s", self.path, e)
        self._loaded = True

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps({"ids": list(self._ids)}, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        except Exception as e:
            log.warning("[seen_ids] Falha ao salvar: %s", e)
