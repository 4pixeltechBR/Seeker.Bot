"""
Seeker.Bot - Entrypoint
python -m src  inicia o bot
"""

import asyncio
import sys
import logging

# Importa pacote de skills para auto-registro de capabilities no Capability Graph
import src.skills  # noqa: F401
from src.channels.telegram.bot import main

# Banner ASCII no terminal (polvo + SEEKER.BOT)
from src.core.banner import print_banner

print_banner()

logging.getLogger("seeker").info("Python %s - Seeker.Bot v3.12", sys.version.split()[0])

if __name__ == "__main__":
    asyncio.run(main())
