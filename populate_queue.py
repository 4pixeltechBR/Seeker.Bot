import asyncio
import sqlite3

async def populate_queue():
    db_path = "E:\\Seeker.Bot\\data\\seeker_memory.db"
    
    cidades = [
        ("Caldas Novas", "GO"), ("Goiânia", "GO"), ("Brasília", "DF"),
        ("Anápolis", "GO"), ("Aparecida de Goiânia", "GO"),
        ("Rio Verde", "GO"), ("Itumbiara", "GO"), ("Jataí", "GO"),
        ("Luziânia", "GO"), ("Catalão", "GO")
    ]
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    inserted = 0
    for city, state in cidades:
        try:
            cur.execute("""
                INSERT INTO city_scan_queue (cidade, estado, status)
                VALUES (?, ?, 'pending')
            """, (city, state))
            inserted += 1
        except sqlite3.IntegrityError:
            # Já existe
            print(f"Cidade {city} já está na fila.")
            pass
            
    conn.commit()
    conn.close()
    
    print(f"Inseridas {inserted} cidades na fila.")

if __name__ == "__main__":
    asyncio.run(populate_queue())
