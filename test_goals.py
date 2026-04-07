import asyncio
import os
import logging
from dotenv import load_dotenv

load_dotenv("config/.env")

from src.core.pipeline import SeekerPipeline
from src.channels.telegram.bot import discover_goals

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

async def main():
    api_keys = {
        "gemini": os.getenv("GEMINI_API_KEY"),
        "tavily": os.getenv("TAVILY_API_KEY"),
        "nvidia": os.getenv("NVIDIA_API_KEY"),
        "mistral": os.getenv("MISTRAL_API_KEY"),
        "deepseek": os.getenv("DEEPSEEK_API_KEY"),
    }
    pipeline = SeekerPipeline(api_keys)
    await pipeline.init()
    goals = discover_goals(pipeline)
    print("====================")
    print("[registry] Validando Goals:")
    for g in goals:
        print(f"[registry] ✅ {g.name}")
    print("[scheduler] 3 goals iniciados.")
    print("====================")

    # test 1 cycle for each
    for g in goals:
        print(f"Rondando {g.name}...")
        try:
            res = await g.run_cycle()
            print(f"Resultado {g.name}: success={res.success}, summary={res.summary}")
        except Exception as e:
            print(f"Erro no {g.name}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
