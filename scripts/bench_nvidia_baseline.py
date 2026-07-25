"""
bench_nvidia_baseline.py — Coleta baseline de hit-rate do NVIDIA NIM (F-09).

Resolve: F-09 do .planning/phases/00-production-hardening/00-VERIFICATION.md.
Contexto: após T-03 (circuit breaker re-keyed por provider:model), queremos
medir o hit-rate real do NVIDIA NIM em 24h de prod para validar o fix.

Uso:
    python scripts/bench_nvidia_baseline.py --duration 24h
    python scripts/bench_nvidia_baseline.py --duration 1h --output data/nvidia_baseline_1h.json
    python scripts/bench_nvidia_baseline.py --report-from data/nvidia_baseline_24h.json

Saída:
    JSON com hit_rate, calls_total, calls_success, calls_failed, fallback_distribution,
    avg_latency_ms, p95_latency_ms, total_cost_usd.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

# Força UTF-8 no stdout (Windows console default = cp1252)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("seeker.bench.nvidia_baseline")


def parse_duration(s: str) -> float:
    """Converte '24h', '30m', '90s' em segundos."""
    s = s.strip().lower()
    if s.endswith("h"):
        return float(s[:-1]) * 3600
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("s"):
        return float(s[:-1])
    return float(s)


async def collect_live(duration_s: float, sample_interval_s: float = 60.0) -> dict:
    """Coleta métricas de runtime chamando o CascadeAdapter via pipeline stub.

    Estratégia: faz chamadas reais ao cascade em loop, registrando tier_used e latência.
    O CascadeAdapter mantém self.call_history (deque maxlen=100) — usamos isso como fonte.
    """
    from src.providers.cascade_advanced import CascadeAdapter, CascadeTier

    api_keys = {
        "nvidia": "stub-key-for-baseline-collection",
        "groq": "stub",
        "gemini": "stub",
        "deepseek": "stub",
    }

    cascade = CascadeAdapter({}, api_keys)

    log.info(
        f"[bench] Coletando baseline por {duration_s/3600:.1f}h "
        f"(sample_interval={sample_interval_s}s)"
    )

    start = time.monotonic()
    end = start + duration_s
    samples: list[dict] = []
    next_sample = start + sample_interval_s
    call_count = 0

    test_messages = [
        [{"role": "user", "content": "What is 2+2?"}],
        [{"role": "user", "content": "Summarize: Python is a programming language."}],
        [{"role": "user", "content": "Translate 'hello' to Portuguese."}],
    ]

    while time.monotonic() < end:
        # Tenta uma chamada real ao cascade. Se não houver providers reais,
        # cai em degraded mode e marca como tal.
        msg = test_messages[call_count % len(test_messages)]
        call_start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                cascade.call_with_cascade(role="FAST", messages=msg),
                timeout=30.0,
            )
            elapsed_ms = (time.monotonic() - call_start) * 1000
            samples.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "tier_used": result.tier_used.value,
                "success": result.success,
                "latency_ms": elapsed_ms,
                "fallbacks": result.fallbacks_triggered,
                "cost_usd": result.cost_usd,
            })
        except Exception as e:
            elapsed_ms = (time.monotonic() - call_start) * 1000
            samples.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "tier_used": "exception",
                "success": False,
                "latency_ms": elapsed_ms,
                "fallbacks": -1,
                "cost_usd": 0.0,
                "error": str(e)[:200],
            })

        call_count += 1

        if time.monotonic() >= next_sample:
            nim_so_far = [s for s in samples if s["tier_used"] == "tier1_nim"]
            log.info(
                f"[bench] {call_count} calls | "
                f"NIM hit-rate={len(nim_so_far)/call_count:.1%} | "
                f"success={sum(1 for s in samples if s['success'])}/{call_count}"
            )
            next_sample = time.monotonic() + sample_interval_s

        # Throttle: 1 call/2s para não martelar providers
        await asyncio.sleep(2.0)

    return aggregate(samples, duration_s)


def aggregate(samples: list[dict], duration_s: float) -> dict:
    """Computa métricas agregadas dos samples."""
    if not samples:
        return {"error": "no samples collected"}

    total = len(samples)
    successes = [s for s in samples if s["success"]]
    nim_samples = [s for s in samples if s.get("tier_used") == "tier1_nim"]
    nim_successes = [s for s in nim_samples if s["success"]]

    tier_counts = Counter(s["tier_used"] for s in samples)
    fallback_counts = Counter(s.get("fallbacks", 0) for s in samples)
    latencies = sorted(s["latency_ms"] for s in successes)

    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95_idx = int(len(latencies) * 0.95) if latencies else 0
    p95 = latencies[p95_idx] if latencies else 0

    nim_hit_rate = len(nim_samples) / total if total else 0
    nim_success_rate = len(nim_successes) / len(nim_samples) if nim_samples else 0

    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(duration_s, 1),
        "duration_human": f"{duration_s/3600:.1f}h",
        "total_calls": total,
        "total_success": len(successes),
        "total_failed": total - len(successes),
        "overall_success_rate": round(len(successes) / total, 4) if total else 0,
        "nvidia_nim": {
            "calls_attempted": len(nim_samples),
            "calls_success": len(nim_successes),
            "hit_rate": round(nim_hit_rate, 4),
            "success_rate_when_used": round(nim_success_rate, 4),
            "avg_latency_ms": round(mean(s["latency_ms"] for s in nim_samples), 1) if nim_samples else 0,
            "p50_latency_ms": round(p50, 1) if nim_samples else 0,
            "p95_latency_ms": round(p95, 1) if nim_samples else 0,
            "total_cost_usd": round(sum(s["cost_usd"] for s in nim_samples), 6),
        },
        "tier_distribution": dict(tier_counts),
        "fallback_distribution": {str(k): v for k, v in fallback_counts.items()},
        "verdict": _verdict(nim_hit_rate, nim_success_rate),
    }


def _verdict(nim_hit_rate: float, nim_success_rate: float) -> str:
    """Compara contra o threshold de 5% mencionado na UAT item 3."""
    if nim_hit_rate >= 0.05 and nim_success_rate >= 0.5:
        return "PASS — T-03 fix validated (NIM hit-rate >= 5%, success >= 50%)"
    if nim_hit_rate < 0.01:
        return "FAIL — NIM hit-rate < 1% — circuit breaker may be permanently open"
    return f"PARTIAL — NIM hit-rate={nim_hit_rate:.1%}, success={nim_success_rate:.1%}"


def report_from_file(path: Path) -> dict:
    """Relê um JSON já coletado e re-emite o relatório."""
    if not path.exists():
        return {"error": f"file not found: {path}"}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_summary(report: dict) -> None:
    """Imprime o relatório formatado."""
    if "error" in report:
        print(f"❌ {report['error']}")
        return

    print("=" * 60)
    print("NVIDIA NIM Baseline Report (F-09)")
    print("=" * 60)
    print(f"Coletado em:    {report['collected_at']}")
    print(f"Duração:        {report['duration_human']} ({report['duration_s']}s)")
    print(f"Total chamadas: {report['total_calls']}")
    print(f"Sucesso geral:  {report['overall_success_rate']:.1%} ({report['total_success']}/{report['total_calls']})")
    print()
    nim = report["nvidia_nim"]
    print(f"🐢 NVIDIA NIM (TIER1):")
    print(f"   Calls:        {nim['calls_attempted']}")
    print(f"   Hit-rate:     {nim['hit_rate']:.2%}")
    print(f"   Success:      {nim['success_rate_when_used']:.2%}")
    print(f"   Latência avg: {nim['avg_latency_ms']:.0f}ms")
    print(f"   Latência p50: {nim['p50_latency_ms']:.0f}ms")
    print(f"   Latência p95: {nim['p95_latency_ms']:.0f}ms")
    print(f"   Custo:        ${nim['total_cost_usd']:.4f}")
    print()
    print(f"📊 Distribuição de tiers: {report['tier_distribution']}")
    print(f"📊 Distribuição de fallbacks: {report['fallback_distribution']}")
    print()
    print(f"🎯 Verdict: {report['verdict']}")
    print("=" * 60)


async def main_async(args):
    if args.report_from:
        report = report_from_file(Path(args.report_from))
    else:
        duration_s = parse_duration(args.duration)
        report = await collect_live(duration_s, args.sample_interval)

        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            log.info(f"[bench] Relatório salvo em {out}")

    print_summary(report)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "--duration", default="24h",
        help="Duração da coleta (ex: 24h, 1h, 30m, 90s). Default: 24h",
    )
    p.add_argument(
        "--sample-interval", type=float, default=60.0,
        help="Intervalo entre samples em segundos. Default: 60",
    )
    p.add_argument(
        "--output", default="data/nvidia_nim_baseline.json",
        help="Caminho do arquivo JSON de saída",
    )
    p.add_argument(
        "--report-from", default=None,
        help="Re-emite relatório a partir de um JSON existente (não coleta)",
    )
    args = p.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        log.info("[bench] Interrompido pelo usuário")
        sys.exit(130)


if __name__ == "__main__":
    main()
