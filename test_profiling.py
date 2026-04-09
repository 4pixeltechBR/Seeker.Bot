#!/usr/bin/env python3
"""Quick test of Performance Profiling System"""

import asyncio
import time
from src.core.profiling.profiler import SystemProfiler
from src.core.profiling.metrics import PerformanceMetrics


async def test_profiling():
    """Teste o sistema de profiling"""
    print("\n" + "=" * 60)
    print("PERFORMANCE PROFILING SYSTEM — TEST")
    print("=" * 60 + "\n")

    profiler = SystemProfiler(history_size=100)

    # Simular 3 fases de processamento
    phases = [
        ("Reflex", 0.5, 100, 50, 0.001, "gemini"),
        ("Deliberate", 2.5, 500, 200, 0.005, "groq"),
        ("Deep", 5.0, 1500, 800, 0.025, "nvidia"),
    ]

    print("[1] Simulando ciclos de processamento...\n")

    for phase_name, duration, tokens_in, tokens_out, cost, provider in phases:
        # Start profiling
        profiler.start_profiling("telegram", phase_name)

        # Simular processamento
        await asyncio.sleep(duration / 1000)  # Converter ms para segundos

        # End profiling
        metric = profiler.end_profiling(
            "telegram", phase_name,
            llm_calls=1,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_usd=cost,
            provider=provider,
            model="default",
            success=True
        )

        print(f"  [{phase_name:12}] {metric.latency_ms:6.0f}ms | "
              f"${metric.cost_usd:.4f} | {metric.total_tokens} tokens | {provider}")

    print("\n[2] Agregações por Goal:\n")

    # Obter estatísticas
    all_stats = profiler.get_all_stats()

    if all_stats:
        total_goals = len(all_stats)
        total_cost = sum(g.total_cost_usd for g in all_stats.values())
        avg_latency = sum(g.avg_latency_ms for g in all_stats.values()) / total_goals
        healthy = sum(1 for g in all_stats.values() if g.success_rate > 80)

        print(f"  Total Goals: {total_goals}")
        print(f"  Healthy Goals: {healthy}")
        print(f"  Health: {(healthy/total_goals*100):.1f}%")
        print(f"  Total Cost: ${total_cost:.4f}")
        print(f"  Avg Latency: {avg_latency:.0f}ms")

    print("\n[3] Worst Offenders (Top 3):\n")

    worst = profiler.get_worst_offenders(limit=3)
    for i, metric in enumerate(worst, 1):
        print(f"  {i}. [{metric.phase_name:12}] "
              f"{metric.latency_ms:6.0f}ms | "
              f"${metric.cost_usd:.4f} | {metric.provider}")

    print("\n[4] Goal Metrics Summary:\n")

    all_stats = profiler.get_all_stats()
    for goal_id, metrics in all_stats.items():
        stats_dict = metrics.to_dict()
        print(f"  Goal: {goal_id}")
        print(f"    Cycles: {stats_dict['cycles']}")
        print(f"    Success: {stats_dict['success_rate']}")
        print(f"    Cost: {stats_dict['total_cost']}")
        print(f"    Avg Latency: {stats_dict['avg_latency_ms']}ms")

    print("\n" + "=" * 60)
    print("TEST COMPLETED SUCCESSFULLY")
    print("=" * 60 + "\n")

    print("Next steps:")
    print("  1. Start the bot: python -m src")
    print("  2. In Telegram: /perf")
    print("  3. In Telegram: /perf_detailed")


if __name__ == "__main__":
    asyncio.run(test_profiling())
