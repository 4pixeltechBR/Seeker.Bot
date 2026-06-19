import asyncio
import os
from dotenv import load_dotenv
from src.core.search.web import WebSearcher

# Specify exact path to .env
load_dotenv(r"E:\Seeker.Bot\config\.env")

async def test():
    key = os.getenv("GOOGLE_SEARCH_API_KEY")
    cx = os.getenv("GOOGLE_SEARCH_CX")
    print(f"API Key: {key}")
    print(f"CX: {cx}")
    if not key or not cx:
        print("Missing API Key or CX!")
        return

    # Passamos as chaves do Google
    searcher = WebSearcher(google_key=key, google_cx=cx)
    res = await searcher.search("noticias de tecnologia de hoje", bypass_limit=True)
    print(f"Backend usado: {res.backend}")
    print(f"Resultados: {len(res.results)}")
    if res.results:
        print(f"Top 1: {res.results[0].title} - {res.results[0].url}")
    else:
        print("Nenhum resultado retornado.")

asyncio.run(test())
