"""
Seeker.Bot — Test Shared Rate Limit Breaker
tests/test_shared_breaker.py
"""

import os
import time
import asyncio
import unittest
from src.core.rate_limiting.shared_breaker import SharedRateLimitBreaker


class TestSharedRateLimitBreaker(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_file = os.path.join(os.path.dirname(__file__), "temp_rate_limits.json")
        if os.path.exists(self.test_file):
            os.remove(self.test_file)
        
        # Cria breaker com threshold pequeno (2 falhas) e cooldown de 2 segundos
        self.breaker = SharedRateLimitBreaker(
            filepath=self.test_file,
            consecutive_threshold=2,
            cooldown_seconds=2
        )

    def tearDown(self):
        if os.path.exists(self.test_file):
            try:
                os.remove(self.test_file)
            except Exception:
                pass

    async def test_initial_state(self):
        # Inicialmente, não deve estar bloqueado
        self.assertFalse(await self.breaker.is_blocked("test_api"))

    async def test_single_failure_does_not_block(self):
        # 1 falha não atinge o threshold (2)
        await self.breaker.record_failure("test_api", 429)
        self.assertFalse(await self.breaker.is_blocked("test_api"))

    async def test_threshold_reached_blocks(self):
        # 2 falhas consecutivas atinge o threshold
        await self.breaker.record_failure("test_api", 429)
        await self.breaker.record_failure("test_api", 429)
        self.assertTrue(await self.breaker.is_blocked("test_api"))

    async def test_success_resets_cooldown(self):
        # Ativa o bloqueio
        await self.breaker.record_failure("test_api", 429)
        await self.breaker.record_failure("test_api", 429)
        self.assertTrue(await self.breaker.is_blocked("test_api"))

        # Sucesso deve resetar imediatamente
        await self.breaker.record_success("test_api")
        self.assertFalse(await self.breaker.is_blocked("test_api"))

    async def test_cooldown_expires(self):
        # Ativa o bloqueio com cooldown curto (2s)
        await self.breaker.record_failure("test_api", 429)
        await self.breaker.record_failure("test_api", 429)
        self.assertTrue(await self.breaker.is_blocked("test_api"))

        # Aguarda expirar
        await asyncio.sleep(2.1)
        self.assertFalse(await self.breaker.is_blocked("test_api"))


if __name__ == "__main__":
    unittest.main()
