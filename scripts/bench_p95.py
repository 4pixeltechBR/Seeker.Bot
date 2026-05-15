"""
P95 latency benchmark — synthetic REFLEX path

Measures pipeline overhead (router → phase dispatch → response construction)
on the REFLEX path with a *mocked LLM* so the number reported is the pipeline
itself, not the model. Validates the T-11 fix (extractor moved to background).

Usage:
    python scripts/bench_p95.py           # 100 reqs, default
    python scripts/bench_p95.py --n 500   # 500 reqs
    python scripts/bench_p95.py --warmup 20

Reports P50 / P95 / P99 / mean / max in ms. Exits non-zero if P95 > 5000ms
(matches UAT T-11 acceptance).

Pure measurement script — does NOT call any real LLM, does NOT touch the
network, does NOT load any .env. Safe to run in CI.
"""
import argparse
import asyncio
import os
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Project root on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Avoid loading the real .env / providers
os.environ.setdefault("ASSISTANT_NAME", "BenchBot")
os.environ.setdefault("DEEPSEEK_API_KEY", "fake")
os.environ.setdefault("GEMINI_API_KEY", "fake")
os.environ.setdefault("GROQ_API_KEY", "fake")
os.environ.setdefault("MISTRAL_API_KEY", "fake")
os.environ.setdefault("NVIDIA_API_KEY", "fake")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=100, help="Sample size")
    parser.add_argument("--warmup", type=int, default=10, help="Warmup iterations (discarded)")
    parser.add_argument("--p95-budget-ms", type=float, default=5000.0, help="Max acceptable P95 in ms")
    args = parser.parse_args()

    # Import the REFLEX phase + its inputs after env is set
    from src.core.phases.reflex import ReflexPhase
    from src.core.phases.base import PhaseContext
    from src.core.router.cognitive_load import RoutingDecision, CognitiveDepth, ExecutionMode

    # Mock the router/api_keys — ReflexPhase only uses them to invoke fallbacks
    router = MagicMock()
    api_keys = {}
    reflex = ReflexPhase(router=router, api_keys=api_keys)

    # Patch invoke_with_fallback to a deterministic sleep + canned response
    # so we measure ONLY the pipeline overhead, not the LLM.
    from src.core.phases import reflex as reflex_mod

    fake_response = MagicMock()
    fake_response.text = "ok"
    fake_response.cost_usd = 0.0

    async def _fake_invoke(*args, **kwargs):
        # Simulate a fast model: 50ms server-side
        await asyncio.sleep(0.05)
        return fake_response

    reflex_mod.invoke_with_fallback = _fake_invoke  # type: ignore[assignment]

    # Build a stable PhaseContext template
    def make_ctx(text: str) -> PhaseContext:
        return PhaseContext(
            user_input=text,
            decision=RoutingDecision(
                depth=CognitiveDepth.REFLEX,
                reason="bench",
                execution_mode=ExecutionMode.INTERACTIVE,
            ),
            memory_prompt="",
            session_context="",
            afk_protocol=None,
            execution_mode="interactive",
            intent_card=None,
            vault_context="",
        )

    # Warmup
    for _ in range(args.warmup):
        await reflex.execute(make_ctx("warmup ping"))

    # Measure
    samples_ms: list[float] = []
    for i in range(args.n):
        ctx = make_ctx(f"benchmark request {i}")
        t0 = time.perf_counter()
        await reflex.execute(ctx)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        samples_ms.append(elapsed_ms)

    samples_ms.sort()
    p50 = statistics.median(samples_ms)
    p95 = samples_ms[int(len(samples_ms) * 0.95) - 1]
    p99 = samples_ms[int(len(samples_ms) * 0.99) - 1]
    mean = statistics.mean(samples_ms)
    mx = max(samples_ms)

    print(f"\n=== REFLEX path latency ({args.n} samples, {args.warmup} warmup) ===")
    print(f"  P50:  {p50:7.2f} ms")
    print(f"  P95:  {p95:7.2f} ms")
    print(f"  P99:  {p99:7.2f} ms")
    print(f"  mean: {mean:7.2f} ms")
    print(f"  max:  {mx:7.2f} ms")
    print(f"\n  Budget P95: {args.p95_budget_ms:.0f} ms")
    print(f"  Note: mock LLM adds 50ms floor. Real LLMs add 200-2000ms more.")

    if p95 > args.p95_budget_ms:
        print(f"\n[FAIL] P95={p95:.0f}ms exceeds budget {args.p95_budget_ms:.0f}ms")
        return 1
    print(f"\n[PASS] P95={p95:.0f}ms within budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
