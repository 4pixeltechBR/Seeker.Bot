import asyncio
import os
import sys
import logging

# Adicionar root ao sys.path para importar src
sys.path.append(os.getcwd())

from src.core.pipeline import SeekerPipeline
from src.skills.scout_hunter.scout import ScoutEngine

# Configurar logging para ver o que está acontecendo
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)

# Tentar carregar .env se existir
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

async def run_test():
    # Carregar chaves das variáveis de ambiente
    api_keys = {
        "gemini": os.getenv("GEMINI_API_KEY", ""),
        "TAVILY_API_KEY": os.getenv("TAVILY_API_KEY", ""),
        "BRAVE_API_KEY": os.getenv("BRAVE_API_KEY", ""),
        "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
        "SAMBANOVA_API_KEY": os.getenv("SAMBANOVA_API_KEY", ""),
        "NEBULA_API_KEY": os.getenv("NEBULA_API_KEY", ""),
        "NVIDIA_API_KEY": os.getenv("NVIDIA_API_KEY", ""),
    }
    
    # Verificar chaves críticas
    if not api_keys["BRAVE_API_KEY"] and not api_keys["TAVILY_API_KEY"]:
        print("ERRO: Nenhuma chave de busca (BRAVE/TAVILY) encontrada no ambiente!")
        return

    print("\n--- INICIALIZANDO PIPELINE ---")
    pipeline = SeekerPipeline(api_keys)
    await pipeline.init()
    
    scout = ScoutEngine(
        memory_store=pipeline.memory,
        cascade_adapter=pipeline.cascade_adapter,
        model_router=pipeline.model_router,
        api_keys=api_keys
    )
    
    await scout.init()
    
    print("\n--- INICIANDO FASE 1: DESCOBERTA REAL (Caldas Novas) ---")
    # Reduzindo limite para teste rápido
    discovery = await scout.scrape_campaign(region="Caldas Novas", niche="eventos", limit=5)
    campaign_id = discovery["campaign_id"]
    
    print(f"\nResultado Discovery:")
    print(f" - Campanha: {campaign_id}")
    print(f" - Leads únicos salvos: {discovery['total_saved']}")
    print(f" - Fontes: {discovery['sources']}")
    
    if discovery['total_saved'] == 0:
        print("Aviso: Nenhum lead encontrado. Verifique as queries ou conexões de API.")
        return

    print("\n--- INICIANDO FASE 2: ENRIQUECIMENTO REAL (Playwright) ---")
    # Tentar pegar leads que tenham instagram ou site real primeiro
    query_enrich = """
        SELECT lead_id, name, company, location, industry, source_url, bio_summary, instagram
        FROM scout_leads
        WHERE campaign_id = ? AND enriched_at IS NULL
        ORDER BY (CASE WHEN instagram IS NOT NULL OR source_url LIKE '%instagram.com%' THEN 0 ELSE 1 END) ASC
        LIMIT 3
    """
    async with pipeline.memory._db.execute(query_enrich, (campaign_id,)) as cur:
        leads_to_enrich = await cur.fetchall()
    
    enriched_count = 0
    for lead_row in leads_to_enrich:
        lead_dict = dict(lead_row)
        print(f"Processando: {lead_dict['name']} ({lead_dict['source_url']})")
        result = await scout._enrich_lead(lead_dict)
        if result.get("enriched_fields"):
            await scout._update_lead_enrichment(lead_dict["lead_id"], result["data"])
            enriched_count += 1
            print(f" [OK] Sucesso: {result['enriched_fields']}")
    
    print(f"\nResultado Enrichment:")
    print(f" - Processados: {len(leads_to_enrich)}")
    print(f" - Enriquecidos com sucesso: {enriched_count}")
    
    # Consultar DB para mostrar os dados reais
    async with pipeline.memory._db.execute(
        "SELECT name, company, whatsapp, email_address, website, instagram, source_url FROM scout_leads WHERE campaign_id = ? AND (whatsapp IS NOT NULL OR email_address IS NOT NULL) ORDER BY enriched_at DESC",
        (campaign_id,)
    ) as cur:
        results = await cur.fetchall()
        print("\n--- AMOSTRA DE DADOS REAIS EXTRAÍDOS ---")
        for row in results:
            print(f"Nome: {row[0]}")
            print(f"Empresa: {row[1]}")
            print(f"  - WhatsApp: {row[2] or 'N/A'}")
            print(f"  - Email: {row[3] or 'N/A'}")
            print(f"  - Website: {row[4] or 'N/A'}")
            print(f"  - Instagram: {row[5] or 'N/A'}")
            print(f"  - Fonte Original: {row[6]}")
            print("-" * 40)

if __name__ == "__main__":
    asyncio.run(run_test())
