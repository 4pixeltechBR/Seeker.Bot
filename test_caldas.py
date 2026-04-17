import asyncio
import logging
import sys
import os
from dotenv import load_dotenv

from src.core.pipeline import SeekerPipeline
from src.skills.event_map_scout.goal import EventMapGoal

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

async def test_caldas():
    print("Carregando dotenv...")
    load_dotenv("E:/Seeker.Bot/config/.env")
    
    api_keys = {
        "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
        "gemini": os.getenv("GEMINI_API_KEY", ""),
        "groq": os.getenv("GROQ_API_KEY", ""),
        "mistral": os.getenv("MISTRAL_API_KEY", ""),
        "nvidia": os.getenv("NVIDIA_API_KEY", ""),
    }

    print("Inicializando pipeline do Seeker...")
    pipeline = SeekerPipeline(api_keys)
    await pipeline.init()
    
    # Injetando cidade de teste
    print("Injetando Caldas Novas na fila de scan e limpando base antiga...")
    # Using explicit dictionary to pass city info to memory directly
    await pipeline.memory._db.execute("DELETE FROM city_scan_queue")
    await pipeline.memory._db.execute("DELETE FROM event_map WHERE cidade='Caldas Novas'")
    await pipeline.memory._db.execute("INSERT INTO city_scan_queue (cidade, estado, status) VALUES ('Caldas Novas', 'GO', 'pending')")
    await pipeline.memory._db.commit()
    
    print("Executando o Goal do Event Map Scout...")
    goal = EventMapGoal()
    try:
        res = await goal.execute(pipeline)
        print("====== RESULTADO DO SCAN ======")
        print(res)
    except Exception as e:
        import traceback
        print(f"Erro no teste: {e}")
        traceback.print_exc()
        
    await pipeline.close()

if __name__ == "__main__":
    asyncio.run(test_caldas())
