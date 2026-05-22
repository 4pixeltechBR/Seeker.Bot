"""
Backfill: adiciona mes/mes_fim/precisao a todos os eventos em event_radar_results.jsonl
Reescreve o arquivo in-place (faz backup .bak antes).
"""

import json
import shutil
import sys
from pathlib import Path

# Resolve root independente de onde o script é chamado
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.skills.event_radar.date_parser import enrich_event

_candidates = [
    ROOT / "data" / "event_radar" / "event_radar_results.jsonl",
    Path("E:/Seeker.Bot/data/event_radar/event_radar_results.jsonl"),
]
JSONL = next((p for p in _candidates if p.exists()), _candidates[0])


def main():
    if not JSONL.exists():
        print(f"Arquivo não encontrado: {JSONL}")
        sys.exit(1)

    lines = JSONL.read_text(encoding="utf-8").splitlines()
    events = [json.loads(l) for l in lines if l.strip()]

    before = sum(1 for e in events if e.get("mes") is not None)

    enriched = [enrich_event(e) for e in events]

    after_ok = sum(1 for e in enriched if e.get("mes") is not None)
    after_none = len(enriched) - after_ok

    # Backup
    shutil.copy(JSONL, JSONL.with_suffix(".jsonl.bak"))

    # Reescreve
    JSONL.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in enriched) + "\n",
        encoding="utf-8",
    )

    print(f"Total eventos  : {len(enriched)}")
    print(f"Já tinham mes  : {before}")
    print(f"Com mes após   : {after_ok}")
    print(f"Indeterminados : {after_none}")
    print(f"Backup salvo   : {JSONL.with_suffix('.jsonl.bak')}")

    # Distribuição por mês
    from collections import Counter
    dist = Counter(e["mes"] for e in enriched if e.get("mes"))
    meses_nome = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
    print("\nDistribuição por mês:")
    for m in range(1, 13):
        bar = "█" * (dist[m] // 5)
        print(f"  {meses_nome[m-1]:3s}  {dist[m]:4d}  {bar}")


if __name__ == "__main__":
    main()
