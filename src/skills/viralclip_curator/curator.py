"""
Seeker.Bot — ViralClip Curator
src/skills/viralclip_curator/curator.py

Goal autônomo que monitora tendências nos 4 nichos de conteúdo
e entrega pautas de vídeo diárias via Telegram + arquivo local.

Ciclo: 1x/dia
Output: digest com até 5 pautas rankeadas por potencial viral
Persistência: salva em E:\\Canais\\Ideias Temas\\{data}.md
"""

import logging
import os
import random
from datetime import datetime

from src.core.pipeline import SeekerPipeline
from src.core.utils import parse_llm_json
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel,
)
from src.providers.base import LLMRequest, invoke_with_fallback
from src.skills.viralclip_curator.prompts import (
    NICHES, TREND_SCORE_PROMPT, DIGEST_PROMPT,
)
from config.models import CognitiveRole

log = logging.getLogger("seeker.curator")

# Pasta local pra salvar pautas
LOCAL_OUTPUT_DIR = os.path.join("E:\\", "Canais", "Ideias Temas")


class ViralClipCurator:
    """
    Goal autônomo: curadoria diária de tendências para produção de vídeo.
    Implementa AutonomousGoal protocol.
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._budget = GoalBudget(
            max_per_cycle_usd=0.10,  # Varre 4 nichos, gasta mais que o hunter
            max_daily_usd=0.20,
        )
        self._status = GoalStatus.IDLE

        # Estado persistente
        self._last_trends: dict[str, list[dict]] = {}  # niche → trends
        self._trend_history: list[str] = []  # títulos já sugeridos (dedup)
        self.MAX_HISTORY = 100  # Mantém últimos 100 títulos

    # ── Protocol ──────────────────────────────────────────

    @property
    def name(self) -> str:
        return "viralclip_curator"

    @property
    def interval_seconds(self) -> int:
        return 24 * 3600  # 1x/dia

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
            "last_trends": self._last_trends,
            "trend_history": self._trend_history[-self.MAX_HISTORY:],
        }

    def load_state(self, state: dict) -> None:
        self._last_trends = state.get("last_trends", {})
        self._trend_history = state.get("trend_history", [])
        log.info(
            f"[curator] Estado carregado: {len(self._trend_history)} trends no histórico"
        )

    # ── Core ──────────────────────────────────────────────

    async def run_cycle(self) -> GoalResult:
        """Varre os 4 nichos, pontua trends, monta digest."""
        self._status = GoalStatus.RUNNING
        total_cost = 0.0
        all_trends: list[dict] = []

        for niche_name, niche_config in NICHES.items():
            try:
                trends, cost = await self._search_niche(niche_name, niche_config)
                total_cost += cost

                # Dedup: remove pautas já sugeridas
                new_trends = [
                    t for t in trends
                    if t.get("title", "").lower() not in
                    {h.lower() for h in self._trend_history}
                ]

                for t in new_trends:
                    t["niche"] = niche_name
                    all_trends.append(t)

            except Exception as e:
                log.warning(f"[curator] Falha no nicho {niche_name}: {e}")
                continue

        if not all_trends:
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary="Nenhuma trend nova encontrada hoje",
                cost_usd=total_cost,
            )

        # Ordena por score e pega top 5
        all_trends.sort(key=lambda t: t.get("score", 0), reverse=True)
        top_trends = all_trends[:5]

        # Gera digest
        try:
            digest, digest_cost = await self._generate_digest(top_trends)
            total_cost += digest_cost
        except Exception as e:
            log.warning(f"[curator] Falha ao gerar digest: {e}")
            # Fallback: monta digest simples sem LLM
            digest = self._fallback_digest(top_trends)

        # Salva arquivo local
        self._save_local(top_trends, digest)

        # Atualiza histórico de dedup
        for t in top_trends:
            title = t.get("title", "")
            if title:
                self._trend_history.append(title)
        self._trend_history = self._trend_history[-self.MAX_HISTORY:]

        # Atualiza last_trends por nicho
        for t in top_trends:
            niche = t.get("niche", "unknown")
            if niche not in self._last_trends:
                self._last_trends[niche] = []
            self._last_trends[niche].append(t)
            self._last_trends[niche] = self._last_trends[niche][-10:]

        self._status = GoalStatus.IDLE
        niche_counts = {}
        for t in top_trends:
            n = t.get("niche", "?")
            niche_counts[n] = niche_counts.get(n, 0) + 1

        return GoalResult(
            success=True,
            summary=f"{len(top_trends)} pautas: {niche_counts}",
            notification=digest,
            cost_usd=total_cost,
            data={"trends": top_trends, "niches": niche_counts},
        )

    # ── Busca por nicho ───────────────────────────────────

    async def _search_niche(
        self, niche_name: str, niche_config: dict
    ) -> tuple[list[dict], float]:
        """Busca tendências de um nicho e pontua com LLM."""
        # Sorteia 2 queries do nicho (não faz todas pra economizar)
        from datetime import datetime
        year = str(datetime.now().year)
        raw_queries = random.sample(
            niche_config["search_queries"],
            min(2, len(niche_config["search_queries"])),
        )
        # Injeta ano apenas se a query ainda não o contém
        queries = [
            q if year in q else f"{q} {year}"
            for q in raw_queries
        ]

        all_results = []
        for q in queries:
            try:
                res = await self.pipeline.searcher.search(q, max_results=5)
                if res.results:
                    all_results.extend(res.results)
            except Exception:
                continue

        if not all_results:
            return [], 0.0

        # Deduplica por URL
        seen_urls = set()
        unique_results = []
        for r in all_results:
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                unique_results.append(r)

        contexto = "\n".join(
            f"- [{r.title[:80]}] {r.snippet[:200]} ({r.url})"
            for r in unique_results[:8]
        )

        # Scoring via LLM
        prompt = TREND_SCORE_PROMPT.format(
            niche_name=niche_name,
            niche_description=niche_config["description"],
            search_context=contexto,
        )

        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            system="Curador de conteúdo viral. Responda APENAS JSON.",
            temperature=0.3,
        )

        resp = await invoke_with_fallback(
            CognitiveRole.FAST, req,
            self.pipeline.model_router, self.pipeline.api_keys,
        )

        try:
            data = parse_llm_json(resp.text)
            trends = data.get("trends", [])
            log.info(f"[curator] {niche_name}: {len(trends)} trends encontradas")
            return trends, resp.cost_usd
        except (ValueError, KeyError, AttributeError) as e:
            log.warning(f"[curator] JSON inválido para {niche_name}: {e}")
            return [], resp.cost_usd

    # ── Digest ────────────────────────────────────────────

    async def _generate_digest(
        self, trends: list[dict]
    ) -> tuple[str, float]:
        """Gera digest formatado via LLM."""
        trends_text = "\n".join(
            f"Rank sugerido: #{i+1} | [{t.get('niche', '?')}] {t.get('title', '?')} | "
            f"Score: {t.get('score', 0)} | Hook: {t.get('hook', '')} | "
            f"Formato: {t.get('format', '?')} | Motivo: {t.get('reasoning', '')} | "
            f"Fonte Original: {t.get('source', 'Busca Ativa')}"
            for i, t in enumerate(trends)
        )

        niches_list = ", ".join(sorted({t.get("niche", "?") for t in trends}))

        prompt = DIGEST_PROMPT.format(
            all_trends=trends_text,
            niches_list=niches_list,
            rank="", niche="", title="", score="",
            format="", hook="", reasoning="", source="",
        )

        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            system="Produtor executivo de conteúdo. Formate em HTML Telegram.",
            temperature=0.5,
        )

        resp = await invoke_with_fallback(
            CognitiveRole.SYNTHESIS, req,
            self.pipeline.model_router, self.pipeline.api_keys,
        )

        return resp.text, resp.cost_usd

    def _fallback_digest(self, trends: list[dict]) -> str:
        """Digest simples sem LLM (fallback)."""
        lines = ["<b>🎬 VIRALCLIP CURATOR — DIGEST DIÁRIO</b>\n"]
        for i, t in enumerate(trends, 1):
            lines.append(
                f"<b>#{i} [{t.get('niche', '?')}] {t.get('title', '?')}</b>\n"
                f"Score: {t.get('score', 0)}/100 | {t.get('format', '?')}\n"
                f"🎣 <i>{t.get('hook', '')}</i>\n"
            )
        return "\n".join(lines)

    # ── Arquivo local ─────────────────────────────────────

    def _save_local(self, trends: list[dict], digest: str):
        """Salva pautas em arquivo local markdown."""
        try:
            os.makedirs(LOCAL_OUTPUT_DIR, exist_ok=True)
            date_str = datetime.now().strftime("%Y-%m-%d")
            filepath = os.path.join(LOCAL_OUTPUT_DIR, f"{date_str}_pautas.md")

            lines = [
                f"# ViralClip Curator — Pautas {date_str}\n",
                f"Gerado automaticamente pelo Seeker.Bot\n",
            ]

            for i, t in enumerate(trends, 1):
                lines.append(f"\n## #{i} [{t.get('niche', '?')}] {t.get('title', '?')}\n")
                lines.append(f"- **Score:** {t.get('score', 0)}/100")
                lines.append(f"- **Formato:** {t.get('format', '?')}")
                lines.append(f"- **Hook:** {t.get('hook', '')}")
                lines.append(f"- **Por que funciona:** {t.get('reasoning', '')}")
                lines.append(f"- **Fonte:** {t.get('source', '?')}")

            with open(filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            log.info(f"[curator] Pautas salvas: {filepath}")

        except Exception as e:
            log.error(f"[curator] Falha ao salvar arquivo local: {e}", exc_info=True)
