from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from src.skills.research_machine.notebooklm import NotebookLMClient
from src.skills.research_machine.synthesizer import Synthesizer
from src.skills.research_machine import store as rm_store
from src.skills.research_machine.yt_search import YouTubeSearch, YouTubeVideo
from src.skills.knowledge_vault.vault_writer import ObsidianWriter

log = logging.getLogger("seeker.research_machine.pipeline")


class ResearchPipeline:
    def __init__(self, pipeline, cookies_path: str | None = None):
        self.pipeline = pipeline
        self.yt = YouTubeSearch(cookies_path=cookies_path)
        self.synth = Synthesizer(pipeline)
        self.nb = NotebookLMClient()
        self.vault = ObsidianWriter()

    async def research(
        self,
        query: str,
        max_videos: int = 20,
        save_to_vault: bool = True,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())[:8]
        start = time.monotonic()
        log.info(f"[research_machine] run={run_id} query={query!r}")

        # 1. Busca no YouTube
        videos = self.yt.search(query, max_results=max_videos)
        if not videos:
            return {"run_id": run_id, "query": query, "error": "Nenhum vídeo encontrado"}

        # 2. Enriquece metadados (paralelo - roda em threads pois yt-dlp é sync)
        enriched = await asyncio.gather(*[
            asyncio.to_thread(self.yt.enrich, v) for v in videos[:10]
        ])

        # 3. Monta contexto textual para síntese
        ctx_lines = []
        for v in enriched:
            ctx_lines.append(f"**{v.title}** ({v.channel_name}) - {v.view_count} views")
            if v.description:
                ctx_lines.append(f"> {v.description[:200]}")
        videos_context = "\n".join(ctx_lines)

        # 4. Síntese via LLM
        result = await self.synth.synthesize(query, videos_context)

        # 5. NotebookLM (degradável)
        notebook = None
        if await self.nb.initialize():
            nb_title = f"Pesquisa: {query} ({date.today().isoformat()})"
            notebook = await self.nb.create_notebook(nb_title)
            if notebook and notebook.notebook_id != "local":
                urls = [v.url for v in enriched if v.url]
                await self.nb.add_urls(notebook.notebook_id, urls)

        # 6. Salva no Obsidian
        obsidian_path = None
        if save_to_vault:
            body = result.summary_md
            if notebook:
                body += f"\n\n---\n📓 [NotebookLM]({notebook.url})"
            try:
                fpath = self.vault.write_note(
                    title=f"{query} - Pesquisa",
                    body=body,
                    tags=["research", "youtube", "research_machine"],
                    source_type="research_machine",
                    source_url=f"ytsearch:{query}",
                )
                obsidian_path = str(fpath)
            except Exception as e:
                log.warning(f"[research_machine] Erro ao salvar no vault: {e}")

        # 7. Persiste run
        elapsed = time.monotonic() - start
        run_data = {
            "run_id": run_id,
            "query": query,
            "started_at": start,
            "finished_at": time.monotonic(),
            "duration_s": round(elapsed, 1),
            "videos": [{"title": v.title, "url": v.url, "channel": v.channel_name, "views": v.view_count} for v in enriched],
            "notebook_url": notebook.url if notebook else "",
            "obsidian_path": obsidian_path or "",
            "cost_usd": result.cost_usd,
            "status": "completed",
        }
        rm_store.save_run(run_id, run_data)

        # State global
        state = rm_store.load_state()
        state["queries"].append({"query": query, "run_id": run_id, "date": date.today().isoformat()})
        state["last_cursor"] = run_id
        state["total_cost_usd"] = state.get("total_cost_usd", 0.0) + result.cost_usd
        rm_store.save_state(state)

        # Fecha NotebookLM
        await self.nb.close()

        log.info(f"[research_machine] run={run_id} OK ({elapsed:.1f}s, ${result.cost_usd:.4f})")
        return run_data

    async def status(self, run_id: str) -> dict | None:
        return rm_store.load_run(run_id)
