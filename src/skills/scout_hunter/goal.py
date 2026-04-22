"""
Scout Hunter — B2B Lead Generation Skill for Seeker.Bot

Autonomous goal that runs B2B prospection campaigns with intelligent scraping,
enrichment, qualification, and copywriting.

Usage:
    goal = ScoutHunter(pipeline)
    result = await goal.run_cycle()
"""

import asyncio
import logging
import random

from src.core.pipeline import SeekerPipeline
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel,
)
from src.skills.scout_hunter.scout import ScoutEngine
from src.core.metrics.scout_hunter_metrics import ScoutHunterMetrics, ScoutHunterMetricsComputer

log = logging.getLogger("seeker.scout_hunter_goal")

# Configuration
TARGET_REGIONS = [
    "Goiânia", "Brasília", "Anápolis", "Aparecida de Goiás",
    "São Paulo", "Rio de Janeiro", "Belo Horizonte", "Salvador",
]

TARGET_NICHES = [
    "eventos", "casamento", "corporativo", "agro", "shows", "conferências",
]

class ScoutHunter(AutonomousGoal):
    """
    Autonomous B2B lead generation goal.
    Combines intelligent prospecting across 6 sources with AI-powered enrichment and copy.

    Budget per cycle: $0.15 USD
    Interval: Every 4 hours
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self.scout = None

        self._budget = GoalBudget(
            max_per_cycle_usd=0.15,
            max_daily_usd=0.60,
        )

        self._status = GoalStatus.IDLE
        self._campaign_cache = {}

    @property
    def name(self) -> str:
        return "scout_hunter"

    @property
    def interval_seconds(self) -> int:
        return 14400  # 4 hours

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.BOTH]  # Telegram + Console

    def get_status(self) -> GoalStatus:
        return self._status

    # ──────────────────────────────────────────────────────────
    # Main Cycle
    # ──────────────────────────────────────────────────────────

    async def run_cycle(self) -> GoalResult:
        """Execute one cycle of B2B lead generation."""
        self._status = GoalStatus.RUNNING
        cycle_cost = 0.0
        cycle_data = {}

        try:
            # Initialize Scout if needed
            if not self.scout:
                self.scout = ScoutEngine(
                    memory_store=self.pipeline.memory,
                    cascade_adapter=self.pipeline.cascade_adapter,
                    model_router=self.pipeline.model_router,
                    api_keys=self.pipeline.api_keys,
                )
                await self.scout.init()

            # Pick random target
            region = random.choice(TARGET_REGIONS)
            niche = random.choice(TARGET_NICHES)

            log.info(f"[scout_hunter] Starting campaign for {niche} in {region}")

            # Phase 1: Scrape
            scrape_result = await self.scout.scrape_campaign(
                region=region,
                niche=niche,
                limit=50,
            )

            if scrape_result["total_saved"] == 0:
                self._status = GoalStatus.IDLE
                return GoalResult(
                    success=True,
                    summary=f"No leads found for {niche} in {region}",
                    cost_usd=0.0,
                )

            campaign_id = scrape_result["campaign_id"]
            cycle_data["campaign_id"] = campaign_id
            cycle_data["sources"] = scrape_result["sources"]
            cycle_data["total_scraped"] = scrape_result["total_saved"]

            log.info(f"[scout_hunter] Scraped {scrape_result['total_saved']} leads")

            # Phase 2: Full Pipeline (Enrich + Qualify + Copy)
            pipeline_result = await self.scout.run_full_pipeline(campaign_id, limit=30)

            if pipeline_result.get("results"):
                results = pipeline_result["results"]
                cycle_data["qualified"] = results.get("qualified", 0)
                cycle_data["written"] = results.get("written", 0)
                cycle_data["rejected"] = results.get("rejected", 0)

                log.info(
                    f"[scout_hunter] Pipeline: "
                    f"Qualified={results['qualified']}, "
                    f"Written={results['written']}, "
                    f"Rejected={results['rejected']}"
                )

                # Phase 3: Get Dashboard
                dashboard = await self.scout.get_campaign_dashboard(campaign_id)

                # Build notification
                if results["qualified"] > 0:
                    notification = self._build_notification(
                        campaign_id, region, niche, results, dashboard
                    )

                    self._status = GoalStatus.IDLE
                    return GoalResult(
                        success=True,
                        summary=f"{results['qualified']} qualified leads identified",
                        notification=notification,
                        cost_usd=cycle_cost,
                        data=cycle_data,
                    )

        except Exception as e:
            log.error(f"[scout_hunter] Cycle failed: {e}", exc_info=True)
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=False,
                summary=f"Campaign failed: {str(e)[:100]}",
                cost_usd=cycle_cost,
            )

        self._status = GoalStatus.IDLE
        return GoalResult(
            success=True,
            summary="Campaign complete with no qualified leads",
            cost_usd=cycle_cost,
            data=cycle_data,
        )

    def _build_notification(
        self,
        campaign_id: str,
        region: str,
        niche: str,
        results: dict,
        dashboard: dict,
    ) -> str:
        """Build Telegram notification with Scout Hunter 2.0 metrics."""
        # Compute Scout Hunter 2.0 metrics
        campaign_data = {
            "total_raw": results.get("total_scraped", 0),
            "enriched": results.get("enriched", 0),
            "total_unique": results.get("total_unique", results.get("qualified", 1)),
            "filtered_out": results.get("filtered_out", 0),
            "accounts_researched": results.get("accounts_researched", 0),
            "cache_hits": results.get("cache_hits", 0),
            "decision_makers": results.get("decision_makers", 0),
            "qualified": results.get("qualified", 0),
            "avg_bant_score": results.get("avg_bant_score", 75.0),
            "high_priority": results.get("high_priority", 0),
            "copy_generated": results.get("written", 0),
            "total_cost": results.get("total_cost", 0.0),
            "avg_latency_ms": results.get("avg_latency_ms", 0.0),
        }

        metrics = ScoutHunterMetricsComputer.compute_from_db(campaign_data)

        header = f"<b>🎯 SCOUT HUNTER 2.0</b>\n"
        header += f"📍 <b>{region.upper()}</b> | 🏷️ <b>{niche.upper()}</b>\n\n"

        # Phase-by-phase breakdown
        phases = f"<b>📊 FUNIL DE VENDAS:</b>\n"
        phases += f"🔹 <b>Fase 1 (Scrape):</b> {metrics.leads_scraped} leads encontrados\n"
        phases += f"🔹 <b>Fase 2 (Enrich):</b> {metrics.leads_enriched} enriquecidos ({metrics.enrichment_rate:.0%})\n"
        phases += f"🔹 <b>Fase 3 (Fit):</b> {metrics.leads_evaluated_discovery_matrix} avaliados (Média: {metrics.avg_fit_score:.0f}/100)\n"
        phases += f"🔹 <b>Fase 4 (Research):</b> {metrics.accounts_researched} empresas analisadas\n"
        phases += f"🔹 <b>Fase 5 (BANT):</b> {metrics.leads_qualified_bant} qualificados\n\n"

        quality = f"<b>⭐ QUALIDADE & LEADS:</b>\n"
        quality += f"✅ <b>High Priority:</b> {metrics.high_priority_leads} leads\n"
        quality += f"📈 <b>Taxa Conversão:</b> {metrics.qualification_rate:.1%}\n"
        quality += f"👤 <b>Decisores:</b> {metrics.decision_makers_found_total} encontrados\n"

        footer = f"\n<b>💰 INVESTIMENTO:</b> ${metrics.total_cost_usd:.3f} USD\n"
        footer += f"<b>🆔 ID:</b> <code>{campaign_id[:12]}</code>\n\n"
        footer += f"👉 <i>Use /scout-leads {campaign_id} para ver a lista.</i>"

        return header + phases + quality + footer

    # ──────────────────────────────────────────────────────────
    # State Management
    # ──────────────────────────────────────────────────────────

    def serialize_state(self) -> dict:
        """Serialize goal state."""
        return {
            "campaign_cache": self._campaign_cache,
        }

    def load_state(self, state: dict) -> None:
        """Load goal state."""
        self._campaign_cache = state.get("campaign_cache", {})
        log.info(f"[scout_hunter] State loaded: {len(self._campaign_cache)} campaigns")


def create_goal(pipeline: SeekerPipeline) -> AutonomousGoal:
    """Factory function for skill registration."""
    return ScoutHunter(pipeline)
