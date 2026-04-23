"""Scout Hunter 2.0 — Métricas e Dashboard (Track C4)"""
from dataclasses import dataclass
import logging

log = logging.getLogger("scout_hunter.metrics")

@dataclass
class ScoutHunterMetrics:
    """Agregação de métricas para uma campanha Scout Hunter"""
    
    # Phase 1: Scraping
    leads_scraped: int = 0
    
    # Phase 2: Enrichment
    leads_enriched: int = 0
    enrichment_rate: float = 0.0
    
    # Phase 2.5: Discovery Matrix
    leads_evaluated_discovery_matrix: int = 0
    avg_fit_score: float = 0.0
    avg_intent_signals: float = 0.0
    discovery_matrix_filters_out: int = 0
    discovery_matrix_pass_rate: float = 0.0
    
    # Phase 2.75: Account Research
    accounts_researched: int = 0
    account_research_cache_hits: int = 0
    decision_makers_found_total: int = 0
    
    # Phase 3: Qualification
    leads_qualified_bant: int = 0
    avg_bant_score: float = 0.0
    high_priority_leads: int = 0
    copy_generated: int = 0
    
    # Totals
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    qualification_rate: float = 0.0

class ScoutHunterMetricsComputer:
    """Computa métricas da campanha Scout Hunter"""

    @staticmethod
    def compute_from_db(campaign_results: dict) -> ScoutHunterMetrics:
        """Computa métricas a partir de resultados de campanha"""
        total_leads = campaign_results.get("total_unique", 1)
        qualified = campaign_results.get("qualified", 0)
        filtered_out = campaign_results.get("filtered_out", 0)

        # Discovery Matrix pass rate: (leads_evaluated - filtered_out) / leads_evaluated
        dm_pass_rate = ((total_leads - filtered_out) / total_leads) if total_leads > 0 else 0.0

        metrics = ScoutHunterMetrics(
            leads_scraped=campaign_results.get("total_raw", 0),
            leads_enriched=campaign_results.get("enriched", 0),
            enrichment_rate=(campaign_results.get("enriched", 0) / total_leads) if total_leads > 0 else 0.0,
            leads_evaluated_discovery_matrix=total_leads,
            avg_fit_score=campaign_results.get("avg_fit_score", 65.0),
            discovery_matrix_filters_out=filtered_out,
            discovery_matrix_pass_rate=dm_pass_rate,
            accounts_researched=campaign_results.get("accounts_researched", 0),
            account_research_cache_hits=campaign_results.get("cache_hits", 0),
            decision_makers_found_total=campaign_results.get("decision_makers", 0),
            leads_qualified_bant=qualified,
            avg_bant_score=campaign_results.get("avg_bant_score", 75.0),
            high_priority_leads=campaign_results.get("high_priority", 0),
            copy_generated=campaign_results.get("copy_generated", 0),
            total_cost_usd=campaign_results.get("total_cost", 0.0),
            avg_latency_ms=campaign_results.get("avg_latency_ms", 0.0),
            qualification_rate=(qualified / total_leads) if total_leads > 0 else 0.0,
        )

        return metrics

    @staticmethod
    def format_telegram_report(metrics: ScoutHunterMetrics) -> str:
        """Formata métricas para notificação Telegram"""
        return f"""🎯 SCOUT HUNTER 2.0 — CAMPANHA COMPLETA

📊 PIPELINE COMPLETO:
🔹 Scraped: {metrics.leads_scraped} leads
🔹 Enriched: {metrics.leads_enriched} ({metrics.enrichment_rate:.0%})
🔹 Discovery Matrix: {metrics.leads_evaluated_discovery_matrix}
  ├─ Avg Fit Score: {metrics.avg_fit_score:.1f}/100
  └─ Filtered out: {metrics.discovery_matrix_filters_out}
🔹 Accounts researched: {metrics.accounts_researched}
  ├─ Cache hits: {metrics.account_research_cache_hits}
  └─ Decision makers: {metrics.decision_makers_found_total}
🔹 Qualified (BANT >= 70): {metrics.leads_qualified_bant} 👤
🔹 Copy generated: {metrics.copy_generated} 📝

📈 QUALITY METRICS:
✓ Avg BANT Score: {metrics.avg_bant_score:.1f}/100
✓ High Priority: {metrics.high_priority_leads} leads
✓ Qualification Rate: {metrics.qualification_rate:.1%}
✓ Total Cost: ${metrics.total_cost_usd:.2f}
"""
