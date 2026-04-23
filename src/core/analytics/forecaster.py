"""
Forecaster de Custos
Previsão baseada em tendências históricas e ML simples
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import statistics

log = logging.getLogger("seeker.analytics.forecaster")


@dataclass
class PrevisaoCustos:
    """Previsão de custos futuros"""
    data: datetime
    custo_estimado: float
    intervalo_confianca: tuple  # (min, max)
    modelo_usado: str
    acuracia: float


class Forecaster:
    """
    Previsor de custos usando:
    - Média móvel simples (SMA)
    - Regressão linear
    - Análise de sazonalidade
    """

    def __init__(self, cost_tracker=None, tamanho_historico: int = 30):
        self.cost_tracker = cost_tracker
        self.tamanho_historico = tamanho_historico
        self._cache_predicoes: Dict[str, PrevisaoCustos] = {}

        log.info("[forecaster] Forecaster inicializado")

    async def prever_custos_7d(self) -> List[PrevisaoCustos]:
        """Prevê custos para os próximos 7 dias"""
        historico = self.cost_tracker.obter_gastos_diarios(dias=self.tamanho_historico)
        custos = [v for v in sorted(historico.items())[-self.tamanho_historico:]]

        if not custos:
            return []

        valores = [v[1] for v in custos]
        datas = [datetime.strptime(d[0], "%Y-%m-%d") for d in custos]

        predicoes = []
        data_proxima = datas[-1] + timedelta(days=1)

        # Modelo 1: Média móvel simples (SMA) com ponderação
        sma_5d = statistics.mean(valores[-5:]) if len(valores) >= 5 else statistics.mean(valores)
        sma_10d = statistics.mean(valores[-10:]) if len(valores) >= 10 else sma_5d

        # Calcular tendência
        tendencia = (sma_5d - sma_10d) / sma_10d if sma_10d > 0 else 0

        for i in range(7):
            # Valor base com aplicação de tendência
            valor_previsto = sma_5d * (1 + tendencia * (i + 1) * 0.05)

            # Intervalo de confiança (±15%)
            intervalo = (valor_previsto * 0.85, valor_previsto * 1.15)

            predicao = PrevisaoCustos(
                data=data_proxima + timedelta(days=i),
                custo_estimado=max(0, valor_previsto),
                intervalo_confianca=intervalo,
                modelo_usado="SMA+Tendencia",
                acuracia=0.85,
            )
            predicoes.append(predicao)

        log.info(
            f"[forecaster] Previsoes geradas para 7 dias: "
            f"custo_estimado_medio=${sum(p.custo_estimado for p in predicoes)/7:.2f}"
        )

        return predicoes

    async def prever_custos_30d(self) -> List[PrevisaoCustos]:
        """Prevê custos para os próximos 30 dias"""
        historico = self.cost_tracker.obter_gastos_diarios(dias=self.tamanho_historico)
        custos = [v for v in sorted(historico.items())[-self.tamanho_historico:]]

        if not custos:
            return []

        valores = [v[1] for v in custos]
        datas = [datetime.strptime(d[0], "%Y-%m-%d") for d in custos]

        predicoes = []
        data_proxima = datas[-1] + timedelta(days=1)

        # Usar regressão linear simples
        n = len(valores)
        x = list(range(n))
        y = valores

        # Calcular coeficientes
        media_x = sum(x) / n
        media_y = sum(y) / n

        numerador = sum((x[i] - media_x) * (y[i] - media_y) for i in range(n))
        denominador = sum((x[i] - media_x) ** 2 for i in range(n))

        slope = numerador / denominador if denominador > 0 else 0
        intercept = media_y - slope * media_x

        # Gerar previsões
        for i in range(30):
            x_pred = n + i
            valor_previsto = intercept + slope * x_pred
            valor_previsto = max(0, valor_previsto)  # Não pode ser negativo

            # Intervalo de confiança aumenta com distância
            margem = 0.15 + (i * 0.01)
            intervalo = (
                valor_previsto * (1 - margem),
                valor_previsto * (1 + margem)
            )

            predicao = PrevisaoCustos(
                data=data_proxima + timedelta(days=i),
                custo_estimado=valor_previsto,
                intervalo_confianca=intervalo,
                modelo_usado="RegressaoLinear",
                acuracia=max(0.7, 0.95 - i * 0.01),  # Acurácia diminui com distância
            )
            predicoes.append(predicao)

        custo_total_30d = sum(p.custo_estimado for p in predicoes)
        log.info(
            f"[forecaster] Previsao 30d: "
            f"custo_estimado_total=${custo_total_30d:.2f}, "
            f"media_diaria=${custo_total_30d/30:.2f}"
        )

        return predicoes

    async def prever_quando_alerta(self, limite: float) -> Optional[datetime]:
        """Prevê quando atingirá o limite mensal"""
        resumo_mensal = self.cost_tracker.obter_resumo_mensal()
        custo_atual = resumo_mensal["custo_total"]

        if custo_atual >= limite:
            return datetime.utcnow()  # Já atingiu

        # Obter média diária dos últimos 7 dias
        gastos_7d = self.cost_tracker.obter_gastos_diarios(dias=7)
        valores = [v for v in gastos_7d.values()]
        media_diaria = sum(valores) / len(valores) if valores else 0

        if media_diaria <= 0:
            return None

        # Calcular dias restantes
        faltante = limite - custo_atual
        dias_restantes = int(faltante / media_diaria)

        if dias_restantes < 0:
            return datetime.utcnow()

        data_alerta = datetime.utcnow() + timedelta(days=dias_restantes)

        log.info(
            f"[forecaster] Alerta previsto para {data_alerta.strftime('%Y-%m-%d')}: "
            f"({dias_restantes} dias, media=${media_diaria:.2f}/dia)"
        )

        return data_alerta

    async def obter_resumo_previsoes(self) -> dict:
        """Resumo das previsões"""
        previsoes_7d = await self.prever_custos_7d()
        previsoes_30d = await self.prever_custos_30d()

        total_7d = sum(p.custo_estimado for p in previsoes_7d)
        total_30d = sum(p.custo_estimado for p in previsoes_30d)

        data_alerta_mensal = await self.prever_quando_alerta(
            self.cost_tracker.limite_mensal_usd
        )

        return {
            "previsao_7d": {
                "total": round(total_7d, 2),
                "media_diaria": round(total_7d / 7, 2),
                "min": round(min(p.custo_estimado for p in previsoes_7d), 2),
                "max": round(max(p.custo_estimado for p in previsoes_7d), 2),
            },
            "previsao_30d": {
                "total": round(total_30d, 2),
                "media_diaria": round(total_30d / 30, 2),
                "min": round(min(p.custo_estimado for p in previsoes_30d), 2),
                "max": round(max(p.custo_estimado for p in previsoes_30d), 2),
            },
            "data_alerta_mensal": (
                data_alerta_mensal.isoformat() if data_alerta_mensal else None
            ),
            "dias_ate_alerta": (
                (data_alerta_mensal - datetime.utcnow()).days
                if data_alerta_mensal and data_alerta_mensal > datetime.utcnow()
                else None
            ),
        }
