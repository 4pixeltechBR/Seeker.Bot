"""
Indexação de Dados
Suporte a busca full-text e vector search com embeddings
"""

import logging
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from src.core.data.store import Fato, ArmazemDados

log = logging.getLogger("seeker.data.indexing")


@dataclass
class ResultadoIndexacao:
    """Resultado de uma busca indexada"""
    fatos: List[Tuple[Fato, float]]  # (fato, score de relevância)
    total_encontrados: int
    tempo_busca_ms: float
    tipo_busca: str  # "fulltext", "categoria", "embedding"


class Indexador:
    """
    Indexador de dados para busca rápida
    Mantém índices em memória para performance
    """

    def __init__(self, armazem: ArmazemDados):
        self.armazem = armazem

        # Índices em memória
        self._indice_categoria: Dict[str, List[int]] = {}
        self._indice_palavras: Dict[str, List[int]] = {}
        self._cache_embeddings: Dict[int, List[float]] = {}

        log.info("[indexacao] Indexador inicializado")

    async def reindexar(self) -> None:
        """Reconstrói todos os índices a partir do armazém"""
        log.info("[indexacao] Iniciando reindexação...")

        # Limpar índices
        self._indice_categoria.clear()
        self._indice_palavras.clear()
        self._cache_embeddings.clear()

        # Reconstruir índices
        fatos = await self.armazem.obter_todos(minimo_confianca=0.0, limite=10000)

        for fato in fatos:
            # Índice por categoria
            if fato.categoria not in self._indice_categoria:
                self._indice_categoria[fato.categoria] = []
            self._indice_categoria[fato.categoria].append(fato.id)

            # Índice de palavras
            palavras = self._extrair_palavras(fato.conteudo)
            for palavra in palavras:
                if palavra not in self._indice_palavras:
                    self._indice_palavras[palavra] = []
                if fato.id not in self._indice_palavras[palavra]:
                    self._indice_palavras[palavra].append(fato.id)

        log.info(
            f"[indexacao] Reindexacao completa: "
            f"{len(fatos)} fatos, "
            f"{len(self._indice_categoria)} categorias, "
            f"{len(self._indice_palavras)} palavras"
        )

    async def buscar_por_categoria(
        self,
        categoria: str,
        limite: int = 50,
    ) -> ResultadoIndexacao:
        """Busca rápida por categoria usando índice"""
        import time
        inicio = time.time()

        ids = self._indice_categoria.get(categoria, [])[:limite]

        fatos_com_score = []
        for fato_id in ids:
            fato = await self.armazem.obter_por_id(fato_id)
            if fato:
                # Score baseado em confiança e recência
                score = fato.confianca * fato.relevancia
                fatos_com_score.append((fato, score))

        # Ordenar por score descendente
        fatos_com_score.sort(key=lambda x: x[1], reverse=True)

        tempo_ms = (time.time() - inicio) * 1000

        return ResultadoIndexacao(
            fatos=fatos_com_score,
            total_encontrados=len(fatos_com_score),
            tempo_busca_ms=tempo_ms,
            tipo_busca="categoria",
        )

    async def buscar_por_palavras(
        self,
        query: str,
        limite: int = 50,
    ) -> ResultadoIndexacao:
        """Busca usando índice de palavras"""
        import time
        inicio = time.time()

        palavras = self._extrair_palavras(query)

        # Encontrar fatos que contêm as palavras
        ids_candidatos = set()
        for palavra in palavras:
            if palavra in self._indice_palavras:
                ids_candidatos.update(self._indice_palavras[palavra])

        # Calcular score por frequência de palavras
        scores: Dict[int, float] = {}
        for fato_id in ids_candidatos:
            fato = await self.armazem.obter_por_id(fato_id)
            if fato:
                # Score = quantidade de palavras encontradas * confiança
                palavras_encontradas = sum(
                    1 for p in palavras if p in self._extrair_palavras(fato.conteudo)
                )
                score = (palavras_encontradas / len(palavras)) * fato.confianca
                scores[fato_id] = score

        # Ordenar e pegar top N
        fatos_ordenados = sorted(
            scores.items(),
            key=lambda x: x[1],
            reverse=True
        )[:limite]

        fatos_com_score = []
        for fato_id, score in fatos_ordenados:
            fato = await self.armazem.obter_por_id(fato_id)
            if fato:
                fatos_com_score.append((fato, score))

        tempo_ms = (time.time() - inicio) * 1000

        return ResultadoIndexacao(
            fatos=fatos_com_score,
            total_encontrados=len(fatos_com_score),
            tempo_busca_ms=tempo_ms,
            tipo_busca="palavras",
        )

    def _extrair_palavras(self, texto: str) -> List[str]:
        """Extrai palavras-chave do texto"""
        # Remove pontuação, converte para minúsculas
        import re
        palavras = re.findall(r'\b\w+\b', texto.lower())

        # Remove stop words comuns
        stop_words = {
            "o", "a", "de", "e", "para", "é", "um", "uma",
            "em", "por", "com", "que", "do", "da", "os", "as",
            "não", "mais", "se", "na", "no", "os", "as"
        }

        return [p for p in palavras if p not in stop_words and len(p) > 2]

    async def atualizar_indice_fato(self, fato: Fato) -> None:
        """Atualiza índices para um fato específico"""
        if not fato.id:
            return

        # Atualizar índice de categoria
        if fato.categoria not in self._indice_categoria:
            self._indice_categoria[fato.categoria] = []
        if fato.id not in self._indice_categoria[fato.categoria]:
            self._indice_categoria[fato.categoria].append(fato.id)

        # Atualizar índice de palavras
        palavras = self._extrair_palavras(fato.conteudo)
        for palavra in palavras:
            if palavra not in self._indice_palavras:
                self._indice_palavras[palavra] = []
            if fato.id not in self._indice_palavras[palavra]:
                self._indice_palavras[palavra].append(fato.id)

    async def remover_indice_fato(self, fato_id: int) -> None:
        """Remove um fato dos índices"""
        # Remover de índice de categoria
        for categoria in self._indice_categoria:
            if fato_id in self._indice_categoria[categoria]:
                self._indice_categoria[categoria].remove(fato_id)

        # Remover de índice de palavras
        for palavra in self._indice_palavras:
            if fato_id in self._indice_palavras[palavra]:
                self._indice_palavras[palavra].remove(fato_id)

        # Limpar cache de embeddings
        if fato_id in self._cache_embeddings:
            del self._cache_embeddings[fato_id]

    async def obter_estatisticas_indice(self) -> dict:
        """Retorna estatísticas dos índices"""
        total_palavras = sum(len(ids) for ids in self._indice_palavras.values())

        return {
            "categorias_indexadas": len(self._indice_categoria),
            "palavras_indexadas": len(self._indice_palavras),
            "total_palavras_mappings": total_palavras,
            "cache_embeddings": len(self._cache_embeddings),
        }
