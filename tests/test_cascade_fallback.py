import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from config.models import ModelConfig, CognitiveRole, ModelRouter
from src.providers.cascade import CascadeAdapter, CascadeRole
from src.providers.base import LLMRequest, LLMResponse


class TestCascadeFallback(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Configuração de modelos para teste de rota
        self.model_a = ModelConfig(
            provider="nvidia",
            model_id="test-model-a",
            display_name="Test Model A",
            rpm_limit=40,
        )
        self.model_b = ModelConfig(
            provider="groq",
            model_id="test-model-b",
            display_name="Test Model B",
            rpm_limit=30,
        )
        self.model_c = ModelConfig(
            provider="gemini",
            model_id="test-model-c",
            display_name="Test Model C",
            rpm_limit=15,
        )

        self.model_router = ModelRouter(
            routes={
                CognitiveRole.FAST: [self.model_a, self.model_b],
                CognitiveRole.SYNTHESIS: [self.model_c],
            }
        )
        self.api_keys = {"nvidia": "key-a", "groq": "key-b", "gemini": "key-c"}
        self.cascade = CascadeAdapter(self.model_router, self.api_keys)

    @patch("src.providers.base.create_provider")
    async def test_successful_first_tier(self, mock_create_provider):
        # Simula sucesso no primeiro provedor (NVIDIA)
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(
            return_value=LLMResponse(
                text="Sucesso A",
                model="test-model-a",
                provider="nvidia",
            )
        )
        mock_create_provider.return_value = mock_provider

        result = await self.cascade.call(
            role=CascadeRole.FAST,
            messages=[{"role": "user", "content": "Olá"}],
        )

        self.assertEqual(result["content"], "Sucesso A")
        self.assertEqual(result["provider"], "nvidia")
        self.assertEqual(result["model"], "Test Model A")
        self.assertEqual(result["tier"], 1)

    @patch("src.providers.base.create_provider")
    async def test_fallback_on_429_error(self, mock_create_provider):
        # Simula erro HTTP 429 no provedor A
        mock_provider_a = MagicMock()
        mock_response_429 = httpx.Response(429, request=httpx.Request("POST", "http://test"))
        mock_provider_a.complete = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Rate limit exceeded",
                request=mock_response_429.request,
                response=mock_response_429,
            )
        )

        # Simula sucesso no provedor B (Groq)
        mock_provider_b = MagicMock()
        mock_provider_b.complete = AsyncMock(
            return_value=LLMResponse(
                text="Sucesso B",
                model="test-model-b",
                provider="groq",
            )
        )

        def side_effect_create(model, api_keys):
            if model.provider == "nvidia":
                return mock_provider_a
            elif model.provider == "groq":
                return mock_provider_b
            return MagicMock()

        mock_create_provider.side_effect = side_effect_create

        result = await self.cascade.call(
            role=CascadeRole.FAST,
            messages=[{"role": "user", "content": "Olá"}],
        )

        # Deve pular NVIDIA e acionar Groq
        self.assertEqual(result["content"], "Sucesso B")
        self.assertEqual(result["provider"], "groq")
        self.assertEqual(result["model"], "Test Model B")
        self.assertEqual(result["tier"], 2)

    @patch("src.providers.base.create_provider")
    async def test_fallback_on_timeout(self, mock_create_provider):
        # Simula timeout de conexão no provedor A
        mock_provider_a = MagicMock()
        mock_provider_a.complete = AsyncMock(side_effect=asyncio.TimeoutError("Timeout"))

        # Provedor B responde com sucesso
        mock_provider_b = MagicMock()
        mock_provider_b.complete = AsyncMock(
            return_value=LLMResponse(
                text="Sucesso B via Timeout",
                model="test-model-b",
                provider="groq",
            )
        )

        def side_effect_create(model, api_keys):
            if model.provider == "nvidia":
                return mock_provider_a
            elif model.provider == "groq":
                return mock_provider_b
            return MagicMock()

        mock_create_provider.side_effect = side_effect_create

        result = await self.cascade.call(
            role=CascadeRole.FAST,
            messages=[{"role": "user", "content": "Olá"}],
        )

        self.assertEqual(result["content"], "Sucesso B via Timeout")
        self.assertEqual(result["provider"], "groq")
        self.assertEqual(result["tier"], 2)


if __name__ == "__main__":
    unittest.main()
