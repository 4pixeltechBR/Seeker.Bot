#!/usr/bin/env python3
"""
Run benchmarks for all 3 available models and generate final comparison report.
"""

import subprocess
import json
import os
from datetime import datetime
from pathlib import Path

os.chdir("E:\Seeker.Bot")

MODELS = [
    "qwen3.5:4b",
    "qwen3-vl:8b", 
    "minicpm-v"
]

print("=" * 80)
print("VISION 2.0 — FINAL BENCHMARK SUITE FOR 3/4 MODELS")
print("=" * 80)
print(f"Data: {datetime.now().isoformat()}")
print()

# Run benchmarks for each model
results = {}
for i, model in enumerate(MODELS, 1):
    print(f"\n{'─' * 80}")
    print(f"BENCHMARK {i}/3: {model}")
    print(f"{'─' * 80}\n")
    
    env = os.environ.copy()
    env["VLM_MODEL"] = model
    
    cmd = [
        "python", "-m", "tests.vision_benchmark.runner",
        "--model", model,
        "--limit", "50"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=False, text=True, env=env, timeout=1800)
        print(f"\n✓ Benchmark {i} completed")
        results[model] = "completed"
    except subprocess.TimeoutExpired:
        print(f"\n✗ Benchmark {i} TIMEOUT after 30 minutes")
        results[model] = "timeout"
    except Exception as e:
        print(f"\n✗ Benchmark {i} ERROR: {e}")
        results[model] = f"error: {e}"

print("\n" + "=" * 80)
print("GENERATING FINAL COMPARISON REPORT")
print("=" * 80)
print()

# Generate comparison report
try:
    cmd = [
        "python", "-m", "tests.vision_benchmark.report",
        "--models", "qwen3.5:4b", "qwen3-vl:8b", "minicpm-v",
        "--output", "reports/vision_2_0_comparison_final.md"
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    print("✓ Comparison report generated: reports/vision_2_0_comparison_final.md")
except Exception as e:
    print(f"✗ Report generation failed: {e}")

print("\n" + "=" * 80)
print("SUMMARY FILES")
print("=" * 80)
print()

# List summary files
summary_dir = Path("reports")
summaries = sorted(summary_dir.glob("summary_*.json"))
for summary in summaries:
    size = summary.stat().st_size
    mtime = datetime.fromtimestamp(summary.stat().st_mtime).isoformat()
    print(f"  {summary.name:40} ({size:6} bytes) - {mtime}")

print("\n" + "=" * 80)
print("BENCHMARKING COMPLETE")
print("=" * 80)

