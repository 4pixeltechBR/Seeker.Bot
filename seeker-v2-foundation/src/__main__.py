"""
Seeker.Bot — Entrypoint
python -m src → inicia o bot
"""

import asyncio
from src.channels.telegram.bot import main

if __name__ == "__main__":
    asyncio.run(main())
