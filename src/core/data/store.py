"""
Armazém de Dados
CRUD eficiente para fatos semânticos com SQLite
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import json

log = logging.getLogger("seeker.data.store")


@dataclass
class Fato:
    """Representa um fato semântico armazenado"""
    id: Optional[int] = None
    conteudo: str = ""
    categoria: str = "geral"
    confianca: float = 0.5
    fonte: str = "sistema"
    timestamp_criacao: Optional[datetime] = None
    timestamp_atualizacao: Optional[datetime] = None
    embedding: Optional[bytes] = None  # Serializado como BLOB
    metadados: Dict = None
    relevancia: float = 1.0
    vezes_utilizado: int = 0

    def __post_init__(self):
        if self.metadados is None:
            self.metadados = {}
        if self.timestamp_criacao is None:
            self.timestamp_criacao = datetime.utcnow()
        if self.timestamp_atualizacao is None:
            self.timestamp_atualizacao = datetime.utcnow()

    def para_dict(self) -> dict:
        """Serializa para dicionário"""
        return {
            "id": self.id,
            "conteudo": self.conteudo,
            "categoria": self.categoria,
            "confianca": round(self.confianca, 2),
            "fonte": self.fonte,
            "timestamp_criacao": self.timestamp_criacao.isoformat() if self.timestamp_criacao else None,
            "timestamp_atualizacao": self.timestamp_atualizacao.isoformat() if self.timestamp_atualizacao else None,
            "relevancia": round(self.relevancia, 2),
            "vezes_utilizado": self.vezes_utilizado,
            "metadados": self.metadados,
        }


@dataclass
class ResultadoBusca:
    """Resultado de uma busca"""
    fatos: List[Fato]
    total_encontrados: int
    tempo_busca_ms: float
    query: str


class ArmazemDados:
    """
    Armazém central de fatos com suporte a:
    - CRUD eficiente
    - Busca full-text
    - Indexação por categoria
    - Limpeza automática
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conexao: Optional[sqlite3.Connection] = None
        self._inicializar_db()

    def _inicializar_db(self) -> None:
        """Inicializa banco de dados com schema"""
        self.conexao = sqlite3.connect(
            self.db_path,
            check_same_thread=False
        )
        self.conexao.row_factory = sqlite3.Row

        cursor = self.conexao.cursor()

        # Tabela principal de fatos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fatos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conteudo TEXT NOT NULL,
                categoria TEXT NOT NULL DEFAULT 'geral',
                confianca REAL NOT NULL DEFAULT 0.5,
                fonte TEXT NOT NULL DEFAULT 'sistema',
                timestamp_criacao TIMESTAMP NOT NULL,
                timestamp_atualizacao TIMESTAMP NOT NULL,
                embedding BLOB,
                metadados TEXT,
                relevancia REAL DEFAULT 1.0,
                vezes_utilizado INTEGER DEFAULT 0
            )
        """)

        # Índices para performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_categoria
            ON fatos(categoria)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_confianca
            ON fatos(confianca DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON fatos(timestamp_atualizacao DESC)
        """)

        self.conexao.commit()
        log.info(f"[data] Banco inicializado: {self.db_path}")

    async def criar(self, fato: Fato) -> int:
        """Cria um novo fato, retorna ID"""
        cursor = self.conexao.cursor()

        metadados_json = json.dumps(fato.metadados) if fato.metadados else "{}"

        cursor.execute("""
            INSERT INTO fatos (
                conteudo, categoria, confianca, fonte,
                timestamp_criacao, timestamp_atualizacao,
                embedding, metadados, relevancia, vezes_utilizado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            fato.conteudo,
            fato.categoria,
            fato.confianca,
            fato.fonte,
            fato.timestamp_criacao,
            fato.timestamp_atualizacao,
            fato.embedding,
            metadados_json,
            fato.relevancia,
            fato.vezes_utilizado,
        ))

        self.conexao.commit()
        novo_id = cursor.lastrowid

        log.debug(
            f"[data] Fato criado: id={novo_id}, "
            f"categoria={fato.categoria}, confianca={fato.confianca:.2f}"
        )

        return novo_id

    async def obter_por_id(self, fato_id: int) -> Optional[Fato]:
        """Obtém um fato por ID"""
        cursor = self.conexao.cursor()
        cursor.execute("SELECT * FROM fatos WHERE id = ?", (fato_id,))
        row = cursor.fetchone()

        if not row:
            return None

        return self._row_para_fato(row)

    async def obter_por_categoria(
        self,
        categoria: str,
        minimo_confianca: float = 0.3,
        limite: int = 50,
    ) -> List[Fato]:
        """Obtém fatos por categoria"""
        cursor = self.conexao.cursor()
        cursor.execute("""
            SELECT * FROM fatos
            WHERE categoria = ? AND confianca >= ?
            ORDER BY confianca DESC, timestamp_atualizacao DESC
            LIMIT ?
        """, (categoria, minimo_confianca, limite))

        fatos = [self._row_para_fato(row) for row in cursor.fetchall()]
        return fatos

    async def buscar_texto(
        self,
        query: str,
        limite: int = 20,
    ) -> ResultadoBusca:
        """Busca full-text por conteúdo"""
        import time
        inicio = time.time()

        cursor = self.conexao.cursor()

        # Busca por LIKE com wildcards
        termos = query.split()
        condicoes = " AND ".join(
            f"conteudo LIKE ?" for _ in termos
        )
        parametros = [f"%{termo}%" for termo in termos]

        cursor.execute(f"""
            SELECT * FROM fatos
            WHERE {condicoes}
            ORDER BY confianca DESC, vezes_utilizado DESC
            LIMIT ?
        """, parametros + [limite])

        fatos = [self._row_para_fato(row) for row in cursor.fetchall()]

        tempo_ms = (time.time() - inicio) * 1000

        return ResultadoBusca(
            fatos=fatos,
            total_encontrados=len(fatos),
            tempo_busca_ms=tempo_ms,
            query=query,
        )

    async def atualizar(self, fato: Fato) -> bool:
        """Atualiza um fato existente"""
        if not fato.id:
            return False

        fato.timestamp_atualizacao = datetime.utcnow()
        cursor = self.conexao.cursor()

        metadados_json = json.dumps(fato.metadados) if fato.metadados else "{}"

        cursor.execute("""
            UPDATE fatos SET
                conteudo = ?,
                categoria = ?,
                confianca = ?,
                fonte = ?,
                timestamp_atualizacao = ?,
                embedding = ?,
                metadados = ?,
                relevancia = ?,
                vezes_utilizado = ?
            WHERE id = ?
        """, (
            fato.conteudo,
            fato.categoria,
            fato.confianca,
            fato.fonte,
            fato.timestamp_atualizacao,
            fato.embedding,
            metadados_json,
            fato.relevancia,
            fato.vezes_utilizado,
            fato.id,
        ))

        self.conexao.commit()
        return cursor.rowcount > 0

    async def deletar(self, fato_id: int) -> bool:
        """Deleta um fato"""
        cursor = self.conexao.cursor()
        cursor.execute("DELETE FROM fatos WHERE id = ?", (fato_id,))
        self.conexao.commit()
        return cursor.rowcount > 0

    async def obter_todos(
        self,
        minimo_confianca: float = 0.3,
        limite: int = 100,
    ) -> List[Fato]:
        """Obtém todos fatos acima de confiança mínima"""
        cursor = self.conexao.cursor()
        cursor.execute("""
            SELECT * FROM fatos
            WHERE confianca >= ?
            ORDER BY confianca DESC, timestamp_atualizacao DESC
            LIMIT ?
        """, (minimo_confianca, limite))

        return [self._row_para_fato(row) for row in cursor.fetchall()]

    async def contar(self) -> int:
        """Conta total de fatos"""
        cursor = self.conexao.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM fatos")
        return cursor.fetchone()["total"]

    async def estatisticas(self) -> dict:
        """Retorna estatísticas do armazém"""
        cursor = self.conexao.cursor()

        cursor.execute("SELECT COUNT(*) as total FROM fatos")
        total = cursor.fetchone()["total"]

        cursor.execute("SELECT AVG(confianca) as media FROM fatos")
        conf_media = cursor.fetchone()["media"] or 0.0

        cursor.execute("SELECT DISTINCT categoria FROM fatos")
        categorias = [row["categoria"] for row in cursor.fetchall()]

        cursor.execute("""
            SELECT categoria, COUNT(*) as quantidade
            FROM fatos
            GROUP BY categoria
        """)
        qtd_por_categoria = {
            row["categoria"]: row["quantidade"]
            for row in cursor.fetchall()
        }

        return {
            "total_fatos": total,
            "confianca_media": round(conf_media, 2),
            "categorias": categorias,
            "quantidade_por_categoria": qtd_por_categoria,
        }

    def _row_para_fato(self, row: sqlite3.Row) -> Fato:
        """Converte linha do BD em Fato"""
        metadados = {}
        if row["metadados"]:
            try:
                metadados = json.loads(row["metadados"])
            except:
                metadados = {}

        return Fato(
            id=row["id"],
            conteudo=row["conteudo"],
            categoria=row["categoria"],
            confianca=row["confianca"],
            fonte=row["fonte"],
            timestamp_criacao=datetime.fromisoformat(row["timestamp_criacao"]),
            timestamp_atualizacao=datetime.fromisoformat(row["timestamp_atualizacao"]),
            embedding=row["embedding"],
            metadados=metadados,
            relevancia=row["relevancia"],
            vezes_utilizado=row["vezes_utilizado"],
        )

    def fechar(self) -> None:
        """Fecha conexão com BD"""
        if self.conexao:
            self.conexao.close()
            log.info("[data] Conexão fechada")
