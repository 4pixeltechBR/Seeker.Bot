"""
Seeker.Bot — SenseNews Goal
src/skills/sense_news/goal.py

Curadoria diária de notícias dos 4 nichos de conteúdo.
Gera relatório em PDF e envia como anexo no Telegram às 10:00.

Diferente do ViralClip Curator (que sugere pautas de vídeo),
o SenseNews entrega análise e contexto — relatório de pesquisa.
"""

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta

from src.core.pipeline import SeekerPipeline
from src.core.utils import parse_llm_json
from src.providers.base import LLMRequest, invoke_with_fallback
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel,
)
from src.skills.sense_news.prompts import NICHES, ANALYSIS_PROMPT, REPORT_PROMPT
from src.skills.sense_news.pdf_builder import build_sense_news_pdf
from config.models import CognitiveRole

log = logging.getLogger("seeker.sensenews")


class SenseNewsGoal:
    """
    Curadoria diária de notícias — relatório de pesquisa em PDF.
    Horário fixo: 10:00. Mínimo 2 temas por nicho.
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(
            max_per_cycle_usd=0.15,
            max_daily_usd=0.30,
        )

        self.target_hour = 10
        self.target_minute = 0
        self._last_run_date = ""
        self._history: list[str] = []  # títulos já cobertos (dedup)
        self.MAX_HISTORY = 200

    # ── Protocol ──────────────────────────────────────────

    @property
    def name(self) -> str:
        return "sense_news"

    @property
    def interval_seconds(self) -> int:
        now = datetime.now()
        target = now.replace(
            hour=self.target_hour, minute=self.target_minute,
            second=0, microsecond=0,
        )
        if now >= target:
            target += timedelta(days=1)
        wait = (target - now).total_seconds()
        return max(60, min(3600, int(wait)))

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
            "last_run_date": self._last_run_date,
            "history": self._history[-self.MAX_HISTORY:],
        }

    def load_state(self, state: dict) -> None:
        self._last_run_date = state.get("last_run_date", "")
        self._history = state.get("history", [])
        log.info(f"[sensenews] Estado carregado: {len(self._history)} temas no histórico")

    # ── Core ──────────────────────────────────────────────

    async def run_cycle(self) -> GoalResult:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        if self._last_run_date == today_str:
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="SenseNews já executado hoje", cost_usd=0.0)

        target_today = now.replace(
            hour=self.target_hour, minute=self.target_minute,
            second=0, microsecond=0,
        )
        if now < target_today:
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary=f"Aguardando {self.target_hour:02d}:{self.target_minute:02d}",
                cost_usd=0.0,
            )

        self._status = GoalStatus.RUNNING
        total_cost = 0.0
        all_analyses: list[dict] = []
        year = now.year

        # Varre os 4 nichos
        for niche_name, niche_config in NICHES.items():
            try:
                analyses, cost = await self._research_niche(niche_name, niche_config, year)
                total_cost += cost

                # Dedup
                new_analyses = [
                    a for a in analyses
                    if a.get("title", "").lower() not in {h.lower() for h in self._history}
                ]

                # Mínimo 2 por nicho — se tiver menos, loga mas não bloqueia
                if len(new_analyses) < 2:
                    log.warning(
                        f"[sensenews] {niche_name}: apenas {len(new_analyses)} temas novos "
                        f"(mínimo desejado: 2)"
                    )

                for a in new_analyses:
                    a["niche"] = niche_name
                    a["emoji"] = niche_config.get("emoji", "📰")
                    all_analyses.append(a)

            except Exception as e:
                log.warning(f"[sensenews] Falha no nicho {niche_name}: {e}")
                continue

        if not all_analyses:
            self._last_run_date = today_str
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary="Nenhum tema novo encontrado hoje",
                notification="<b>📰 SenseNews</b>\n\n<i>Sem novidades relevantes hoje nos seus nichos.</i>",
                cost_usd=total_cost,
            )

        # Gera relatório consolidado via LLM
        try:
            report_md, report_cost = await self._generate_report(all_analyses)
            total_cost += report_cost
        except Exception as e:
            log.warning(f"[sensenews] Falha ao gerar relatório: {e}")
            report_md = self._fallback_report(all_analyses)

        # Gera PDF
        date_label = now.strftime("%d/%m/%Y")
        pdf_path = build_sense_news_pdf(report_md, all_analyses, date_label)

        # Atualiza histórico
        for a in all_analyses:
            title = a.get("title", "")
            if title:
                self._history.append(title)
        self._history = self._history[-self.MAX_HISTORY:]

        self._last_run_date = today_str
        self._status = GoalStatus.IDLE

        # Notificação com path do PDF (scheduler envia o arquivo)
        niche_counts = {}
        for a in all_analyses:
            n = a.get("niche", "?")
            niche_counts[n] = niche_counts.get(n, 0) + 1

        notification = (
            f"<b>📰 SenseNews — {date_label}</b>\n\n"
            f"<b>{len(all_analyses)} temas</b> nos seus nichos:\n"
        )
        for niche, count in niche_counts.items():
            emoji = NICHES.get(niche, {}).get("emoji", "📰")
            notification += f"  {emoji} {niche}: {count} temas\n"
        notification += f"\n<i>Relatório PDF em anexo.</i>"

        return GoalResult(
            success=True,
            summary=f"SenseNews: {len(all_analyses)} temas, PDF gerado",
            notification=notification,
            cost_usd=total_cost,
            data={"pdf_path": pdf_path, "analyses": len(all_analyses)},
        )

    # ── Pesquisa por nicho ────────────────────────────────

    async def _research_niche(
        self, niche_name: str, niche_config: dict, year: int
    ) -> tuple[list[dict], float]:
        """Busca e analisa notícias de um nicho."""
        year_str = str(year)
        raw_queries = random.sample(
            niche_config["search_queries"],
            min(3, len(niche_config["search_queries"])),
        )
        # Injeta ano apenas se a query ainda não o contém
        queries = [
            q if year_str in q else f"{q} {year}"
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
        seen = set()
        unique = []
        for r in all_results:
            if r.url not in seen:
                seen.add(r.url)
                unique.append(r)

        contexto = "\n".join(
            f"- [{r.title[:80]}] {r.snippet[:250]} ({r.url})"
            for r in unique[:10]
        )

        prompt = ANALYSIS_PROMPT.format(
            niche_name=niche_name,
            niche_description=niche_config["description"],
            niche_objective=niche_config["objective"],
            search_context=contexto,
            year=year,
        )

        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            system="Analista de inteligência. Responda APENAS JSON.",
            temperature=0.2,
        )

        resp = await invoke_with_fallback(
            CognitiveRole.FAST, req,
            self.pipeline.model_router, self.pipeline.api_keys,
        )

        try:
            data = parse_llm_json(resp.text)
            analyses = data.get("analyses", [])
            log.info(f"[sensenews] {niche_name}: {len(analyses)} temas analisados")
            return analyses, resp.cost_usd
        except (ValueError, KeyError, AttributeError) as e:
            log.warning(f"[sensenews] JSON inválido para {niche_name}: {e}")
            return [], resp.cost_usd

    # ── Relatório ─────────────────────────────────────────

    async def _generate_report(
        self, analyses: list[dict]
    ) -> tuple[str, float]:
        """Gera relatório markdown consolidado via LLM."""
        analyses_text = "\n".join(
            f"[{a.get('niche', '?')}] {a.get('title', '?')}\n"
            f"  Análise: {a.get('analysis', '')}\n"
            f"  Impacto: {a.get('impact', '')}\n"
            f"  Fonte: {a.get('source', '')}"
            for a in analyses
        )

        prompt = REPORT_PROMPT.format(
            analyses_text=analyses_text,
            total=len(analyses),
            date=datetime.now().strftime("%d/%m/%Y"),
        )

        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            system="Redator de relatórios de inteligência. Output em Markdown puro.",
            temperature=0.4,
            max_tokens=2000,
        )

        resp = await invoke_with_fallback(
            CognitiveRole.SYNTHESIS, req,
            self.pipeline.model_router, self.pipeline.api_keys,
        )

        return resp.text, resp.cost_usd

    def _fallback_report(self, analyses: list[dict]) -> str:
        """Relatório simples sem LLM."""
        lines = [f"# SenseNews — {datetime.now().strftime('%d/%m/%Y')}\n"]
        for a in analyses:
            lines.append(f"## [{a.get('niche', '?')}] {a.get('title', '?')}\n")
            lines.append(f"{a.get('analysis', 'Sem análise')}\n")
            lines.append(f"**Impacto:** {a.get('impact', '?')}\n")
            lines.append(f"**Fonte:** {a.get('source', '?')}\n")
        return "\n".join(lines)


def create_goal(pipeline) -> SenseNewsGoal:
    """Factory chamada pelo Goal Registry."""
    return SenseNewsGoal(pipeline)
