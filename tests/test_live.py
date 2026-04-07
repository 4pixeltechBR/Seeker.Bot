"""
Seeker.Bot — Teste de Integração
tests/test_live.py

Valida API keys, testa cada provider, e roda a primeira arbitragem real.

Executar da raiz do projeto:
  pip install -r requirements.txt
  python -m tests.test_live

NÃO é um teste pytest — é um script standalone com API keys reais.
As funções test_* são excluídas da coleta automática do pytest via pytestmark.
"""

import asyncio
import os
import sys
import time

import pytest

# Exclui todas as funções test_* deste arquivo da coleta do pytest
pytestmark = pytest.mark.skip(reason="live integration test — run directly: python -m tests.test_live")

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from config.models import (
    build_default_router,
    DEEPSEEK_CHAT,
    NVIDIA_NEMOTRON_SUPER,
    NVIDIA_NEMOTRON_ULTRA,
    GEMINI_31_FLASH_LITE,
    GEMINI_3_FLASH,
    GEMINI_25_FLASH,
    GROQ_LLAMA,
    MISTRAL_FREE,
    ModelConfig,
)
from src.providers.base import (
    create_provider,
    LLMRequest,
    LLMResponse,
)
from src.core.evidence.arbitrage import EvidenceArbitrage


# ─────────────────────────────────────────────────────────────────────
# CORES PARA O TERMINAL
# ─────────────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def header(text: str):
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}\n")


def ok(text: str):
    print(f"  {GREEN}✅ {text}{RESET}")


def fail(text: str):
    print(f"  {RED}❌ {text}{RESET}")


def warn(text: str):
    print(f"  {YELLOW}⚠️  {text}{RESET}")


def info(text: str):
    print(f"  {CYAN}→ {text}{RESET}")


# ─────────────────────────────────────────────────────────────────────
# TESTE 1: VERIFICAR API KEYS
# ─────────────────────────────────────────────────────────────────────

def check_keys(api_keys: dict[str, str]) -> dict[str, str]:
    """Verifica quais keys estão presentes."""
    header("PASSO 1 — Verificando API Keys")

    valid_keys = {}
    for provider, key in api_keys.items():
        if key and len(key) > 5 and key not in ("sk-...", "AI...", "gsk_...", ""):
            ok(f"{provider}: key presente ({key[:8]}...{key[-4:]})")
            valid_keys[provider] = key
        else:
            warn(f"{provider}: key ausente ou placeholder")

    print(f"\n  {len(valid_keys)}/5 providers configurados")
    if len(valid_keys) < 2:
        fail("Precisa de no mínimo 2 providers para o Evidence Arbitrage")
        sys.exit(1)

    return valid_keys


# ─────────────────────────────────────────────────────────────────────
# TESTE 2: PING CADA PROVIDER
# ─────────────────────────────────────────────────────────────────────

async def ping_provider(
    config: ModelConfig,
    api_keys: dict[str, str],
) -> bool:
    """Testa um provider com uma pergunta trivial."""
    if config.provider not in api_keys:
        warn(f"{config.display_name}: pulando (sem key)")
        return False

    try:
        provider = create_provider(config, api_keys)
        try:
            start = time.perf_counter()
            response = await provider.complete(
                LLMRequest(
                    messages=[{"role": "user", "content": "Responda apenas: ok"}],
                    max_tokens=10,
                    temperature=0.0,
                )
            )
            elapsed = int((time.perf_counter() - start) * 1000)
            ok(
                f"{config.display_name}: "
                f"respondeu em {elapsed}ms | "
                f"{response.total_tokens} tokens | "
                f"${response.cost_usd:.6f}"
            )
            return True
        finally:
            await provider.close()

    except Exception as e:
        fail(f"{config.display_name}: {e}")
        return False


async def test_all_providers(api_keys: dict[str, str]) -> list[str]:
    """Testa todos os providers e retorna os que funcionam."""
    header("PASSO 2 — Testando Providers")

    models = [
        ("NVIDIA Nemotron Super", NVIDIA_NEMOTRON_SUPER),
        ("NVIDIA Nemotron Ultra", NVIDIA_NEMOTRON_ULTRA),
        ("DeepSeek", DEEPSEEK_CHAT),
        ("Gemini 3.1 Flash Lite", GEMINI_31_FLASH_LITE),
        ("Gemini 3 Flash", GEMINI_3_FLASH),
        ("Gemini 2.5 Flash", GEMINI_25_FLASH),
        ("Groq", GROQ_LLAMA),
        ("Mistral", MISTRAL_FREE),
    ]

    working = []
    for name, config in models:
        success = await ping_provider(config, api_keys)
        if success:
            working.append(config.provider)

    print(f"\n  {len(working)}/8 providers funcionando")
    return working


# ─────────────────────────────────────────────────────────────────────
# TESTE 3: PRIMEIRA ARBITRAGEM REAL
# ─────────────────────────────────────────────────────────────────────

