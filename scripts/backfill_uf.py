"""
Backfill de UF nos leads existentes do CRM.

Resolve ~12k leads marcados como "GO" indiscriminadamente,
usando IBGE (27 UFs), Google Places, e Wikipédia como fallback.

Uso:
  python scripts/backfill_uf.py --dry-run      # simula
  python scripts/backfill_uf.py --limit 100    # processa só 100
  python scripts/backfill_uf.py                # executa completo
"""

import sys
import os
import asyncio
import argparse
from pathlib import Path
from collections import Counter

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from dotenv import load_dotenv
import aiosqlite

load_dotenv(Path(__file__).resolve().parent.parent / "config" / ".env")

from src.core.memory.store import DEFAULT_DB_PATH
from src.skills.seeker_sales.geo import resolve_uf, save_uf_override, normalize_string


async def main():
    parser = argparse.ArgumentParser(description="Backfill de UF nos leads do CRM.")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem escrever.")
    parser.add_argument("--limit", type=int, default=0, help="Limita número de leads processados.")
    parser.add_argument("--skip-ibge", action="store_true", help="Pula Tier 0 (IBGE) para teste rápido.")
    args = parser.parse_args()

    db = await aiosqlite.connect(DEFAULT_DB_PATH)

    # Lê todos os leads
    async with db.execute("SELECT target_key, cidade, estado FROM crm_leads ORDER BY discovered_at DESC") as cur:
        rows = await cur.fetchall()
        cols = [c[0] for c in cur.description]
        leads = [dict(zip(cols, row)) for row in rows]

    if args.limit > 0:
        leads = leads[:args.limit]

    print(f"📋 Total de leads: {len(leads)}")

    # Audit antes
    estado_before = Counter(l.get("estado") or "GO" for l in leads)
    print(f"✗ Antes: {dict(estado_before)}")

    # Processa
    updates = []
    sources_used = Counter()

    from src.core.pipeline import SeekerPipeline

    api_keys = {
        "gemini": os.getenv("GEMINI_API_KEY"),
        "groq": os.getenv("GROQ_API_KEY"),
        "kimi": os.getenv("KIMI_API_KEY"),
        "deepseek": os.getenv("DEEPSEEK_API_KEY"),
    }
    pipeline = SeekerPipeline(api_keys)

    print(f"\n🔄 Processando {len(leads)} leads...")

    for i, lead in enumerate(leads, 1):
        target_key = lead["target_key"]
        cidade_raw = lead.get("cidade", "")
        estado_atual = lead.get("estado") or "GO"

        if not cidade_raw:
            continue

        # resolve_uf já normaliza internamente (preserva "Cidade - UF" para detectar sufixo)
        uf_resolvido = None
        source = None

        # Tier 0: IBGE (offline)
        if not args.skip_ibge:
            uf_resolvido, source = resolve_uf(cidade_raw, pipeline=None)

        # Tier 1: Places + Wiki (se precisar)
        if not uf_resolvido:
            uf_resolvido, source = resolve_uf(cidade_raw, pipeline=pipeline)

        if uf_resolvido and uf_resolvido != estado_atual:
            updates.append((uf_resolvido, target_key))
            sources_used[source or "unresolved"] += 1

            if (i % 100) == 0:
                print(f"  [{i:5d}] {cidade_raw:20s} → {uf_resolvido} ({source})")
        elif uf_resolvido == estado_atual:
            sources_used["no_change"] += 1
        else:
            sources_used["unresolved"] += 1

    print(f"\n📊 Resumo por source:")
    for source, count in sources_used.most_common():
        print(f"  {source:15s}: {count:4d}")

    print(f"\n💾 Total a atualizar: {len(updates)}")

    if not args.dry_run and updates:
        print("🔐 Executando UPDATE...")
        async with db.execute("BEGIN") as _:
            for uf, tk in updates:
                await db.execute("UPDATE crm_leads SET estado=? WHERE target_key=?", (uf, tk))
            await db.commit()
        print("✓ UPDATE concluído")

    # Audit depois
    if not args.dry_run and updates:
        async with db.execute("SELECT estado FROM crm_leads WHERE estado IS NOT NULL AND estado != ''") as cur:
            rows = await cur.fetchall()
            estado_after = Counter(r[0] for r in rows)
            print(f"✓ Depois: {dict(estado_after)}")

    await db.close()
    print("\n✅ Concluído!")


if __name__ == "__main__":
    asyncio.run(main())
