import asyncio
import logging
import random

from src.core.pipeline import SeekerPipeline
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel,
)
from src.skills.seeker_sales.scout import ScoutEngine
from src.skills.seeker_sales.miner import RevenueMiner
from src.core.metrics.scout_hunter_metrics import ScoutHunterMetricsComputer

# Seeker Sales B2B targets
B2B_REGIONS = [
    "Goiânia", "Brasília", "Anápolis", "Aparecida de Goiás",
    "São Paulo", "Rio de Janeiro", "Belo Horizonte", "Salvador",
]

B2B_NICHES = [
    "eventos", "casamento", "corporativo", "agro", "shows", "conferências",
]

log = logging.getLogger("seeker.seeker_sales")

class SeekerSalesGoal(AutonomousGoal):
    """
    Agentic BDR Unificado (Seeker Sales).
    Alterna estrategicamente entre prospectar Eventos (Trigger temporais) 
    e B2B Corporativo (Scout) baseado em budget e cooldowns.
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline

        self._budget = GoalBudget(
            max_per_cycle_usd=0.25,
            max_daily_usd=1.50,
        )

        self._status = GoalStatus.IDLE
        
        # Motores
        self.event_miner = RevenueMiner(pipeline)
        self.b2b_scout = None

    @property
    def name(self) -> str:
        return "seeker_sales"

    @property
    def interval_seconds(self) -> int:
        return 7200  # A cada 2 horas

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    async def run_cycle(self) -> GoalResult:
        self._status = GoalStatus.RUNNING
        
        # Decide between B2B and Events based on random (or logic later)
        # We can alternate 50/50 for now
        mode = random.choice(["B2B", "EVENT"])
        log.info(f"[seeker_sales] Iniciando ciclo unificado no modo: {mode}")
        
        try:
            if mode == "EVENT":
                result = await self.event_miner.run_cycle()
                self._status = GoalStatus.IDLE
                return result
            else:
                result = await self._run_b2b_cycle()
                self._status = GoalStatus.IDLE
                return result
        except Exception as e:
            log.error(f"[seeker_sales] Erro no ciclo {mode}: {e}", exc_info=True)
            self._status = GoalStatus.IDLE
            return GoalResult(success=False, summary=f"Erro no Seeker Sales: {e}", cost_usd=0.0)

    async def _run_b2b_cycle(self) -> GoalResult:
        cycle_cost = 0.0
        cycle_data = {}

        if not self.b2b_scout:
            self.b2b_scout = ScoutEngine(
                memory_store=self.pipeline.memory,
                cascade_adapter=self.pipeline.cascade_adapter,
                model_router=self.pipeline.model_router,
                api_keys=self.pipeline.api_keys,
            )
            await self.b2b_scout.init()

        region = random.choice(B2B_REGIONS)
        niche = random.choice(B2B_NICHES)

        log.info(f"[seeker_sales] Iniciando campanha B2B para {niche} em {region}")

        # Phase 1: Scrape
        scrape_result = await self.b2b_scout.scrape_campaign(
            region=region,
            niche=niche,
            limit=50,
        )

        if scrape_result["total_saved"] == 0:
            return GoalResult(
                success=True,
                summary=f"Sem leads B2B encontrados para {niche} em {region}",
                cost_usd=0.0,
            )

        campaign_id = scrape_result["campaign_id"]
        cycle_data["campaign_id"] = campaign_id
        cycle_data["sources"] = scrape_result["sources"]
        cycle_data["total_scraped"] = scrape_result["total_saved"]

        log.info(f"[seeker_sales] Prospectados {scrape_result['total_saved']} leads (B2B)")

        # Phase 2: Full Pipeline (Enrich + Qualify + Copy)
        pipeline_result = await self.b2b_scout.run_full_pipeline(campaign_id, limit=30)

        if pipeline_result.get("results"):
            results = pipeline_result["results"]
            cycle_data["qualified"] = results.get("qualified", 0)
            cycle_data["written"] = results.get("written", 0)
            cycle_data["rejected"] = results.get("rejected", 0)

            # Phase 3: Dashboard
            dashboard = await self.b2b_scout.get_campaign_dashboard(campaign_id)

            if results["qualified"] > 0:
                notification = self._build_scout_notification(
                    campaign_id, region, niche, results, dashboard
                )

                return GoalResult(
                    success=True,
                    summary=f"{results['qualified']} leads B2B qualificados",
                    notification=notification,
                    cost_usd=cycle_cost,
                    data=cycle_data,
                )

        return GoalResult(
            success=True,
            summary="Campanha B2B concluída sem leads ultra qualificados",
            cost_usd=cycle_cost,
            data=cycle_data,
        )

    def _build_scout_notification(self, campaign_id: str, region: str, niche: str, results: dict, dashboard: dict) -> str:
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

        header = f"<b>🎯 SEEKER SALES (B2B)</b>\\n"
        header += f"📍 <b>{region.upper()}</b> | 🏷️ <b>{niche.upper()}</b>\\n\\n"

        phases = f"<b>📊 FUNIL DE VENDAS:</b>\\n"
        phases += f"🔹 <b>Prospectados:</b> {metrics.leads_scraped} leads\\n"
        phases += f"🔹 <b>Enriquecidos:</b> {metrics.leads_enriched} ({metrics.enrichment_rate:.0%})\\n"
        phases += f"🔹 <b>Fit Avaliado:</b> {metrics.leads_evaluated_discovery_matrix} (Média: {metrics.avg_fit_score:.0f}/100)\\n"
        phases += f"🔹 <b>Research (Deep):</b> {metrics.accounts_researched} empresas\\n"
        phases += f"🔹 <b>BANT (Qualificados):</b> {metrics.leads_qualified_bant}\\n\\n"

        quality = f"<b>⭐ QUALIDADE:</b>\\n"
        quality += f"✅ <b>Alta Prioridade:</b> {metrics.high_priority_leads}\\n"
        quality += f"📈 <b>Conversão:</b> {metrics.qualification_rate:.1%}\\n"
        quality += f"👤 <b>Decisores Mapeados:</b> {metrics.decision_makers_found_total}\\n"

        footer = f"\\n<b>💰 CUSTO:</b> ${metrics.total_cost_usd:.3f} USD\\n"
        footer += f"<b>🆔 ID:</b> <code>{campaign_id[:12]}</code>\\n\\n"
        footer += f"👉 <i>Use /scout-leads {campaign_id} para ver a lista.</i>"

        return header + phases + quality + footer

    def serialize_state(self) -> dict:
        return {
            "event_miner_state": self.event_miner.serialize_state()
        }

    def load_state(self, state: dict) -> None:
        if "event_miner_state" in state:
            self.event_miner.load_state(state["event_miner_state"])

def create_goal(pipeline: SeekerPipeline) -> AutonomousGoal:
    return SeekerSalesGoal(pipeline)