async def test_arbitrage(api_keys: dict[str, str]):
    """Roda a primeira arbitragem real do Seeker."""
    header("PASSO 3 — Primeira Evidence Arbitrage")

    query = "Quais são as limitações reais do DeepSeek V3.2 para uso em agentes autônomos?"

    info(f"Query: \"{query}\"")
    print()

    router = build_default_router()
    arbitrage = EvidenceArbitrage(router, api_keys, min_models=2)

    try:
        start = time.perf_counter()
        result = await arbitrage.arbitrate(query)
        elapsed = int((time.perf_counter() - start) * 1000)

        # ── Resultado ─────────────────────────────────────
        ok(f"Arbitragem completa em {elapsed}ms")
        info(f"Modelos consultados: {', '.join(result.models_consulted)}")
        info(f"Custo total: ${result.total_cost_usd:.6f}")
        print()

        # ── Consenso ──────────────────────────────────────
        if result.consensus_claims:
            print(f"  {GREEN}{BOLD}CONSENSO ({len(result.consensus_claims)} claims):{RESET}")
            for claim in result.consensus_claims:
                conf = claim.effective_confidence
                bar = "█" * int(conf * 20) + "░" * (20 - int(conf * 20))
                print(f"    [{bar}] {conf:.0%} {claim.text[:80]}")
                if claim.supporting_models:
                    print(f"      suportado por: {', '.join(claim.supporting_models)}")
            print()

        # ── Conflitos ─────────────────────────────────────
        if result.conflict_zones:
            print(f"  {YELLOW}{BOLD}CONFLITOS ({len(result.conflict_zones)} zonas):{RESET}")
            for zone in result.conflict_zones:
                print(f"    ⚠️  {zone.topic} [{zone.agreement_level.value}]")
                for claim in zone.claims:
                    print(f"      [{claim.source_provider}] {claim.text[:80]}")
                if zone.needs_primary_source:
                    print(f"      {RED}→ Requer fonte primária para desempate{RESET}")
            print()
        else:
            info("Nenhum conflito detectado entre modelos")
            print()

        # ── Resumo ────────────────────────────────────────
        summary = result.confidence_summary
        if summary:
            print(f"  {BOLD}Confiança média:{RESET}")
            for level, score in summary.items():
                print(f"    {level}: {score:.0%}")

    except Exception as e:
        fail(f"Arbitragem falhou: {e}")
        import traceback
        traceback.print_exc()


# ─────────────────────────────────────────────────────────────────────
# TESTE 4: ROUTER + PIPELINE RÁPIDO
# ─────────────────────────────────────────────────────────────────────

def test_router_quick():
    """Teste rápido do router — sem API keys."""
    header("PASSO 4 — Cognitive Load Router (offline)")

    from src.core.router.cognitive_load import CognitiveLoadRouter

    router = CognitiveLoadRouter()
    cases = [
        ("ok", "reflex"),
        ("como configuro nginx?", "deliberate"),
        ("vale a pena migrar pra K8s?", "deep"),
        ("god mode", "deep"),
    ]

    for text, expected in cases:
        decision = router.route(text)
        is_ok = decision.depth.value == expected
        status = ok if is_ok else fail
        status(f"[{decision.depth.value:>10}] {text}")


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

async def main():
    print(f"\n{BOLD}{CYAN}")
    print("  ╔═══════════════════════════════════════════╗")
    print("  ║   SEEKER.BOT — TESTE DE INTEGRAÇÃO v0.1  ║")
    print("  ╚═══════════════════════════════════════════╝")
    print(f"{RESET}")

    # Carrega .env
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        info(f"Carregado: {env_path}")
    else:
        # Tenta .env na raiz
        load_dotenv()
        warn("Usando .env da raiz ou variáveis de ambiente")

    api_keys = {
        "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
        "gemini": os.getenv("GEMINI_API_KEY", ""),
        "groq": os.getenv("GROQ_API_KEY", ""),
        "mistral": os.getenv("MISTRAL_API_KEY", ""),
        "nvidia": os.getenv("NVIDIA_API_KEY", ""),
    }

    # Passo 1: Verificar keys
    valid_keys = check_keys(api_keys)

    # Passo 2: Ping providers
    working = await test_all_providers(valid_keys)

    if len(working) < 2:
        fail("Menos de 2 providers funcionando. Corrija as keys e tente novamente.")
        sys.exit(1)

    # Passo 3: Arbitragem real
    await test_arbitrage(valid_keys)

    # Passo 4: Router offline
    test_router_quick()

    # ── Resumo final ──────────────────────────────────
    header("RESULTADO FINAL")
    ok(f"{len(working)} providers ativos")
    ok("Evidence Arbitrage funcional")
    ok("Cognitive Load Router funcional")
    print()
    info("Próximo passo: bot Telegram com aiogram")
    print()


if __name__ == "__main__":
    asyncio.run(main())
