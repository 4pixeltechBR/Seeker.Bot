"""
Seeker.Bot — Test Persistent Compressor
tests/test_compressor_persistent.py
"""

import os
import asyncio
import unittest
from unittest.mock import AsyncMock
from src.core.memory.session_store import SessionStore
from src.core.memory.compressor import SessionCompressor
from config.models import build_default_router


class TestPersistentCompressor(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db_file = os.path.join(os.path.dirname(__file__), "temp_session.db")
        if os.path.exists(self.db_file):
            os.remove(self.db_file)

        # Instancia SessionStore temporário
        self.store = SessionStore(db_path=self.db_file)

        # Mock ModelRouter e api_keys
        self.model_router = build_default_router()
        self.api_keys = {"gemini": "mock_key"}

        # Instancia SessionCompressor com limites baixos para teste rápido
        self.compressor = SessionCompressor(
            model_router=self.model_router,
            api_keys=self.api_keys,
            session_store=self.store,
            compress_after_turns=4,
            keep_recent_turns=2
        )

        # Mocka a chamada interna do modelo de compressão para não bater na API externa
        self.mock_compress_result = "[Estado] Tudo funcionando\n[Tarefas] Testar compressor"
        self.compressor._compress = AsyncMock(return_value=self.mock_compress_result)

    def tearDown(self):
        # Fechamento seguro do banco de dados antes da remoção
        async def cleanup():
            await self.store.close()
            if os.path.exists(self.db_file):
                try:
                    os.remove(self.db_file)
                except Exception:
                    pass
        
        # Como o tearDown em IsolatedAsyncioTestCase aguarda corrotinas se usarmos um loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(cleanup())
        else:
            asyncio.run(cleanup())

    async def test_compress_and_cleanup(self):
        session_id = "test_session_123"

        # Simula a adição de 5 turnos de conversa no SQLite
        for i in range(5):
            role = "user" if i % 2 == 0 else "assistant"
            content = f"Mensagem numero {i}"
            await self.store.record_session_turn(
                session_id=session_id,
                role=role,
                content=content
            )

        # Recupera as turns gravadas
        turns = await self.store.get_session_turns(session_id, limit=10)
        self.assertEqual(len(turns), 5)

        # Executa maybe_compress (limite é 4, keep_recent é 2)
        compressed_turns = await self.compressor.maybe_compress(session_id, turns)

        # Deve retornar: 1 turn de sistema (resumo) + 2 turns recentes = 3 turns
        self.assertEqual(len(compressed_turns), 3)
        self.assertEqual(compressed_turns[0]["role"], "system")
        self.assertIn("[CONTEXTO COMPRIMIDO]", compressed_turns[0]["content"])

        # Verifica se o resumo foi persistido no banco de dados
        saved_summary = await self.store.get_summary(session_id)
        self.assertEqual(saved_summary, self.mock_compress_result)

        # Verifica se o SQLite foi limpo de turnos antigos, mantendo apenas 2 mais recentes
        db_turns = await self.store.get_session_turns(session_id, limit=10)
        self.assertEqual(len(db_turns), 2)
        self.assertEqual(db_turns[0]["content"], "Mensagem numero 3")
        self.assertEqual(db_turns[1]["content"], "Mensagem numero 4")

    async def test_incremental_compression_includes_previous_summary(self):
        session_id = "test_session_456"

        # Define resumo pré-existente
        await self.store.store_summary(session_id, "[Estado] Iniciado\n[Decisões] Nenhuma")

        # Mocka a chamada _compress para observar o que foi enviado nela
        captured_history = []
        async def spy_compress(history_text):
            captured_history.append(history_text)
            return "[Estado] Atualizado"

        self.compressor._compress = spy_compress

        # Cria 5 turns
        turns = []
        for i in range(5):
            turns.append({"role": "user", "content": f"Mensagem {i}"})

        # Comprime
        await self.compressor.maybe_compress(session_id, turns)

        # O compressor deve ter incluído o resumo anterior
        self.assertTrue(len(captured_history) > 0)
        self.assertIn("RESUMO ANTERIOR:", captured_history[0])
        self.assertIn("[Estado] Iniciado", captured_history[0])
        self.assertIn("NOVOS TURNOS:", captured_history[0])


if __name__ == "__main__":
    unittest.main()
