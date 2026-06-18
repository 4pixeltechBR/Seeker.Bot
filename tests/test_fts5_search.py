import os
import pytest
import tempfile
from src.core.memory.session_store import SessionStore

@pytest.mark.anyio
async def test_fts5_search_flow():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_session.db")
        store = SessionStore(db_path=db_path)
        
        # 1. Inicializa o banco
        await store.init()
        
        # 2. Grava algumas mensagens
        session_id = "test_session_1"
        await store.record_session_turn(
            session_id=session_id,
            role="user",
            content="Eu gosto de jogar futebol aos sábados e comer pizza."
        )
        await store.record_session_turn(
            session_id=session_id,
            role="assistant",
            content="Que legal! Futebol e pizza é uma ótima combinação."
        )
        await store.record_session_turn(
            session_id=session_id,
            role="user",
            content="Amanhã vou assistir o jogo do Flamengo."
        )
        
        # 3. Testa a busca FTS5 (busca exata)
        # Deve achar o turno sobre Flamengo
        results_flamengo = await store.search_session_turns(query="Flamengo", session_id=session_id)
        assert len(results_flamengo) == 1
        assert "Flamengo" in results_flamengo[0]["content"]
        
        # Deve achar os dois turnos sobre futebol (ou pizza)
        results_futebol = await store.search_session_turns(query="futebol", session_id=session_id)
        assert len(results_futebol) == 2
        
        # 4. Testa busca com query que não existe
        results_inexistent = await store.search_session_turns(query="Palmeiras", session_id=session_id)
        assert len(results_inexistent) == 0
        
        # 5. Testa busca sem especificar session_id (busca global)
        results_global = await store.search_session_turns(query="pizza")
        assert len(results_global) == 2
        
        # 6. Deleta a sessão e verifica se FTS5 limpou
        await store.delete_session(session_id)
        results_after_delete = await store.search_session_turns(query="futebol")
        assert len(results_after_delete) == 0
        
        await store.close()
