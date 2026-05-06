"""
Seeker.Bot — Memory Protocol
src/core/memory/protocol.py

Contrato estável para backends de memória.

Qualquer módulo que precisa de memória depende DESTE protocolo,
não de uma implementação concreta. Isso permite:
  - SQLiteStore (hoje)
  - GraphitiStore (futuro)
  - InMemoryStore (testes)
  - PostgresStore (escala)

Protocol (structural typing) ao invés de ABC porque:
  - Não força herança — bibliotecas externas (Graphiti) funcionam se implementarem os métodos
  - Runtime checkable — isinstance() funciona pra validação
  - Mais Pythonic pra Python 3.10+
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryProtocol(Protocol):
    """
    Contrato estável para backends de memória do Seeker.
    
    Todo módulo que acessa memória (DecayEngine, SemanticSearch, 
    FactExtractor, SessionManager, Pipeline) depende deste contrato.
    
    Regras:
      - Métodos keyword-only (*, ) pra segurança — sem confundir ordem de args
      - upsert_fact retorna int (fact_id) — elimina hack de search-after-insert
      - Embeddings e sessão no protocolo — mesmo lifecycle que os fatos
    """

    # ─── Lifecycle ───────────────────────────────────────────

    async def initialize(self) -> None:
        """Inicializa o backend (cria tabelas, conecta, etc)."""
        ...

    async def close(self) -> None:
        """Libera recursos (fecha conexão, etc)."""
        ...

    # ─── Memória Episódica ───────────────────────────────────
    # Eventos: o que aconteceu, quando, com que contexto

    async def record_episode(
        self,
        *,
        session_id: str,
        user_input: str,
        response_summary: str = "",
        depth: str = "deliberate",
        module: str = "none",
        had_arbitrage: bool = False,
        had_conflicts: bool = False,
        cost_usd: float = 0.0,
        latency_ms: int = 0,
        metadata: dict | None = None,
    ) -> None:
        """Registra um episódio de interação."""
        ...

    async def get_recent_episodes(self, limit: int = 10) -> list[dict]:
        """Últimos N episódios, ordem cronológica reversa."""
        ...

    async def search_episodes(self, query: str, limit: int = 5) -> list[dict]:
        """Busca episódios por texto (LIKE)."""
        ...

    async def get_episode_stats(self) -> dict:
        """Estatísticas agregadas: total, custo, latência, por profundidade."""
        ...

    # ─── Memória Semântica ───────────────────────────────────
    # Fatos: o que o Seeker sabe sobre o mundo e o usuário

    async def upsert_fact(
        self,
        *,
        fact: str,
        category: str = "general",
        confidence: float = 0.5,
        source: str = "inferred",
        metadata: dict | None = None,
    ) -> int:
        """
        Insere ou atualiza um fato. Retorna o fact_id.
        
        Se o fato já existe:
          - Incrementa times_seen
          - Atualiza last_seen
          - Boost de confiança (+0.05, cap 0.95)
        """
        ...

    async def get_facts(
        self,
        category: str | None = None,
        min_confidence: float = 0.3,
        limit: int = 20,
    ) -> list[dict]:
        """Fatos filtrados por categoria e confiança mínima."""
        ...

    async def search_facts(self, query: str, limit: int = 10) -> list[dict]:
        """Busca fatos por texto (LIKE). Fallback quando embeddings falham."""
        ...

    async def update_fact_confidence(self, fact_id: int, confidence: float) -> None:
        """Atualiza confiança de um fato. Usado pelo DecayEngine."""
        ...

    async def delete_fact(self, fact_id: int) -> None:
        """Remove fato + embedding associado. Usado pelo DecayEngine."""
        ...

    async def commit(self) -> None:
        """Commit explícito para operações em batch."""
        ...

    # ─── Embeddings ──────────────────────────────────────────
    # Vetores de embedding persistidos — sobrevivem a restarts

    async def store_embedding(self, fact_id: int, vector: list[float]) -> None:
        """Persiste embedding de um fato."""
        ...

    async def load_all_embeddings(self) -> dict[int, list[float]]:
        """Carrega todos os embeddings de uma vez. Chamado no startup."""
        ...

    async def delete_embedding(self, fact_id: int) -> None:
        """Remove embedding de um fato."""
        ...

    # ─── Sessão ──────────────────────────────────────────────
    # Conversação: janela deslizante com persistência

    async def record_session_turn(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """Registra uma mensagem na sessão (user ou assistant)."""
        ...

    async def get_session_turns(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """Últimas N mensagens da sessão, ordem cronológica."""
        ...

    async def cleanup_old_sessions(self, max_age_days: int = 30) -> int:
        """Remove sessões antigas. Retorna quantidade removida."""
        ...

    # ─── Knowledge Graph (Temporal Triples) ──────────────────
    # Sujeito → Predicado → Objeto (com validade temporal)

    async def add_entity(self, name: str, entity_type: str = "unknown", properties: dict | None = None) -> str:
        """Adiciona ou atualiza um nó de entidade. Retorna o entity_id."""
        ...

    async def add_triple(
        self,
        *,
        subject: str,
        predicate: str,
        object_: str,
        valid_from: str | None = None,
        valid_to: str | None = None,
        confidence: float = 1.0,
        source_file: str | None = None,
        source_drawer_id: str | None = None,
        adapter_name: str | None = None,
    ) -> str:
        """Adiciona uma tripla de relacionamento subject → predicate → object."""
        ...

    async def invalidate_triple(self, subject: str, predicate: str, object_: str, ended: str | None = None) -> None:
        """Marca um relacionamento como não mais válido (set valid_to)."""
        ...

    async def query_knowledge(self, entity_name: str, as_of: str | None = None, direction: str = "outgoing") -> list[dict]:
        """Busca relacionamentos de uma entidade."""
        ...

    async def get_knowledge_timeline(self, entity_name: str | None = None, limit: int = 100) -> list[dict]:
        """Timeline cronológica de fatos do grafo."""
        ...

    # ─── Auditoria Temporal ───────────────────────────────────

    async def find_temporal_anomalies(self, limit: int = 5) -> list[dict]:
        """Encontra triplas antigas ou de baixa confiança que podem estar obsoletas."""
        ...

    async def get_verification_context(self) -> str:
        """Gera bloco de texto para o LLM verificar fatos possivelmente obsoletos."""
        ...

    # ─── Contexto para LLM ──────────────────────────────────

    async def format_context(
        self,
        query: str = "",
        limit: int = 10,
        identity: str = "",
        on_demand_category: str | None = None,
    ) -> str:
        """Formata memória usando o 4-Layer Stack (L0-L3)."""
        ...
