"""
Cache Statistics Provider (Phase 4)
Agregação de telemetria de cache hit/creation para análise de economia
"""

import logging
from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass, field

log = logging.getLogger("seeker.budget.cache_stats")


@dataclass
class CacheMetrics:
    """Métricas de cache para período específico."""

    periodo: str  # "2025-03-15" ou "2025-03"
    total_cache_hits: int = 0
    total_cache_creations: int = 0
    economia_estimada_usd: float = 0.0
    chamadas_com_cache: int = 0
    taxa_cache_hit: float = 0.0  # porcentagem

    def para_dict(self) -> dict:
        """Serializa para dicionário."""
        return {
            "periodo": self.periodo,
            "total_cache_hits": self.total_cache_hits,
            "total_cache_creations": self.total_cache_creations,
            "economia_estimada_usd": round(self.economia_estimada_usd, 4),
            "chamadas_com_cache": self.chamadas_com_cache,
            "taxa_cache_hit": round(self.taxa_cache_hit, 1),
        }


class CacheStatsProvider:
    """
    Agregador de telemetria de cache.
    Coleta dados de LLMResponse (cache_hit_tokens, cache_creation_tokens)
    e calcula economia por provider, modelo, fase.
    """

    def __init__(self):
        # Por provider:modelo:fase
        self._cache_stats: Dict[str, CacheMetrics] = {}

        # Histórico por dia
        self._metricas_diarias: Dict[str, CacheMetrics] = {}

        # Acumulado geral
        self.total_hits_globais = 0
        self.total_creations_globais = 0
        self.economia_total_usd = 0.0

    def registrar_resposta(
        self,
        provider: str,
        modelo: str,
        fase: str,
        cache_hit_tokens: int,
        cache_creation_tokens: int,
        custo_usd: float,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Registra resposta com telemetria de cache."""
        if timestamp is None:
            timestamp = datetime.utcnow()

        chave = f"{provider}:{modelo}:{fase}"
        data_chave = timestamp.strftime("%Y-%m-%d")

        # Registra globalmente
        self.total_hits_globais += cache_hit_tokens
        self.total_creations_globais += cache_creation_tokens

        # Economia estimada (hit = 90% discount, creation = 25-50% discount)
        economia = self._estimar_economia(
            cache_hit_tokens, cache_creation_tokens, provider, custo_usd
        )
        self.economia_total_usd += economia

        # Agregado por dimensão
        if chave not in self._cache_stats:
            self._cache_stats[chave] = CacheMetrics(periodo=chave)

        stats = self._cache_stats[chave]
        stats.total_cache_hits += cache_hit_tokens
        stats.total_cache_creations += cache_creation_tokens
        stats.economia_estimada_usd += economia
        if cache_hit_tokens + cache_creation_tokens > 0:
            stats.chamadas_com_cache += 1

        # Agregado por dia
        if data_chave not in self._metricas_diarias:
            self._metricas_diarias[data_chave] = CacheMetrics(periodo=data_chave)

        daily = self._metricas_diarias[data_chave]
        daily.total_cache_hits += cache_hit_tokens
        daily.total_cache_creations += cache_creation_tokens
        daily.economia_estimada_usd += economia
        if cache_hit_tokens + cache_creation_tokens > 0:
            daily.chamadas_com_cache += 1

    def _estimar_economia(
        self,
        cache_hit_tokens: int,
        cache_creation_tokens: int,
        provider: str,
        custo_usd: float,
    ) -> float:
        """Estima economia USD baseado em hit/creation tokens e provider."""
        economia = 0.0

        # DeepSeek: 90% discount no cache hit, 25% no cache creation
        if "deepseek" in provider.lower():
            economia = (cache_hit_tokens * 0.9) / 1_000_000 * 0.14  # $0.14/1M
            economia += (cache_creation_tokens * 0.25) / 1_000_000 * 0.14

        # Gemini: 90% discount no cache hit, 50% no cache creation
        elif "gemini" in provider.lower():
            economia = (cache_hit_tokens * 0.9) / 1_000_000 * 0.075  # $0.075/1M
            economia += (cache_creation_tokens * 0.50) / 1_000_000 * 0.075

        # OpenAI: usar custo para estimar (menos preciso)
        elif cache_hit_tokens > 0:
            economia = custo_usd * 0.5  # aproximação conservadora

        return economia

    def obter_stats_por_dimensao(self, dimensao: str) -> Dict[str, dict]:
        """Retorna stats agregados por dimensão específica."""
        resultado = {}
        for chave, metrics in self._cache_stats.items():
            # Extrai a dimensão desejada (provider, modelo ou fase)
            partes = chave.split(":")
            if dimensao == "provider" and len(partes) >= 1:
                dim_key = partes[0]
            elif dimensao == "modelo" and len(partes) >= 2:
                dim_key = partes[1]
            elif dimensao == "fase" and len(partes) >= 3:
                dim_key = partes[2]
            else:
                continue

            if dim_key not in resultado:
                resultado[dim_key] = CacheMetrics(periodo=dim_key)

            stats = resultado[dim_key]
            stats.total_cache_hits += metrics.total_cache_hits
            stats.total_cache_creations += metrics.total_cache_creations
            stats.economia_estimada_usd += metrics.economia_estimada_usd
            stats.chamadas_com_cache += metrics.chamadas_com_cache

        return {k: v.para_dict() for k, v in resultado.items()}

    def obter_stats_diarias(self, dias: int = 7) -> Dict[str, dict]:
        """Retorna stats de cache dos últimos N dias."""
        from datetime import timedelta

        agora = datetime.utcnow()
        resultado = {}

        for i in range(dias):
            data = (agora - timedelta(days=i)).strftime("%Y-%m-%d")
            if data in self._metricas_diarias:
                resultado[data] = self._metricas_diarias[data].para_dict()
            else:
                resultado[data] = CacheMetrics(periodo=data).para_dict()

        return dict(sorted(resultado.items()))

    def obter_resumo_geral(self) -> dict:
        """Retorna resumo geral de cache."""
        return {
            "total_cache_hits": self.total_hits_globais,
            "total_cache_creations": self.total_creations_globais,
            "economia_total_usd": round(self.economia_total_usd, 4),
            "stats_por_provider": self.obter_stats_por_dimensao("provider"),
            "stats_por_modelo": self.obter_stats_por_dimensao("modelo"),
            "stats_por_fase": self.obter_stats_por_dimensao("fase"),
        }
