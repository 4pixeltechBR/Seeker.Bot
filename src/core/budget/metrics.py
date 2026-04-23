"""
Métricas e agregação de custos
Estruturas de dados para rastreamento financeiro
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Dict, List, Optional

log = logging.getLogger("seeker.budget.metrics")


@dataclass
class CustoMetrica:
    """Métrica de custo para uma chamada de LLM"""
    timestamp: datetime
    provider: str
    modelo: str
    fase: str  # "Reflex", "Deliberate", "Deep"
    tokens_entrada: int
    tokens_saida: int
    custo_usd: float
    tempo_latencia_ms: int
    sucesso: bool
    mensagem_erro: Optional[str] = None

    def para_dict(self) -> dict:
        """Serializa para dicionário"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "provider": self.provider,
            "modelo": self.modelo,
            "fase": self.fase,
            "tokens_entrada": self.tokens_entrada,
            "tokens_saida": self.tokens_saida,
            "custo_usd": self.custo_usd,
            "tempo_latencia_ms": self.tempo_latencia_ms,
            "sucesso": self.sucesso,
            "mensagem_erro": self.mensagem_erro,
        }


@dataclass
class CustoAgregado:
    """Custo agregado por chave (provider, modelo, fase, etc)"""
    chave: str
    total_chamadas: int = 0
    total_custo_usd: float = 0.0
    total_tokens_entrada: int = 0
    total_tokens_saida: int = 0
    chamadas_sucesso: int = 0
    chamadas_falha: int = 0
    tempo_latencia_min_ms: int = float('inf')
    tempo_latencia_max_ms: int = 0
    tempo_latencia_medio_ms: float = 0.0
    custo_min: float = float('inf')
    custo_max: float = 0.0

    @property
    def taxa_sucesso(self) -> float:
        """Taxa de sucesso em porcentagem"""
        if self.total_chamadas == 0:
            return 0.0
        return (self.chamadas_sucesso / self.total_chamadas) * 100

    @property
    def custo_medio(self) -> float:
        """Custo médio por chamada"""
        if self.total_chamadas == 0:
            return 0.0
        return self.total_custo_usd / self.total_chamadas

    @property
    def tokens_por_chamada(self) -> int:
        """Média de tokens por chamada"""
        if self.total_chamadas == 0:
            return 0
        total_tokens = self.total_tokens_entrada + self.total_tokens_saida
        return total_tokens // self.total_chamadas

    def para_dict(self) -> dict:
        """Serializa para dicionário"""
        return {
            "chave": self.chave,
            "total_chamadas": self.total_chamadas,
            "total_custo_usd": round(self.total_custo_usd, 4),
            "taxa_sucesso": round(self.taxa_sucesso, 1),
            "custo_medio": round(self.custo_medio, 4),
            "custo_min": round(self.custo_min, 4),
            "custo_max": round(self.custo_max, 4),
            "tempo_latencia_medio_ms": round(self.tempo_latencia_medio_ms, 0),
            "tokens_por_chamada": self.tokens_por_chamada,
        }


@dataclass
class EstatisticasProveedor:
    """Estatísticas agregadas de um provedor"""
    provedor: str
    total_chamadas: int = 0
    total_custo_usd: float = 0.0
    custo_por_modelo: Dict[str, float] = field(default_factory=dict)
    custo_por_fase: Dict[str, float] = field(default_factory=dict)
    chamadas_por_modelo: Dict[str, int] = field(default_factory=dict)
    taxa_sucesso: float = 0.0
    tempo_latencia_medio_ms: float = 0.0
    ultimas_chamadas: deque = field(default_factory=lambda: deque(maxlen=50))

    @property
    def custo_medio(self) -> float:
        """Custo médio por chamada"""
        if self.total_chamadas == 0:
            return 0.0
        return self.total_custo_usd / self.total_chamadas

    @property
    def modelo_mais_usado(self) -> Optional[str]:
        """Modelo mais frequentemente usado"""
        if not self.chamadas_por_modelo:
            return None
        return max(self.chamadas_por_modelo, key=self.chamadas_por_modelo.get)

    @property
    def modelo_mais_caro(self) -> Optional[str]:
        """Modelo com maior custo acumulado"""
        if not self.custo_por_modelo:
            return None
        return max(self.custo_por_modelo, key=self.custo_por_modelo.get)

    def para_dict(self) -> dict:
        """Serializa para dicionário"""
        return {
            "provedor": self.provedor,
            "total_chamadas": self.total_chamadas,
            "total_custo_usd": round(self.total_custo_usd, 4),
            "custo_medio": round(self.custo_medio, 4),
            "taxa_sucesso": round(self.taxa_sucesso, 1),
            "tempo_latencia_medio_ms": round(self.tempo_latencia_medio_ms, 0),
            "modelo_mais_usado": self.modelo_mais_usado,
            "modelo_mais_caro": self.modelo_mais_caro,
            "custo_por_modelo": {
                modelo: round(custo, 4)
                for modelo, custo in self.custo_por_modelo.items()
            },
            "custo_por_fase": {
                fase: round(custo, 4)
                for fase, custo in self.custo_por_fase.items()
            },
        }
