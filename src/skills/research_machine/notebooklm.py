from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("seeker.research_machine.notebooklm")


@dataclass
class Notebook:
    notebook_id: str
    title: str
    url: str


class NotebookLMClient:
    def __init__(self):
        self._client = None
        self._available = False

    async def initialize(self) -> bool:
        if self._available:
            return True
        try:
            import notebooklm
            self._client = await notebooklm.NotebookLMClient.from_storage()
            # Inicializa contexto async (entra no __aenter__ que ativa o client)
            self._ctx = self._client.__aenter__()
            await self._ctx
            self._available = True
            log.info("[notebooklm] Client autenticado e inicializado")
            return True
        except Exception as e:
            log.warning(f"[notebooklm] Não disponível — modo degradado: {e}")
            self._available = False
            return False

    async def close(self) -> None:
        if self._client and hasattr(self, "_ctx"):
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass
            self._available = False

    @property
    def available(self) -> bool:
        return self._available and self._client is not None

    async def create_notebook(self, title: str) -> Notebook | None:
        if not await self.initialize():
            log.warning("[notebooklm] Modo degradado: nota local")
            return Notebook(notebook_id="local", title=title, url="")
        try:
            nb = await self._client.notebooks.create(title=title)
            return Notebook(notebook_id=nb.id, title=nb.title, url=f"https://notebooklm.google.com/notebook/{nb.id}")
        except Exception as e:
            log.error(f"[notebooklm] Erro ao criar notebook: {e}")
            return None

    async def add_urls(self, notebook_id: str, urls: list[str]) -> bool:
        if not await self.initialize():
            return False
        ok = True
        for url in urls:
            try:
                await self._client.sources.add_url(notebook_id=notebook_id, url=url, wait=True)
            except Exception as e:
                log.warning(f"[notebooklm] Falha ao adicionar {url}: {e}")
                ok = False
        return ok

    async def add_text(self, notebook_id: str, title: str, content: str) -> bool:
        if not await self.initialize():
            return False
        try:
            await self._client.sources.add_text(
                notebook_id=notebook_id, title=title, content=content, wait=True
            )
            return True
        except Exception as e:
            log.warning(f"[notebooklm] Falha ao adicionar texto: {e}")
            return False

    async def generate_report(self, notebook_id: str, custom_prompt: str = "") -> str:
        if not await self.initialize():
            return ""
        try:
            task = await self._client.artifacts.generate_report(
                notebook_id=notebook_id, custom_prompt=custom_prompt or None
            )
            result = await self._client.artifacts.wait_for_completion(
                notebook_id=notebook_id, task_id=str(task)
            )
            return str(result)
        except Exception as e:
            log.warning(f"[notebooklm] Erro ao gerar report: {e}")
            return ""