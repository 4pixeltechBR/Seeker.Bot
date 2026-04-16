import asyncio
import logging
import sys
from src.core.pipeline import SeekerPipeline
from src.skills.event_map_scout.scout import EventMapEngine
import os
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

async def test_pdf_only():
    load_dotenv("E:/Seeker.Bot/config/.env")
    api_keys = {
        "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
        "gemini": os.getenv("GEMINI_API_KEY", ""),
        "groq": os.getenv("GROQ_API_KEY", ""),
        "mistral": os.getenv("MISTRAL_API_KEY", ""),
        "nvidia": os.getenv("NVIDIA_API_KEY", ""),
    }
    
    pipeline = SeekerPipeline(api_keys)
    await pipeline.init()
    
    engine = EventMapEngine(pipeline)
    print("Gerando PDF a partir do banco de dados para Caldas Novas...")
    report, pdf_path = await engine._generate_report("Caldas Novas", "GO")
    
    print("PDF Gerado em:", pdf_path)
    await pipeline.close()

if __name__ == "__main__":
    asyncio.run(test_pdf_only())
