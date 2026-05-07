"""
Módulo de Gerenciamento de Dados
Armazenamento eficiente, indexação e retenção de fatos semânticos
"""

from src.core.data.store import (
    Fato, ArmazemDados, ResultadoBusca
)
from src.core.data.indexing import (
    Indexador, ResultadoIndexacao
)
from src.core.data.retention import (
    PoliticaRetencao, GerenciadorRetencao
)

__all__ = [
    "Fato",
    "ArmazemDados",
    "ResultadoBusca",
    "Indexador",
    "ResultadoIndexacao",
    "PoliticaRetencao",
    "GerenciadorRetencao",
]
