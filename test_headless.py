"""
Teste isolado do HeadlessScraper — não consome créditos de busca.

Uso:
    python test_headless.py
    python test_headless.py prefeitura.caldas.novas
"""

import asyncio
import sys
import os

# Garante que src/ está no path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from src.core.search.headless import HeadlessScraper


async def main():
    handle = sys.argv[1] if len(sys.argv) > 1 else "prefeitura.caldas.novas"
    handle = handle.lstrip("@")

    print(f"\n{'='*55}")
    print(f"  HeadlessScraper — Teste Isolado")
    print(f"  Handle: @{handle}")
    print(f"{'='*55}\n")

    scraper = HeadlessScraper()
    result = await scraper.extract_contacts_from_instagram(handle)

    print("Resultado:")
    for k, v in result.items():
        icon = "[+]" if v and not k.startswith("_") else ("[!]" if k.startswith("_") else "[ ]")
        print(f"  {icon} {k:15s}: {v}")

    print()
    if result.get("whatsapp") or result.get("email"):
        print("[OK] SUCESSO - Contato(s) extraido(s)!")
    elif result.get("_erro"):
        print(f"[ERRO] {result['_erro']}")
    else:
        print("[--] Nenhum contato encontrado (bio sem dados de contato).")


if __name__ == "__main__":
    asyncio.run(main())
