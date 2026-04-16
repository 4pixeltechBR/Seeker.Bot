import asyncio
import aiosqlite

DB_PATH = "e:/Seeker.Bot/data/seeker_memory.db"

async def alter_schema():
    print(f"Connecting to DB: {DB_PATH}")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("ALTER TABLE event_map ADD COLUMN atualizado_em TIMESTAMP;")
        await db.commit()
    print("Column added successfully.")

if __name__ == "__main__":
    asyncio.run(alter_schema())
