"""
SOUL.md Hot Reload Watcher

src/core/memory/soul_watcher.py

Poll `mtime` every 30s, recarrega sem restart.
"""

import asyncio
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("seeker.soul_watcher")


class SoulWatcher:
    """Watch SOUL.md for changes and trigger reload."""

    def __init__(self, soul_path: str | None = None, poll_interval: int = 30):
        self.soul_path = soul_path or self._find_soul_path()
        self.poll_interval = poll_interval
        self._last_mtime: float | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._cache: str = ""
        self._callbacks: list = []

    def _find_soul_path(self) -> str:
        base = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        return os.path.join(base, "SOUL.md")

    def load_soul(self) -> str:
        """Load SOUL.md content with proper formatting."""
        if not os.path.exists(self.soul_path):
            return ""
        try:
            with open(self.soul_path, "r", encoding="utf-8") as f:
                content = f.read()
            self._cache = "=== DIRETRIZES DE IDENTIDADE (SOUL.md) ===\n" + content + "\n\n"
            self._last_mtime = os.path.getmtime(self.soul_path)
            return self._cache
        except Exception as e:
            log.warning(f"[soul_watcher] Falha ao ler SOUL.md: {e}")
            return self._cache

    def register_callback(self, callback) -> None:
        """Register a callback to be called when SOUL.md changes."""
        self._callbacks.append(callback)

    async def _watch_loop(self) -> None:
        while self._running:
            try:
                if os.path.exists(self.soul_path):
                    mtime = os.path.getmtime(self.soul_path)
                    if self._last_mtime is not None and mtime != self._last_mtime:
                        log.info("[soul_watcher] SOUL.md mudou — recarregando...")
                        self.load_soul()
                        for cb in self._callbacks:
                            try:
                                await cb(self._cache)
                            except Exception as e:
                                log.warning(f"[soul_watcher] Callback falhou: {e}")
            except Exception as e:
                log.warning(f"[soul_watcher] Erro no poll: {e}")
            await asyncio.sleep(self.poll_interval)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.load_soul()
        self._task = asyncio.create_task(self._watch_loop())
        log.info(f"[soul_watcher] Iniciado — polling SOUL.md a cada {self.poll_interval}s")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
        log.info("[soul_watcher] Parado")

    def get_cached(self) -> str:
        return self._cache