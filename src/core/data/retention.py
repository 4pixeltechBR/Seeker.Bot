"""
Políticas de Retenção de Dados
Limpeza automática baseada em idade, confiança, etc
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict
from src.core.data.store import ArmazemDados

log = logging.getLogger("seeker.data.retention")


@dataclass
class PoliticaRetencao:
    """Define política de retenção para fatos"""
    dias_retencao_maximo: int = 90  # Deletar após 90 dias
    dias_retencao_confianca_baixa: int = 30  # Deletar confiança < 0.3 após 30 dias
    confianca_minima_permanente: float = 0.7  # Guardar se confiança >= 0.7
    limpar_nao_utilizados: bool = True  # Limpar nunca usados
    dias_nao_utilizado: int = 14  # Se não usado há 14 dias


class GerenciadorRetencao:
    """
    Gerencia políticas de retenção e limpeza de dados
    Executa limpeza automática baseada em políticas
    """

    def __init__(
        self,
        armazem: ArmazemDados,
        politica: PoliticaRetencao = None,
    ):
        self.armazem = armazem
        self.politica = politica or PoliticaRetencao()
        self._ultimas_limpezas: Dict[str, datetime] = {}

        log.info(
            f"[retencao] Gerenciador inicializado: "
            f"retenção_máxima={self.politica.dias_retencao_maximo}d, "
            f"confiança_mínima={self.politica.confianca_minima_permanente}"
        )

    async def limpar_dados(self, simular: bool = False) -> dict:
        """
        Executa limpeza de dados baseada em políticas
        Se simular=True, apenas conta sem deletar
        """
        log.info("[retencao] Iniciando limpeza de dados...")

        agora = datetime.utcnow()

        # Obter todos fatos
        fatos = await self.armazem.obter_todos(minimo_confianca=0.0, limite=10000)

        contador_deletados = 0
        contador_por_motivo = {
            "idade_maxima": 0,
            "confianca_baixa": 0,
            "nunca_utilizado": 0,
            "total": 0,
        }

        for fato in fatos:
            motivo_delecao = None
            idade_dias = (agora - fato.timestamp_atualizacao).days

            # Regra 1: Idade máxima
            if idade_dias > self.politica.dias_retencao_maximo:
                if fato.confianca < self.politica.confianca_minima_permanente:
                    motivo_delecao = "idade_maxima"

            # Regra 2: Confiança baixa e antigo
            elif (
                fato.confianca < 0.3
                and idade_dias > self.politica.dias_retencao_confianca_baixa
            ):
                motivo_delecao = "confianca_baixa"

            # Regra 3: Nunca utilizado
            elif (
                self.politica.limpar_nao_utilizados
                and fato.vezes_utilizado == 0
                and idade_dias > self.politica.dias_nao_utilizado
            ):
                motivo_delecao = "nunca_utilizado"

            # Executar deleção se necessário
            if motivo_delecao:
                if not simular:
                    await self.armazem.deletar(fato.id)
                    log.debug(
                        f"[retencao] Deletado fato {fato.id}: {motivo_delecao}"
                    )

                contador_deletados += 1
                contador_por_motivo[motivo_delecao] += 1

        contador_por_motivo["total"] = contador_deletados

        # Log resultado
        modo = "SIMULAÇÃO" if simular else "EXECUÇÃO"
        log.info(
            f"[retencao] {modo} completa: "
            f"total_deletados={contador_deletados}, "
            f"idade_maxima={contador_por_motivo['idade_maxima']}, "
            f"confianca_baixa={contador_por_motivo['confianca_baixa']}, "
            f"nunca_utilizado={contador_por_motivo['nunca_utilizado']}"
        )

        self._ultimas_limpezas["geral"] = agora

        return {
            "total_deletados": contador_deletados,
            "por_motivo": contador_por_motivo,
            "simulacao": simular,
            "timestamp": agora.isoformat(),
        }

    async def aplicar_politica_categoria(
        self,
        categoria: str,
        dias_retencao: int,
        confianca_minima: float = 0.0,
    ) -> dict:
        """Aplica política específica para uma categoria"""
        log.info(
            f"[retencao] Limpando categoria '{categoria}': "
            f"dias={dias_retencao}, conf_mín={confianca_minima}"
        )

        agora = datetime.utcnow()
        fatos = await self.armazem.obter_por_categoria(
            categoria,
            minimo_confianca=0.0,
            limite=10000,
        )

        contador = 0
        for fato in fatos:
            idade_dias = (agora - fato.timestamp_atualizacao).days

            if idade_dias > dias_retencao and fato.confianca < confianca_minima:
                await self.armazem.deletar(fato.id)
                contador += 1

        self._ultimas_limpezas[categoria] = agora

        log.info(f"[retencao] Categoria '{categoria}': {contador} deletados")

        return {
            "categoria": categoria,
            "total_deletados": contador,
            "timestamp": agora.isoformat(),
        }

    async def analisar_dados_para_limpeza(self) -> dict:
        """Analisa dados sem deletar, retorna relatório"""
        agora = datetime.utcnow()
        fatos = await self.armazem.obter_todos(minimo_confianca=0.0, limite=10000)

        analise = {
            "total_fatos": len(fatos),
            "fatos_para_deletar": 0,
            "fatos_por_idade": {
                "0_7_dias": 0,
                "7_30_dias": 0,
                "30_90_dias": 0,
                "90_dias": 0,
            },
            "fatos_por_confianca": {
                "alta": 0,  # >= 0.7
                "media": 0,  # 0.3-0.7
                "baixa": 0,  # < 0.3
            },
            "nunca_utilizados": 0,
            "recomendacoes": [],
        }

        for fato in fatos:
            idade_dias = (agora - fato.timestamp_atualizacao).days

            # Categorizar por idade
            if idade_dias <= 7:
                analise["fatos_por_idade"]["0_7_dias"] += 1
            elif idade_dias <= 30:
                analise["fatos_por_idade"]["7_30_dias"] += 1
            elif idade_dias <= 90:
                analise["fatos_por_idade"]["30_90_dias"] += 1
            else:
                analise["fatos_por_idade"]["90_dias"] += 1

            # Categorizar por confiança
            if fato.confianca >= 0.7:
                analise["fatos_por_confianca"]["alta"] += 1
            elif fato.confianca >= 0.3:
                analise["fatos_por_confianca"]["media"] += 1
            else:
                analise["fatos_por_confianca"]["baixa"] += 1

            # Contar nunca utilizados
            if fato.vezes_utilizado == 0:
                analise["nunca_utilizados"] += 1

            # Verificar se seria deletado
            seria_deletado = False
            if (
                fato.confianca < self.politica.confianca_minima_permanente
                and idade_dias > self.politica.dias_retencao_maximo
            ):
                seria_deletado = True
            elif (
                fato.confianca < 0.3
                and idade_dias > self.politica.dias_retencao_confianca_baixa
            ):
                seria_deletado = True
            elif (
                self.politica.limpar_nao_utilizados
                and fato.vezes_utilizado == 0
                and idade_dias > self.politica.dias_nao_utilizado
            ):
                seria_deletado = True

            if seria_deletado:
                analise["fatos_para_deletar"] += 1

        # Gerar recomendações
        pct_para_deletar = (
            (analise["fatos_para_deletar"] / analise["total_fatos"]) * 100
            if analise["total_fatos"] > 0
            else 0
        )

        if pct_para_deletar > 10:
            analise["recomendacoes"].append(
                f"Consider limpar dados: {pct_para_deletar:.0f}% dos fatos poderiam ser deletados"
            )

        if analise["nunca_utilizados"] > analise["total_fatos"] * 0.2:
            analise["recomendacoes"].append(
                "20% ou mais dos fatos nunca foram utilizados - considere revisar políticas"
            )

        if analise["fatos_por_confianca"]["baixa"] > analise["total_fatos"] * 0.3:
            analise["recomendacoes"].append(
                "30% ou mais dos fatos têm confiança baixa - revisar qualidade dos dados"
            )

        return analise

    async def aumentar_relevancia(self, fato_id: int) -> None:
        """Aumenta relevância quando fato é utilizado"""
        fato = await self.armazem.obter_por_id(fato_id)
        if fato:
            fato.vezes_utilizado += 1
            fato.relevancia = min(2.0, fato.relevancia + 0.05)  # Max 2.0
            await self.armazem.atualizar(fato)

    def obter_status_limpeza(self) -> dict:
        """Retorna status das últimas limpezas"""
        agora = datetime.utcnow()

        status = {}
        for chave, timestamp in self._ultimas_limpezas.items():
            horas_atras = (agora - timestamp).total_seconds() / 3600
            status[chave] = {
                "ultima_limpeza": timestamp.isoformat(),
                "horas_atras": round(horas_atras, 1),
            }

        return status
