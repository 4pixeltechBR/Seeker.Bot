"""
Reporter Financeiro
Geração de relatórios em HTML para visualização
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

log = logging.getLogger("seeker.analytics.reporter")


@dataclass
class RelatorioFinanceiro:
    """Relatório financeiro estruturado"""
    titulo: str
    periodo: str
    timestamp: datetime
    conteudo_html: str
    resumo_executivo: dict


class Reporter:
    """
    Gerador de relatórios financeiros em HTML
    Para Telegram e visualização web
    """

    def __init__(self, dashboard=None, forecaster=None):
        self.dashboard = dashboard
        self.forecaster = forecaster

        log.info("[reporter] Reporter Financeiro inicializado")

    async def gerar_relatorio_diario(self) -> RelatorioFinanceiro:
        """Gera relatório diário"""
        metricas = await self.dashboard.obter_metricas()
        alertas = await self.dashboard.obter_alertas_ativos()
        resumo = await self.dashboard.obter_resumo_executivo()

        # Cores baseadas no status
        cor_status = {
            "OK": "#10b981",
            "CUIDADO": "#f59e0b",
            "ALERTA": "#ef4444",
            "CRITICO": "#991b1b",
        }
        status_color = cor_status.get(resumo["status"], "#6b7280")

        # Barra de progresso
        percentual = metricas.percentual_limite_diario
        barra_width = min(100, percentual)

        linhas = []
        linhas.append("<b>💰 RELATORIO FINANCEIRO DIARIO</b>\n")
        linhas.append(
            f"<code style='background: {status_color}; color: white;'>"
            f"  STATUS: {resumo['status']}  </code>\n"
        )

        linhas.append("<b>Gastos de Hoje</b>")
        linhas.append(f"{resumo['custo_hoje']} de ${metricas.custo_total_mes:.2f} no mês")
        linhas.append(
            f"<code>{'█' * int(barra_width/10)}{'░' * (10-int(barra_width/10))} "
            f"{metricas.percentual_limite_diario:.0f}%</code>\n"
        )

        linhas.append("<b>Métricas</b>")
        linhas.append(f"Saúde do Sistema: {resumo['saude']}")
        linhas.append(f"Tendência: {resumo['tendencia']}")
        linhas.append(f"Provedores Ativos: {resumo['provedores_ativos']}")
        linhas.append(
            f"Taxa Sucesso: {metricas.taxa_sucesso_geral:.1f}%"
        )
        linhas.append(f"Latência: {metricas.latencia_media_ms:.0f}ms\n")

        if alertas:
            linhas.append("<b>Alertas Ativos</b>")
            for alerta in alertas[:3]:  # Top 3 alertas
                emoji = "🔴" if alerta["tipo"] == "CRITICO" else "🟠" if alerta["tipo"] == "ALERTA" else "🔵"
                linhas.append(f"{emoji} <i>{alerta['mensagem']}</i>")

        html = "\n".join(linhas)

        return RelatorioFinanceiro(
            titulo="Relatório Financeiro Diário",
            periodo=datetime.utcnow().strftime("%Y-%m-%d"),
            timestamp=datetime.utcnow(),
            conteudo_html=html,
            resumo_executivo=resumo,
        )

    async def gerar_relatorio_semanal(self) -> RelatorioFinanceiro:
        """Gera relatório semanal com previsões"""
        metricas = await self.dashboard.obter_metricas()
        previsoes = await self.forecaster.obter_resumo_previsoes()
        detalhes = await self.dashboard.obter_detalhes_provedores()

        linhas = []
        linhas.append("<b>📊 RELATORIO SEMANAL</b>\n")

        # Resumo da semana
        linhas.append("<b>Esta Semana</b>")
        linhas.append(f"Gasto Hoje: ${metricas.custo_total_hoje:.2f}")
        linhas.append(f"Média 7d: ${metricas.custo_medio_diario_7d:.2f}/dia")
        linhas.append(f"Projeção: ${previsoes['previsao_7d']['total']:.2f}\n")

        # Previsão próximos 7 dias
        linhas.append("<b>Previsão Próximos 7 Dias</b>")
        linhas.append(f"Total: ${previsoes['previsao_7d']['total']:.2f}")
        linhas.append(f"Min: ${previsoes['previsao_7d']['min']:.2f}")
        linhas.append(f"Max: ${previsoes['previsao_7d']['max']:.2f}")
        linhas.append(f"Média/Dia: ${previsoes['previsao_7d']['media_diaria']:.2f}\n")

        # Top provedores
        linhas.append("<b>Top Provedores (7d)</b>")
        for provider, custo in sorted(
            metricas.custo_por_provider.items(),
            key=lambda x: x[1],
            reverse=True
        )[:3]:
            stats = detalhes.get(provider, {})
            taxa = stats.get("taxa_sucesso", 0)
            linhas.append(
                f"{provider}: ${custo:.2f} ({taxa:.0f}% sucesso, "
                f"{stats.get('chamadas', 0)} chamadas)"
            )

        html = "\n".join(linhas)

        return RelatorioFinanceiro(
            titulo="Relatório Semanal",
            periodo=datetime.utcnow().strftime("%Y-W%W"),
            timestamp=datetime.utcnow(),
            conteudo_html=html,
            resumo_executivo=previsoes,
        )

    async def gerar_relatorio_mensal(self) -> RelatorioFinanceiro:
        """Gera relatório mensal completo"""
        resumo_mensal = self.dashboard.cost_tracker.obter_resumo_mensal()
        metricas = await self.dashboard.obter_metricas()
        previsoes = await self.forecaster.obter_resumo_previsoes()

        mes_ano = datetime.utcnow().strftime("%B %Y")

        linhas = []
        linhas.append("<b>📈 RELATORIO MENSAL</b>")
        linhas.append(f"<i>Período: {mes_ano}</i>\n")

        # Custos mensais
        linhas.append("<b>Resumo Financeiro</b>")
        linhas.append(f"Total Mês: ${metricas.custo_total_mes:.2f}")
        linhas.append(f"Limite: ${resumo_mensal['limite']:.2f}")
        linhas.append(f"Utilização: {resumo_mensal['porcentagem_limite']:.0f}%")
        linhas.append(f"Restante: ${resumo_mensal['limite'] - metricas.custo_total_mes:.2f}\n")

        # Previsão para próximos 30 dias
        linhas.append("<b>Previsão Próximos 30 Dias</b>")
        linhas.append(f"Total Estimado: ${previsoes['previsao_30d']['total']:.2f}")
        linhas.append(f"Média/Dia: ${previsoes['previsao_30d']['media_diaria']:.2f}")

        if previsoes['data_alerta_mensal']:
            linhas.append(
                f"Possível Alerta: {previsoes['data_alerta_mensal']} "
                f"({previsoes['dias_ate_alerta']} dias)"
            )
        else:
            linhas.append("Sem alertas previstos")

        linhas.append("")

        # Tendências
        linhas.append("<b>Análise</b>")
        linhas.append(f"Tendência: {metricas.tendencia_custos.upper()}")
        linhas.append(f"Média 30d: ${metricas.custo_medio_diario_30d:.2f}/dia")
        linhas.append(f"Saúde: {await self._obter_saude_sistema()}")

        html = "\n".join(linhas)

        return RelatorioFinanceiro(
            titulo="Relatório Mensal",
            periodo=datetime.utcnow().strftime("%Y-%m"),
            timestamp=datetime.utcnow(),
            conteudo_html=html,
            resumo_executivo=previsoes,
        )

    async def _obter_saude_sistema(self) -> str:
        """Avalia saúde geral do sistema"""
        metricas = await self.dashboard.obter_metricas()
        return metricas.taxa_sucesso_geral >= 95 and metricas.percentual_limite_mensal <= 80 and "EXCELENTE" or "BOA"

    def formatar_para_telegram(self, relatorio: RelatorioFinanceiro) -> str:
        """Formata relatório para envio no Telegram"""
        # Remove tags HTML e formata para Telegram
        html = relatorio.conteudo_html
        html = html.replace("<b>", "<b>").replace("</b>", "</b>")
        html = html.replace("<i>", "<i>").replace("</i>", "</i>")
        html = html.replace("<code>", "<code>").replace("</code>", "</code>")

        return html
