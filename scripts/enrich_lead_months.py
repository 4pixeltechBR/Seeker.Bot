import sys
import os
import asyncio
import json
import argparse
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Adiciona a raiz do projeto ao path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from src.skills.seeker_sales.crm_store import CRMStore
from src.skills.event_radar.query import EventQuery
from src.skills.seeker_sales.month_enricher import enrich_tier0, enrich_via_search, normalize_city

async def main():
    parser = argparse.ArgumentParser(description="Enriquece o mês dos leads do CRM em cascata.")
    parser.add_argument("--enrich-stats", action="store_true", help="Mostra apenas as estatísticas de enriquecimento e a cobertura.")
    parser.add_argument("--limit", type=int, default=0, help="Limita o número de leads órfãos processados.")
    parser.add_argument("--dry-run", action="store_true", help="Simula a cascata sem escrever no CRM.")
    parser.add_argument("--tier", type=int, choices=[0, 1, 2], default=2,
                         help="Tier máximo a aplicar: 0=fuzzy/cluster/heuristica, 1=+mini-mining, 2=+busca individual (default).")
    parser.add_argument("--max-cities", type=int, default=0, help="Limita o número de cidades minerados no Tier 1.")
    args = parser.parse_args()

    from dotenv import load_dotenv
    import aiosqlite
    from src.core.memory.store import DEFAULT_DB_PATH

    load_dotenv()
    
    api_keys = {
        "gemini": os.getenv("GEMINI_API_KEY"),
        "groq": os.getenv("GROQ_API_KEY"),
        "kimi": os.getenv("KIMI_API_KEY"),
        "deepseek": os.getenv("DEEPSEEK_API_KEY"),
    }

    # SeekerPipeline só é necessário para Tier 1 (mine_city) e Tier 2 (busca+LLM).
    # Tier 0 é puro CPU/CRM — evita o custo de inicialização da pipeline completa.
    pipeline = None
    radar_goal = None

    def _ensure_pipeline():
        nonlocal pipeline, radar_goal
        if pipeline is None:
            from src.core.pipeline import SeekerPipeline
            from src.skills.event_radar.goal import EventRadarGoal
            pipeline = SeekerPipeline(api_keys)
            radar_goal = EventRadarGoal(pipeline)
        return pipeline, radar_goal

    # Initialize DB connection
    db = await aiosqlite.connect(DEFAULT_DB_PATH)
    crm_store = CRMStore(db)

    if args.enrich_stats:
        stats = await crm_store.get_source_distribution()
        print("=== Cobertura e Provenance de Mês nos Leads ===")
        total = 0
        resolved = 0
        async with db.execute("SELECT COUNT(*) FROM crm_leads") as cur:
            total = (await cur.fetchone())[0]
        
        async with db.execute("SELECT COUNT(*) FROM crm_leads WHERE data_evento_mes IS NOT NULL") as cur:
            resolved = (await cur.fetchone())[0]

        for s, c in sorted(stats.items(), key=lambda x: x[1], reverse=True):
            print(f"- {s if s else 'Órfãos'}: {c}")
        
        if total > 0:
            print(f"\nTotal Leads: {total}")
            print(f"Resolvidos:  {resolved} ({resolved/total*100:.1f}%)")
        
        await db.close()
        return

    # 1. Carrega todos os leads órfãos (data_evento_mes IS NULL)
    async with db.execute("SELECT * FROM crm_leads WHERE data_evento_mes IS NULL") as cur:
        rows = await cur.fetchall()
        cols = [c[0] for c in cur.description]
        orphan_leads = [dict(zip(cols, row)) for row in rows]

    if args.limit > 0:
        orphan_leads = orphan_leads[:args.limit]

    if not orphan_leads:
        print("Nenhum lead órfão encontrado.")
        await db.close()
        return

    print(f"Iniciando enriquecimento de {len(orphan_leads)} leads.")

    # 2. Carrega Pool Global de Eventos do Radar (zero custo, sem pipeline)
    pool = EventQuery().all()

    # Prepara controle de concorrência e banco
    sem = asyncio.Semaphore(3)
    db_lock = asyncio.Lock()

    resolved_count = 0
    total_cost = 0.0
    mined_cities: set[str] = set()

    async def _safe_update(*update_args):
        if args.dry_run:
            return
        async with db_lock:
            await crm_store.update_event_date_full(*update_args)

    # 3. Executa processamento em cascata concorrente
    async def process_lead(lead: dict):
        nonlocal resolved_count, total_cost
        target_key = lead["target_key"]
        nome = lead.get("nome_evento") or ""
        cidade = lead.get("cidade") or ""
        cidade_norm = normalize_city(cidade)

        # Tier 0 (Match rápido em memória: fuzzy/cluster/heurística)
        r0 = enrich_tier0(lead, pool)
        if r0 and r0["confidence"] >= 0.80:
            await _safe_update(
                target_key, r0["mes"], r0["mes_fim"], r0["ano"],
                r0["source"], r0["confidence"], r0["evidencia"]
            )
            print(f"[Tier 0] {cidade} - {nome[:30]} -> Mês {r0['mes']} ({r0['source']})")
            resolved_count += 1
            return

        if args.tier < 1:
            print(f"[Tier 0] {cidade} - {nome[:30]} -> sem match (--tier=0)")
            return

        # Tier 1 (On Demand Mining) se a cidade tem pouco evento no pool
        cidade_events = [e for e in pool if normalize_city(e.get("cidade", "")) == cidade_norm]
        if len(cidade_events) < 2 and cidade_norm not in mined_cities:
            if args.max_cities and len(mined_cities) >= args.max_cities:
                print(f"[Tier 1] Limite de --max-cities atingido, pulando mineração de {cidade}")
            else:
                print(f"[Tier 1] Minerando {cidade} on-demand...")
                async with sem:
                    _, radar_goal = _ensure_pipeline()
                    events, cost = await radar_goal.mine_city(
                        cidade, lead.get("estado", "Goiás"), "GO",
                        save_to_jsonl=not args.dry_run,
                    )
                    async with db_lock:
                        total_cost += cost
                        mined_cities.add(cidade_norm)

                if events:
                    async with db_lock:
                        pool.extend(events)

                    # Re-avalia Tier 0 após a mineração
                    r0_again = enrich_tier0(lead, pool, pool_source="mining")
                    if r0_again and r0_again["confidence"] >= 0.80:
                        await _safe_update(
                            target_key, r0_again["mes"], r0_again["mes_fim"], r0_again["ano"],
                            r0_again["source"], r0_again["confidence"], r0_again["evidencia"]
                        )
                        print(f"[Tier 1] {cidade} - {nome[:30]} -> Mês {r0_again['mes']} (após mine_city)")
                        resolved_count += 1
                        return

        if args.tier < 2:
            print(f"[Tier 1] {cidade} - {nome[:30]} -> sem match (--tier=1)")
            return

        # Tier 2 (Busca Direcionada com IA)
        async with sem:
            print(f"[Tier 2] Buscando na web: {nome[:30]} ({cidade})")
            pipeline, _ = _ensure_pipeline()
            r2 = await enrich_via_search(lead, pipeline)
            if r2:
                await _safe_update(
                    target_key, r2["mes"], r2["mes_fim"], r2["ano"],
                    r2["source"], r2["confidence"], r2["evidencia"]
                )
                print(f"[Tier 2] {cidade} - {nome[:30]} -> Mês {r2['mes']} (via LLM search)")
                resolved_count += 1
                return

        print(f"[Falha] Não foi possível resolver: {nome[:30]} ({cidade})")

    # Dispara os leads todos juntos (limitados a 3 em I/O pesados pelo semáforo)
    tasks = [process_lead(lead) for lead in orphan_leads]
    await asyncio.gather(*tasks)

    dry_str = " (DRY-RUN, nada foi escrito)" if args.dry_run else ""
    print(f"\n✅ Concluído!{dry_str} {resolved_count}/{len(orphan_leads)} leads resolvidos.")
    print(f"💰 Custo extra estimado (LLM): ${total_cost:.4f}")

    await db.close()

if __name__ == "__main__":
    asyncio.run(main())
