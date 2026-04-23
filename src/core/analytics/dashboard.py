"""
Dashboard Financeiro
Agregação de métricas de custo, uso e performance
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict

log = logging.getLogger("seeker.analytics.dashboard")


@dataclass
class MetricasDashboard:
    """Métricas agregadas para o dashboard"""
    timestamp: datetime

    # Custos
    custo_total_hoje: float
    custo_total_mes: float
    custo_total_ano: float

    # Provedores
    provedores_ativos: int
    provider_mais_caro: Optional[str]
    provider_mais_usado: Optional[str]
    custo_por_provider: Dict[str, float]

    # Performance
    latencia_media_ms: float
    taxa_sucesso_geral: float

    # Tendências
    custo_medio_diario_7d: float
    custo_medio_diario_30d: float
    tendencia_custos: str  # "crescente", "estavel", "decrescente"

    # Limites
    percentual_limite_diario: float
    percentual_limite_mensal: float
    dias_ate_alerta: Optional[int]


class DashboardFinanceiro:
    """
    Agregador central de métricas financeiras
    Combina dados de cost_tracker, profiler e dados históricos
    """

    def __init__(self, cost_tracker=None, profiler=None):
        self.cost_tracker = cost_tracker
        self.profiler = profiler
        self._cache_metricas: Optional[MetricasDashboard] = None
        self._timestamp_cache = None

        log.info("[dashboard] Dashboard Financeiro inicializado")

    async def obter_metricas(self, usar_cache: bool = True) -> MetricasDashboard:
        """Obtém métricas agregadas do dashboard"""
        agora = datetime.utcnow()

        # Usar cache se válido (máx 1 minuto)
        if (
            usar_cache
            and self._cache_metricas
            and self._timestamp_cache
            and (agora - self._timestamp_cache).total_seconds() < 60
        ):
            return self._cache_metricas

        # Obter dados do cost_tracker
        resumo_diario = self.cost_tracker.obter_resumo_diario()
        resumo_mensal = self.cost_tracker.obter_resumo_mensal()
        gastos_7d = self.cost_tracker.obter_gastos_diarios(dias=7)

        # Calcular custo médio diário
        custos_7d = [v for v in gastos_7d.values()]
        custo_medio_7d = sum(custos_7d) / len(custos_7d) if custos_7d else 0.0

        gastos_30d = self.cost_tracker.obter_gastos_diarios(dias=30)
        custos_30d = [v for v in gastos_30d.values()]
        custo_medio_30d = sum(custos_30d) / len(custos_30d) if custos_30d else 0.0

        # Obter estatísticas de performance
        stats_profiler = self.profiler.get_all_stats() if self.profiler else {}

        latencia_media = 0.0
        taxa_sucesso = 0.0
        if stats_profiler:
            latencias = [
                v.get("latencia_media_ms", 0)
                for v in stats_profiler.get("goals", {}).values()
            ]
            latencia_media = sum(latencias) / len(latencias) if latencias else 0.0

            sucesso_count = sum(
                1 for v in stats_profiler.get("goals", {}).values()
                if v.get("sucesso_rate", 0) > 0
            )
            taxa_sucesso = (
                (sucesso_count / len(stats_profiler.get("goals", {}))) * 100
                if stats_profiler.get("goals")
                else 0.0
            )

        # Analisar tendência
        if len(custos_7d) >= 2:
            primeira_metade = sum(custos_7d[:len(custos_7d)//2])
            segunda_metade = sum(custos_7d[len(custos_7d)//2:])
            if segunda_metade > primeira_metade * 1.1:
                tendencia = "crescente"
            elif segunda_metade < primeira_metade * 0.9:
                tendencia = "decrescente"
            else:
                tendencia = "estavel"
        else:
            tendencia = "estavel"

        # Calcular dias até alerta
        custo_diario = resumo_diario["custo_total"]
        limite_diario = self.cost_tracker.limite_diario_usd
        dias_ate_alerta = None
        if custo_diario > 0:
            dias_ate_alerta = max(1, int(limite_diario / custo_diario))

        # Obter custo do ano
        agora = datetime.utcnow()
        ano_chave = agora.strftime("%Y")
        custo_ano = sum(
            v for k, v in self.cost_tracker._gastos_mensais.items()
            if k.startswith(ano_chave)
        )

        metricas = MetricasDashboard(
            timestamp=agora,
            custo_total_hoje=resumo_diario["custo_total"],
            custo_total_mes=resumo_mensal["custo_total"],
            custo_total_ano=custo_ano,
            provedores_ativos=len(resumo_diario["provedores"]),
            provider_mais_caro=max(
                resumo_diario["provedores"].items(),
                key=lambda x: x[1],
                default=(None, 0)
            )[0],
            provider_mais_usado=None,  # Calculado do profiler
            custo_por_provider=resumo_diario["provedores"],
            latencia_media_ms=latencia_media,
            taxa_sucesso_geral=taxa_sucesso,
            custo_medio_diario_7d=custo_medio_7d,
            custo_medio_diario_30d=custo_medio_30d,
            tendencia_custos=tendencia,
            percentual_limite_diario=resumo_diario["porcentagem_limite"],
            percentual_limite_mensal=resumo_mensal["porcentagem_limite"],
            dias_ate_alerta=dias_ate_alerta,
        )

        # Atualizar cache
        self._cache_metricas = metricas
        self._timestamp_cache = agora

        return metricas

    async def obter_resumo_executivo(self) -> dict:
        """Resumo executivo em 4-5 linhas"""
        metricas = await self.obter_metricas()

        return {
            "status": self._calcular_status(metricas),
            "custo_hoje": f"${metricas.custo_total_hoje:.2f}",
            "limite_diario": f"{metricas.percentual_limite_diario:.0f}%",
            "tendencia": metricas.tendencia_custos,
            "provedores_ativos": metricas.provedores_ativos,
            "saude": self._calcular_saude(metricas),
        }

    def _calcular_status(self, metricas: MetricasDashboard) -> str:
        """Calcula status geral"""
        if metricas.percentual_limite_diario > 100:
            return "CRITICO"
        elif metricas.percentual_limite_diario > 80:
            return "ALERTA"
        elif metricas.percentual_limite_mensal > 80:
            return "CUIDADO"
        else:
            return "OK"

    def _calcular_saude(self, metricas: MetricasDashboard) -> str:
        """Calcula saúde geral do sistema"""
        score = 0

        if metricas.taxa_sucesso_geral >= 95:
            score += 40
        elif metricas.taxa_sucesso_geral >= 90:
            score += 30
        else:
            score += 20

        if metricas.percentual_limite_diario <= 50:
            score += 30
        elif metricas.percentual_limite_diario <= 80:
            score += 20
        else:
            score += 10

        if metricas.tendencia_custos == "decrescente":
            score += 30
        elif metricas.tendencia_custos == "estavel":
            score += 20
        else:
            score += 10

        if score >= 90:
            return "EXCELENTE"
        elif score >= 70:
            return "BOA"
        elif score >= 50:
            return "ACEITAVEL"
        else:
            return "RUIM"

    async def obter_detalhes_provedores(self) -> dict:
        """Detalha custos por provedor"""
        metricas = await self.obter_metricas()

        detalhes = {}
        for provider, custo in metricas.custo_por_provider.items():
            stats = self.cost_tracker.obter_estatisticas_provedor(provider)
            if stats:
                detalhes[provider] = {
                    "custo_hoje": custo,
                    "custo_medio": stats.get("custo_medio", 0),
                    "chamadas": stats.get("total_chamadas", 0),
                    "taxa_sucesso": stats.get("taxa_sucesso", 0),
                    "modelo_mais_caro": stats.get("modelo_mais_caro"),
                }

        return detalhes

    async def obter_alertas_ativos(self) -> List[dict]:
        """Retorna alertas ativos"""
        metricas = await self.obter_metricas()
        alertas = []

        if metricas.percentual_limite_diario > 100:
            alertas.append({
                "tipo": "CRITICO",
                "mensagem": f"Limite diário excedido em {metricas.percentual_limite_diario - 100:.0f}%",
                "acao": "Reduzir uso ou aumentar limite",
            })

        if metricas.percentual_limite_mensal > 90:
            alertas.append({
                "tipo": "ALERTA",
                "mensagem": f"Limite mensal em {metricas.percentual_limite_mensal:.0f}%",
                "acao": "Monitorar closely",
            })

        if metricas.tendencia_custos == "crescente":
            alertas.append({
                "tipo": "INFO",
                "mensagem": "Custos em tendência crescente",
                "acao": "Investigar aumento",
            })

        if metricas.taxa_sucesso_geral < 90:
            alertas.append({
                "tipo": "AVISO",
                "mensagem": f"Taxa de sucesso baixa: {metricas.taxa_sucesso_geral:.1f}%",
                "acao": "Revisar erros",
            })

        return alertas
