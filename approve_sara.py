import sys
import asyncio
import aiosqlite
from pathlib import Path
sys.path.insert(0, 'E:/Seeker.Bot')
from src.core.memory.store import DEFAULT_DB_PATH
from src.skills.self_improvement.error_database import ErrorDatabase

async def do():
    db = await aiosqlite.connect(DEFAULT_DB_PATH)
    err_db = ErrorDatabase(db)
    res = await err_db.approve(15)
    print('RES:', res)
    await db.close()

asyncio.run(do())
