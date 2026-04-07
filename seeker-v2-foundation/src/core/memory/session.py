"""
Seeker.Bot — Session Manager
src/core/memory/session.py

Janela deslizante de conversação com persistência.

Sem isso, cada mensagem é uma ilha. "E o custo disso?" não tem referente.
Com isso, o Seeker mantém contexto entre mensagens e entre restarts.

Design:
  - RAM: cache das últimas N turns por sessão (acesso rápido)
  - SQLite: persistência (sobrevive a restart)
  - Formatação inteligente: últimas 3 trocas com conteúdo, anteriores só input
  - Cleanup automático via DecayEngine (30 dias)
  
Pré-requisito para:
  - Multi-turn investigation (Fase 3)
  - Proactive Research baseada em padrões (Fase 4)
  - Continuidade entre sessões
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.memory.protocol import MemoryProtocol

log = logging.getLogger("seeker.memory.session")


class SessionManager:
    """
    Janela deslizante de conversação.

    Uso:
        session = SessionManager(memory)
        await session.load_session("telegram")
        
        # Quando recebe mensagem:
        await session.add_turn("telegram", "user", "como funciona o arbitrage?")
        context = session.format_context("telegram")
        # → injeta no system prompt
        
        # Depois de responder:
        await session.add_turn("telegram", "assistant", "O Evidence Arbitrage...")
    """

    def __init__(
        self,
        memory: "MemoryProtocol",
        window_size: int = 10,
        max_context_chars: int = 4000,
    ):
        """
        Args:
            memory: Backend de memória (MemoryProtocol)
            window_size: Quantas TROCAS manter (user+assistant = 1 troca)
            max_context_chars: Limite de caracteres no contexto formatado
        """
        self.memory = memory
        self.window_size = window_size
        self.max_context_chars = max_context_chars
        self._cache: dict[str, list[dict]] = {}

    async def load_session(self, session_id: str) -> None:
        """Carrega sessão do SQLite pro cache. Chamado no startup."""
        turns = await self.memory.get_session_turns(
            session_id,
            limit=self.window_size * 2,  # user + assistant
        )
        self._cache[session_id] = turns
        if turns:
            log.info(f"[session] Carregada: {session_id} ({len(turns)} turns)")

    async def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """
        Adiciona mensagem à sessão (RAM + SQLite).
        Chamado para user e assistant.
        """
        # Persiste
        await self.memory.record_session_turn(
            session_id=session_id,
            role=role,
            content=content,
        )

        # Atualiza cache
        if session_id not in self._cache:
            self._cache[session_id] = []

        self._cache[session_id].append({
            "role": role,
            "content": content[:2000],
        })

        # Trim — mantém janela deslizante
        max_turns = self.window_size * 2
        if len(self._cache[session_id]) > max_turns:
            self._cache[session_id] = self._cache[session_id][-max_turns:]

    def format_context(self, session_id: str) -> str:
        """
        Formata o histórico da sessão para o system prompt.

        Não despeja tudo — resumo inteligente:
        - Últimas 3 trocas: conteúdo completo (truncado a 300 chars)
        - Trocas anteriores: apenas o input do usuário (contexto mínimo)
        
        Isso mantém o contexto relevante sem explodir o prompt.
        """
        turns = self._cache.get(session_id, [])
        if not turns:
            return ""

        lines = ["=== CONVERSA RECENTE ==="]
        total_chars = 0

        # Divide em "recente" (últimas 3 trocas) e "contexto" (antes)
        recent_count = 6  # 3 trocas × 2 (user + assistant)
        recent = turns[-recent_count:]
        older = turns[:-recent_count] if len(turns) > recent_count else []

        # Contexto antigo: só inputs do usuário (resumo mínimo)
        for turn in older:
            if turn["role"] == "user":
                line = f"[anterior] {turn['content'][:100]}"
                total_chars += len(line)
                if total_chars > self.max_context_chars:
                    break
                lines.append(line)

        # Recente: conteúdo completo (truncado)
        for turn in recent:
            icon = "👤" if turn["role"] == "user" else "🤖"
            content = turn["content"][:300]
            line = f"{icon} {content}"
            total_chars += len(line)
            if total_chars > self.max_context_chars:
                break
            lines.append(line)

        return "\n".join(lines)

    def has_context(self, session_id: str) -> bool:
        """Verifica se há contexto de sessão disponível."""
        turns = self._cache.get(session_id, [])
        return len(turns) > 0

    @property
    def active_sessions(self) -> list[str]:
        """Lista de sessões com contexto em cache."""
        return [sid for sid, turns in self._cache.items() if turns]
