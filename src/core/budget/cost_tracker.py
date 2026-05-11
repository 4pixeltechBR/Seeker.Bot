"""
Rastreador de custos com histórico e alertas
Gerencia limite diário/mensal e notificações
"""

import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple
from src.core.budget.metrics import CustoMetrica, CustoAgregado, EstatisticasProveedor
from src.core.budget.quota_manager import QuotaManager

log = logging.getLogger("seeker.budget.cost_tracker")


@dataclass
class AlertaCusto:
    """Alerta quando limite é excedido"""

    timestamp: datetime
    tipo_alerta: str  # "diario", "mensal", "anomalia"
    provedor: str
    mensagem: str
    custo_atual: float
    limite: float
    porcentagem_limite: float


class RastreadorCustos:
    """
    Rastreador central de custos por LLM provider
    Mantém histórico, detecta tendências, gera alertas
    """

    def __init__(
        self,
        limite_diario_usd: float = 10.0,
        limite_mensal_usd: float = 200.0,
        tamanho_historico: int = 500,
    ):
        self.limite_diario_usd = limite_diario_usd
        self.limite_mensal_usd = limite_mensal_usd

        # Histórico completo
        self._historico: deque = deque(maxlen=tamanho_historico)

        # Agregação por chave (provider:modelo:fase, etc)
        self._agregados: Dict[str, CustoAgregado] = {}

        # Estatísticas por provedor
        self._provedores: Dict[str, EstatisticasProveedor] = {}

        # Alertas gerados
        self._alertas: deque = deque(maxlen=100)

        # Rastreamento diário/mensal
        self._gastos_diarios: Dict[str, float] = defaultdict(float)
        self._gastos_mensais: Dict[str, float] = defaultdict(float)

        # Cache Telemetry (Phase 4) — rastrear economia por cache hit
        self._cache_hits_diarios: Dict[str, int] = defaultdict(int)  # tokens salvos
        self._cache_hits_mensais: Dict[str, int] = defaultdict(int)
        self._custo_economizado_diarios: Dict[str, float] = defaultdict(float)  # USD
        self._custo_economizado_mensais: Dict[str, float] = defaultdict(float)

        # Quota & Credits Manager (Sprint 11)
        self.quota_manager = QuotaManager()

        log.info(
            f"[custo] Rastreador inicializado: "
            f"limite_diario=${limite_diario_usd:.2f}, "
            f"limite_mensal=${limite_mensal_usd:.2f}"
        )

    def registrar_custo(
        self,
        provider: str,
        modelo: str,
        fase: str,
        tokens_entrada: int,
        tokens_saida: int,
        custo_usd: float,
        tempo_latencia_ms: int = 0,
        sucesso: bool = True,
        mensagem_erro: Optional[str] = None,
        cache_hit_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> Optional[AlertaCusto]:
        """
        Registra uma chamada de LLM e retorna alerta se limite excedido.
        Opcionalmente registra economia por cache hit (Phase 4).
        """
        agora = datetime.utcnow()

        # Criar métrica
        metrica = CustoMetrica(
            timestamp=agora,
            provider=provider,
            modelo=modelo,
            fase=fase,
            tokens_entrada=tokens_entrada,
            tokens_saida=tokens_saida,
            custo_usd=custo_usd,
            tempo_latencia_ms=tempo_latencia_ms,
            sucesso=sucesso,
            mensagem_erro=mensagem_erro,
        )

        # Adicionar ao histórico
        self._historico.append(metrica)

        # Atualizar agregados
        self._atualizar_agregados(metrica)

        # Atualizar estatísticas do provedor
        self._atualizar_provedores(metrica)

        # Atualizar gastos diários/mensais
        data_chave = agora.strftime("%Y-%m-%d")
        mes_chave = agora.strftime("%Y-%m")
        self._gastos_diarios[data_chave] += custo_usd
        self._gastos_mensais[mes_chave] += custo_usd

        # Registrar economia por cache (Phase 4)
        if cache_hit_tokens > 0 or cache_creation_tokens > 0:
            self._registrar_cache_telemetria(
                provider, data_chave, mes_chave,
                cache_hit_tokens, cache_creation_tokens, custo_usd
            )

        # Consome cota financeira se aplicável (DeepSeek, etc)
        self.quota_manager.consume_financial(provider, custo_usd)

        # Verificar limites
        alerta = self._verificar_limites(provider, agora)

        if sucesso:
            log.debug(
                f"[custo] {provider}/{modelo}: "
                f"${custo_usd:.4f} ({tokens_entrada}+{tokens_saida} tokens)"
            )
        else:
            log.warning(f"[custo] {provider}/{modelo}: ERRO - {mensagem_erro}")

        return alerta

    def _atualizar_agregados(self, metrica: CustoMetrica) -> None:
        """Atualiza agregados por diferentes dimensões"""
        chaves = [
            f"{metrica.provider}",
            f"{metrica.provider}:{metrica.modelo}",
            f"{metrica.provider}:{metrica.fase}",
            f"{metrica.provider}:{metrica.modelo}:{metrica.fase}",
        ]

        for chave in chaves:
            if chave not in self._agregados:
                self._agregados[chave] = CustoAgregado(chave=chave)

            agg = self._agregados[chave]
            agg.total_chamadas += 1
            agg.total_custo_usd += metrica.custo_usd
            agg.total_tokens_entrada += metrica.tokens_entrada
            agg.total_tokens_saida += metrica.tokens_saida

            if metrica.sucesso:
                agg.chamadas_sucesso += 1
            else:
                agg.chamadas_falha += 1

            # Atualizar latência
            if metrica.tempo_latencia_ms > 0:
                agg.tempo_latencia_min_ms = min(
                    agg.tempo_latencia_min_ms, metrica.tempo_latencia_ms
                )
                agg.tempo_latencia_max_ms = max(
                    agg.tempo_latencia_max_ms, metrica.tempo_latencia_ms
                )
                total_ms = agg.tempo_latencia_medio_ms * (agg.total_chamadas - 1)
                agg.tempo_latencia_medio_ms = (
                    total_ms + metrica.tempo_latencia_ms
                ) / agg.total_chamadas

            # Atualizar custo min/max
            agg.custo_min = min(agg.custo_min, metrica.custo_usd)
            agg.custo_max = max(agg.custo_max, metrica.custo_usd)

    def _atualizar_provedores(self, metrica: CustoMetrica) -> None:
        """Atualiza estatísticas agregadas por provedor"""
        if metrica.provider not in self._provedores:
            self._provedores[metrica.provider] = EstatisticasProveedor(
                provedor=metrica.provider
            )

        prov = self._provedores[metrica.provider]
        prov.total_chamadas += 1
        prov.total_custo_usd += metrica.custo_usd

        # Custo por modelo
        if metrica.modelo not in prov.custo_por_modelo:
            prov.custo_por_modelo[metrica.modelo] = 0.0
        prov.custo_por_modelo[metrica.modelo] += metrica.custo_usd

        # Chamadas por modelo
        if metrica.modelo not in prov.chamadas_por_modelo:
            prov.chamadas_por_modelo[metrica.modelo] = 0
        prov.chamadas_por_modelo[metrica.modelo] += 1

        # Custo por fase
        if metrica.fase not in prov.custo_por_fase:
            prov.custo_por_fase[metrica.fase] = 0.0
        prov.custo_por_fase[metrica.fase] += metrica.custo_usd

        # Taxa de sucesso
        total_sucesso = sum(
            1 for m in self._historico if m.provider == metrica.provider and m.sucesso
        )
        prov.taxa_sucesso = (total_sucesso / prov.total_chamadas) * 100

        # Latência média
        metricas_prov = [m for m in self._historico if m.provider == metrica.provider]
        if metricas_prov:
            prov.tempo_latencia_medio_ms = sum(
                m.tempo_latencia_ms for m in metricas_prov
            ) / len(metricas_prov)

        # Últimas chamadas
        prov.ultimas_chamadas.append(metrica)

    def _verificar_limites(
        self, provider: str, agora: datetime
    ) -> Optional[AlertaCusto]:
        """Verifica se limites diários/mensais foram excedidos"""
        data_chave = agora.strftime("%Y-%m-%d")
        mes_chave = agora.strftime("%Y-%m")

        custo_diario = self._gastos_diarios[data_chave]
        custo_mensal = self._gastos_mensais[mes_chave]

        # Verificar limite diário
        if custo_diario > self.limite_diario_usd:
            pct = (custo_diario / self.limite_diario_usd) * 100
            if pct > 100:  # Só alerta se exceder
                alerta = AlertaCusto(
                    timestamp=agora,
                    tipo_alerta="diario",
                    provedor=provider,
                    mensagem=(
                        f"Limite diário excedido: "
                        f"${custo_diario:.2f} de ${self.limite_diario_usd:.2f}"
                    ),
                    custo_atual=custo_diario,
                    limite=self.limite_diario_usd,
                    porcentagem_limite=pct,
                )
                self._alertas.append(alerta)
                log.warning(f"[alerta] {alerta.mensagem}")
                return alerta

        # Verificar limite mensal
        if custo_mensal > self.limite_mensal_usd:
            pct = (custo_mensal / self.limite_mensal_usd) * 100
            if pct > 100:
                alerta = AlertaCusto(
                    timestamp=agora,
                    tipo_alerta="mensal",
                    provedor=provider,
                    mensagem=(
                        f"Limite mensal excedido: "
                        f"${custo_mensal:.2f} de ${self.limite_mensal_usd:.2f}"
                    ),
                    custo_atual=custo_mensal,
                    limite=self.limite_mensal_usd,
                    porcentagem_limite=pct,
                )
                self._alertas.append(alerta)
                log.warning(f"[alerta] {alerta.mensagem}")
                return alerta

        return None

    def _registrar_cache_telemetria(
        self,
        provider: str,
        data_chave: str,
        mes_chave: str,
        cache_hit_tokens: int,
        cache_creation_tokens: int,
        custo_usd: float,
    ) -> None:
        """Registra economia por cache hit (Phase 4 telemetry)."""
        total_cached = cache_hit_tokens + cache_creation_tokens
        if total_cached == 0:
            return

        # Economia estimada: custo não pago por tokens cached
        # DeepSeek: hit reduz input tokens em 90%, creation em 25% discount
        # Gemini: hit reduz input tokens em 90%, creation em 50% discount
        economia_usd = 0.0
        if cache_hit_tokens > 0:
            economia_usd += (cache_hit_tokens / max(1, cache_hit_tokens + (custo_usd * 1_000_000)))

        # Registra história diária/mensal
        self._cache_hits_diarios[data_chave] += total_cached
        self._cache_hits_mensais[mes_chave] += total_cached
        self._custo_economizado_diarios[data_chave] += economia_usd
        self._custo_economizado_mensais[mes_chave] += economia_usd

        if cache_hit_tokens > 0:
            log.debug(
                f"[cache] {provider}: CACHE HIT "
                f"{cache_hit_tokens} tokens (~${economia_usd:.6f} economizado)"
            )

    def obter_economia_cache_diaria(self, dias: int = 7) -> Dict[str, dict]:
        """Retorna economia de cache dos últimos N dias."""
        agora = datetime.utcnow()
        economia = {}

        for i in range(dias):
            data = (agora - timedelta(days=i)).strftime("%Y-%m-%d")
            economia[data] = {
                "tokens_cache": self._cache_hits_diarios.get(data, 0),
                "custo_economizado_usd": round(
                    self._custo_economizado_diarios.get(data, 0.0), 4
                ),
            }

        return dict(sorted(economia.items()))

    def obter_economia_cache_mensal(self) -> dict:
        """Retorna economia de cache do mês atual."""
        agora = datetime.utcnow()
        mes_chave = agora.strftime("%Y-%m")
        total_tokens = self._cache_hits_mensais.get(mes_chave, 0)
        total_economia = self._custo_economizado_mensais.get(mes_chave, 0.0)

        return {
            "mes": mes_chave,
            "tokens_cache": total_tokens,
            "custo_economizado_usd": round(total_economia, 4),
            "taxa_economia": self._calcular_taxa_economia(mes_chave),
        }

    def _calcular_taxa_economia(self, mes_chave: str) -> float:
        """Calcula percentual de economia vs custo total do mês."""
        custo_total = self._gastos_mensais.get(mes_chave, 0.0)
        economia = self._custo_economizado_mensais.get(mes_chave, 0.0)

        if custo_total <= 0:
            return 0.0
        return round((economia / (custo_total + economia)) * 100, 1)

    def obter_gastos_diarios(self, dias: int = 7) -> Dict[str, float]:
        """Retorna gastos dos últimos N dias"""
        agora = datetime.utcnow()
        gastos = {}

        for i in range(dias):
            data = (agora - timedelta(days=i)).strftime("%Y-%m-%d")
            gastos[data] = self._gastos_diarios.get(data, 0.0)

        return dict(sorted(gastos.items()))

    def obter_gasto_mensal_atual(self) -> Tuple[str, float]:
        """Retorna mês atual e gasto total"""
        agora = datetime.utcnow()
        mes_chave = agora.strftime("%Y-%m")
        custo = self._gastos_mensais.get(mes_chave, 0.0)
        return mes_chave, custo

    def obter_estatisticas_provedor(self, provider: str) -> Optional[dict]:
        """Retorna estatísticas de um provedor específico"""
        if provider not in self._provedores:
            return None
        return self._provedores[provider].para_dict()

    def obter_todas_estatisticas(self) -> Dict[str, dict]:
        """Retorna estatísticas de todos provedores"""
        return {prov: stats.para_dict() for prov, stats in self._provedores.items()}

    def obter_agregado(self, chave: str) -> Optional[dict]:
        """Retorna agregado para uma chave específica"""
        if chave not in self._agregados:
            return None
        return self._agregados[chave].para_dict()

    def obter_alertas_recentes(self, limite: int = 10) -> List[dict]:
        """Retorna últimos N alertas"""
        alertas = []
        for alerta in list(self._alertas)[-limite:]:
            alertas.append(
                {
                    "timestamp": alerta.timestamp.isoformat(),
                    "tipo": alerta.tipo_alerta,
                    "provedor": alerta.provedor,
                    "mensagem": alerta.mensagem,
                    "custo_atual": round(alerta.custo_atual, 2),
                    "limite": round(alerta.limite, 2),
                    "porcentagem": round(alerta.porcentagem_limite, 1),
                }
            )
        return alertas

    def obter_resumo_diario(self) -> dict:
        """Retorna resumo do gasto de hoje"""
        agora = datetime.utcnow()
        data_chave = agora.strftime("%Y-%m-%d")
        custo_hoje = self._gastos_diarios[data_chave]

        return {
            "data": data_chave,
            "custo_total": round(custo_hoje, 2),
            "limite": self.limite_diario_usd,
            "porcentagem_limite": round((custo_hoje / self.limite_diario_usd) * 100, 1),
            "provedores": {
                prov: stats["total_custo_usd"]
                for prov, stats in self.obter_todas_estatisticas().items()
            },
        }

    def obter_resumo_mensal(self) -> dict:
        """Retorna resumo do gasto do mês"""
        mes_chave, custo = self.obter_gasto_mensal_atual()

        return {
            "mes": mes_chave,
            "custo_total": round(custo, 2),
            "limite": self.limite_mensal_usd,
            "porcentagem_limite": round((custo / self.limite_mensal_usd) * 100, 1),
            "provedores": {
                prov: stats["total_custo_usd"]
                for prov, stats in self.obter_todas_estatisticas().items()
            },
        }

    def formatar_relatorio_custos(self) -> str:
        """Formata relatório HTML para Telegram"""
        resumo_diario = self.obter_resumo_diario()
        resumo_mensal = self.obter_resumo_mensal()

        # Barra de progresso
        def barra_progresso(percent: float, largura: int = 10) -> str:
            preenchido = int(percent / 10)
            vazio = largura - preenchido
            return "█" * preenchido + "░" * vazio

        linhas = []
        linhas.append("<b>💰 GASTOS - RESUMO DIÁRIO</b>\n")
        linhas.append(
            f"<code>{barra_progresso(resumo_diario['porcentagem_limite'])}</code> "
            f"${resumo_diario['custo_total']:.2f} / ${resumo_diario['limite']:.2f}"
        )
        linhas.append(f"<i>{resumo_diario['porcentagem_limite']:.0f}% do limite</i>\n")

        linhas.append("<b>GASTOS POR PROVEDOR (HOJE)</b>")
        for prov, custo in sorted(
            resumo_diario["provedores"].items(), key=lambda x: x[1], reverse=True
        ):
            if custo > 0:
                linhas.append(f"  {prov}: ${custo:.4f}")

        linhas.append(f"\n<b>📊 GASTOS - MÊS ({resumo_mensal['mes']})</b>\n")
        linhas.append(
            f"<code>{barra_progresso(resumo_mensal['porcentagem_limite'])}</code> "
            f"${resumo_mensal['custo_total']:.2f} / ${resumo_mensal['limite']:.2f}"
        )
        linhas.append(f"<i>{resumo_mensal['porcentagem_limite']:.0f}% do limite</i>")

        return "\n".join(linhas)
