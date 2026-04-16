import asyncio
import aiosqlite
import os

DB_PATH = "e:/Seeker.Bot/data/seeker_memory.db"

SCHEMA = """
-- ─── EVENT MAP SCOUT ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS event_map (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    cidade TEXT NOT NULL,
    estado TEXT NOT NULL,
    nome_evento TEXT NOT NULL,
    nome_normalizado TEXT NOT NULL,
    categoria TEXT NOT NULL,
    
    -- Lógica de Previsão
    historico_anos TEXT,
    historico_mes INTEGER,
    status_previsao TEXT,
    
    porte_estimado TEXT,
    valor_contrato_publico TEXT,
    decisor_nome TEXT,
    decisor_cargo TEXT,
    telefone TEXT,
    instagram TEXT,
    fontes_urls TEXT,
    mapeado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(estado, cidade, nome_normalizado)
);

CREATE TABLE IF NOT EXISTS city_scan_queue (
    cidade TEXT,
    estado TEXT,
    status TEXT DEFAULT 'pending',
    last_scanned TIMESTAMP,
    UNIQUE(estado, cidade)
);
"""

async def init_schema():
    print(f"Connecting to DB: {DB_PATH}")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()
    print("Schema created successfully.")

if __name__ == "__main__":
    asyncio.run(init_schema())
