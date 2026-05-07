import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any

log = logging.getLogger("seeker.metrics.integrity")

@dataclass
class IntegrityMonitor:
    """
    Monitor de Integridade Operacional (Sprint 12/God Mode).
    Rastreia a 'saúde cognitiva' do sistema, focando em alucinações, 
    eficácia de auto-cura e aderência ao orçamento.
    """
    # Hallucination Metrics (via Arbitrage)
    total_arbitrages: int = 0
    total_conflicts: int = 0
    total_consensus_claims: int = 0
    
    # Error & Healing Metrics (via S.A.R.A)
    sara_total_attempts: int = 0
    sara_successful_heals: int = 0
    
    # Financial Integrity
    total_cost_usd: float = 0.0
    budget_limit_usd: float = 50.0  # Limite mensal padrão
    
    start_time: datetime = field(default_factory=datetime.utcnow)

    @property
    def hallucination_index(self) -> float:
        """
        Índice de alucinação em %.
        Calculado como a proporção de zonas de conflito em relação ao total de arbitragens.
        """
        if self.total_arbitrages == 0:
            return 0.0
        return (self.total_conflicts / self.total_arbitrages) * 100

    @property
    def reliability_score(self) -> float:
        """Score de confiabilidade (0-100)"""
        return max(0.0, 100.0 - self.hallucination_index)

    @property
    def healing_efficiency(self) -> float:
        """Eficácia do S.A.R.A em %"""
        if self.sara_total_attempts == 0:
            return 100.0
        return (self.sara_successful_heals / self.sara_total_attempts) * 100

    def record_arbitrage(self, has_conflicts: bool, cost: float):
        """Registra uma operação de arbitragem e seu custo."""
        self.total_arbitrages += 1
        if has_conflicts:
            self.total_conflicts += 1
        self.total_cost_usd += cost

    def record_sara_attempt(self, success: bool):
        """Registra uma tentativa de auto-cura do S.A.R.A."""
        self.sara_total_attempts += 1
        if success:
            self.sara_successful_heals += 1

    def get_integrity_report(self) -> Dict[str, Any]:
        """Retorna relatório completo de integridade."""
        uptime = datetime.utcnow() - self.start_time
        uptime_str = f"{uptime.days}d {uptime.seconds // 3600}h {(uptime.seconds % 3600) // 60}m"
        
        return {
            "uptime": uptime_str,
            "hallucination_index": f"{self.hallucination_index:.2f}%",
            "reliability_score": f"{self.reliability_score:.2f}%",
            "healing_efficiency": f"{self.healing_efficiency:.2f}%",
            "total_cost": f"${self.total_cost_usd:.4f}",
            "budget_used_pct": f"{(self.total_cost_usd / self.budget_limit_usd) * 100:.1f}%",
            "conflicts": self.total_conflicts,
            "arbitrages": self.total_arbitrages,
            "heals": f"{self.sara_successful_heals}/{self.sara_total_attempts}"
        }

    def format_for_telegram(self) -> str:
        """Formata relatório de integridade para exibição no Telegram."""
        report = self.get_integrity_report()
        
        # Determine emoji based on reliability
        rel = float(report["reliability_score"].replace("%", ""))
        emoji = "🛡️" if rel > 95 else ("⚠️" if rel > 85 else "🚨")
        
        lines = [
            f"{emoji} <b>SEEKER INTEGRITY DASHBOARD</b>\n",
            f"⏱️ <b>Uptime:</b> {report['uptime']}\n",
            f"<b>🧠 Saúde Cognitiva:</b>",
            f"  Índice de Alucinação: {report['hallucination_index']}",
            f"  Reliability Score: <b>{report['reliability_score']}</b>",
            f"  Conflitos/Arbitragens: {report['conflicts']}/{report['arbitrages']}\n",
            f"<b>🔧 Auto-Cura (S.A.R.A):</b>",
            f"  Eficácia: {report['healing_efficiency']}",
            f"  Correções: {report['heals']}\n",
            f"<b>💰 Integridade Financeira:</b>",
            f"  Gasto Total: {report['total_cost']}",
            f"  Orçamento Usado: {report['budget_used_pct']} (Limite: ${self.budget_limit_usd})\n",
            f"<i>Status: { 'OPERACIONAL' if rel > 85 else 'DEGRADADO' }</i>"
        ]
        
        return "\n".join(lines)
