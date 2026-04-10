#!/usr/bin/env python3
"""Monitor progresso dos benchmarks em tempo real"""
import os
import time
from pathlib import Path
from datetime import datetime

def check_progress():
    reports_dir = Path("reports")
    summaries = sorted(reports_dir.glob("summary_*.json"))
    
    models = ["qwen3.5:4b", "qwen3-vl:8b", "qwen2.5vl:7b", "minicpm-v"]
    
    print("\n" + "="*70)
    print(f"STATUS DOS BENCHMARKS — {datetime.now().strftime('%H:%M:%S')}")
    print("="*70 + "\n")
    
    for model in models:
        safe_name = model.replace(":", "_")
        summary_file = reports_dir / f"summary_{safe_name}.json"
        
        if summary_file.exists():
            stat = summary_file.stat()
            size = stat.st_size
            print(f"✅ {model:20} — COMPLETO ({size} bytes)")
        else:
            print(f"⏳ {model:20} — EXECUTANDO...")
    
    print(f"\nTotal concluído: {len(summaries)}/4 modelos")
    print(f"Tempo estimado restante: {(4 - len(summaries)) * 20} minutos")
    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    check_progress()
