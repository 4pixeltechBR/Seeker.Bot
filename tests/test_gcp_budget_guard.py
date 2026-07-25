"""
Tests para o sistema de billing guard GCP.

Cobre:
  1. Persistência (sobrevive a restart)
  2. Reset automático em nova janela (diária/mensal)
  3. Hard cap (BudgetExceededError)
  4. Circuit breaker após 3 over-cap attempts
  5. Desabilitação manual via set_enabled
  6. Fallback registry
  7. Alertas preditivos
  8. Vídeo-real: Vision API com fallback MediaPipe
"""

import asyncio
import json
import os
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def temp_usage_path():
    """Cria um arquivo de uso temporário e força o guard a usá-lo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "gcp_usage.json"
        with patch("src.core.billing.gcp_budget_guard._usage_path", return_value=path):
            # Reset singleton a cada teste
            from src.core.billing import gcp_budget_guard
            gcp_budget_guard.GCPBudgetGuard._instance = None
            yield path
            gcp_budget_guard.GCPBudgetGuard._instance = None


# ── 1. Persistência ───────────────────────────────────────────────────

def test_guard_loads_persistent_state(temp_usage_path):
    """Estado deve sobreviver a restart."""
    path = temp_usage_path
    path.write_text(json.dumps({
        "usage": {
            "youtube_data_api_v3": {
                "service": "youtube_data_api_v3",
                "window_start": time.time(),
                "units_used": 1234,
                "call_count": 50,
                "fallback_count": 0,
                "over_cap_count": 0,
                "last_call_ts": time.time(),
                "last_error": "",
            }
        },
        "disabled_until": {},
        "alerts_sent": {},
    }))
    from src.core.billing.gcp_budget_guard import GCPBudgetGuard
    guard = GCPBudgetGuard.get()
    assert guard.usage["youtube_data_api_v3"].units_used == 1234


# ── 2. Reset de janela ────────────────────────────────────────────────

def test_daily_window_resets_after_period():
    """Janela antiga deve resetar quando _ensure_current_window é chamada."""
    from src.core.billing.gcp_budget_guard import GCPBudgetGuard, UsageRecord
    from src.core.billing import gcp_budget_guard as mod
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "gcp_usage.json"
        with patch.object(mod, "_usage_path", return_value=path):
            mod.GCPBudgetGuard._instance = None
            guard = GCPBudgetGuard.get()
            long_ago = time.time() - 2 * 86400  # 2 dias atrás
            guard.usage["youtube_data_api_v3"] = UsageRecord(
                service="youtube_data_api_v3", window_start=long_ago, units_used=9999,
            )
            guard._ensure_current_window("youtube_data_api_v3", time.time())
            assert guard.usage["youtube_data_api_v3"].units_used == 0
        mod.GCPBudgetGuard._instance = None


# ── 3. Hard cap ────────────────────────────────────────────────────────

def test_safe_cap_blocks_exceeding_consumption(temp_usage_path):
    """Tentar consumir além do safe_cap deve levantar BudgetExceededError."""
    from src.core.billing.gcp_budget_guard import GCPBudgetGuard, BudgetExceededError
    guard = GCPBudgetGuard.get()
    safe_cap = guard.budgets["cloud_vision"].safe_cap

    async def run():
        # Consome todo o safe_cap
        await guard.consume("cloud_vision", safe_cap)
        # Tenta consumir mais 1 → deve falhar
        with pytest.raises(BudgetExceededError):
            await guard.consume("cloud_vision", 1)

    asyncio.run(run())


# ── 4. Circuit breaker ─────────────────────────────────────────────────

def test_circuit_breaker_after_3_over_cap_attempts(temp_usage_path):
    """3 over-cap attempts → service disabled por 1h."""
    from src.core.billing.gcp_budget_guard import GCPBudgetGuard, BudgetExceededError, ServiceDisabledError
    guard = GCPBudgetGuard.get()
    safe_cap = guard.budgets["cloud_text_to_speech"].safe_cap

    async def run():
        await guard.consume("cloud_text_to_speech", safe_cap)

        for _ in range(3):
            with pytest.raises(BudgetExceededError):
                await guard.consume("cloud_text_to_speech", 1)

        # 4ª tentativa → service disabled
        with pytest.raises(ServiceDisabledError):
            await guard.consume("cloud_text_to_speech", 1)

        assert "cloud_text_to_speech" in guard.disabled_until
        assert guard.disabled_until["cloud_text_to_speech"] > time.time()

    asyncio.run(run())


# ── 5. Desabilitação manual ─────────────────────────────────────────────

def test_manual_disable_blocks_calls(temp_usage_path):
    """set_enabled(False) deve bloquear todas as chamadas."""
    from src.core.billing.gcp_budget_guard import GCPBudgetGuard, ServiceDisabledError
    guard = GCPBudgetGuard.get()

    async def run():
        guard.set_enabled("places_api", False)
        with pytest.raises(ServiceDisabledError):
            await guard.consume("places_api", 1)

    asyncio.run(run())


# ── 6. Fallback registry ───────────────────────────────────────────────

def test_fallback_chain_order():
    """Chain de fallbacks deve estar ordenada conforme registrado."""
    from src.core.billing.gcp_budget_guard import GCPBudgetGuard
    from src.core.billing.fallback_registry import register_all_fallbacks, get_chain
    from src.core.billing import gcp_budget_guard as mod
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "gcp_usage.json"
        with patch.object(mod, "_usage_path", return_value=path):
            mod.GCPBudgetGuard._instance = None
            register_all_fallbacks()
            guard = GCPBudgetGuard.get()
            chain = get_chain("analyze_thumbnail")
            assert chain == ["cloud_vision", "mediapipe_local", "opencv_heuristic"]
            fallbacks = guard.get_fallbacks("analyze_thumbnail")
            assert len(fallbacks) == 3
        mod.GCPBudgetGuard._instance = None


# ── 7. Alertas preditivos ──────────────────────────────────────────────

def test_alert_at_80_percent(temp_usage_path):
    """Deve gerar alerta quando uso passa de 80% do safe_cap."""
    from src.core.billing.gcp_budget_guard import GCPBudgetGuard
    guard = GCPBudgetGuard.get()
    safe_cap = guard.budgets["cloud_vision"].safe_cap

    async def run():
        # Consome exatamente 85% do safe_cap
        await guard.consume("cloud_vision", int(safe_cap * 0.85))
        alerts = await guard.check_alerts()
        assert any("80%" in a or "Cloud Vision" in a for a in alerts), \
            f"Esperava alerta de Vision, recebi: {alerts}"

    asyncio.run(run())


# ── 8. Smoke real: Cloud Vision com fallback ──────────────────────────

@pytest.mark.asyncio
async def test_real_cloud_vision_with_real_fallback():
    """Testa Vision real e fallback MediaPipe contra YouTube thumbnail."""
    from dotenv import load_dotenv
    load_dotenv(r"E:\Seeker.Bot\config\.env")
    if not os.getenv("GOOGLE_CLOUD_API_KEY"):
        pytest.skip("GOOGLE_CLOUD_API_KEY não configurada")

    from src.core.billing.fallback_registry import register_all_fallbacks
    from src.core.billing.gcp_budget_guard import GCPBudgetGuard
    from src.core.billing import gcp_budget_guard as mod
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "gcp_usage.json"
        with patch.object(mod, "_usage_path", return_value=path):
            mod.GCPBudgetGuard._instance = None
            register_all_fallbacks()
            guard = GCPBudgetGuard.get()
            test_video_id = "dQw4w9WgXcQ"

            # Tenta Vision primeiro
            vision_ok = False
            try:
                allowed = await guard.consume("cloud_vision", 1)
                if allowed:
                    import aiohttp, base64
                    api_key = os.getenv("GOOGLE_CLOUD_API_KEY")
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"https://img.youtube.com/vi/{test_video_id}/hqdefault.jpg",
                            timeout=aiohttp.ClientTimeout(total=5),
                        ) as resp:
                            img_bytes = await resp.read()
                        url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
                        payload = {"requests": [{
                            "image": {"content": base64.b64encode(img_bytes).decode()},
                            "features": [{"type": "LABEL_DETECTION", "maxResults": 3}],
                        }]}
                        async with session.post(url, json=payload) as resp2:
                            data = await resp2.json()
                            if resp2.status == 200:
                                labels = [l["description"] for l in data["responses"][0].get("labelAnnotations", [])]
                                assert len(labels) > 0
                                vision_ok = True
                                await guard.record_call_success("cloud_vision", 1)
            except Exception:
                pass

            if not vision_ok:
                # Fallback: MediaPipe local (posição 1)
                fallbacks = guard.get_fallbacks("analyze_thumbnail")
                assert len(fallbacks) >= 2
                result = await fallbacks[1](test_video_id)
                assert result["score"] > 0
                await guard.record_fallback("cloud_vision")
        mod.GCPBudgetGuard._instance = None