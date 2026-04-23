import json
import logging
from typing import List, Dict, Any
import aiosqlite

log = logging.getLogger("seeker.crm_store")

def classify_event_type(nome: str, contratante: str) -> str:
    nome_lower = nome.lower()
    contratante_lower = contratante.lower()
    text = nome_lower + " " + contratante_lower
    
    if any(k in text for k in ["agro", "peão", "rodeio", "vaquejada", "sindicato rural", "expo"]):
        return "AGRO"
    if any(k in text for k in ["junin", "arraiá", "quadrilha"]):
        return "JUNINO"
    if any(k in text for k in ["religios", "romaria", "divino", "padroeiro", "igreja", "paróquia"]):
        return "RELIG"
    if any(k in text for k in ["casamento", "15 anos", "debutante", "cerimonial"]):
        return "CERIM"
    if any(k in text for k in ["corporativo", "convenção", "congresso", "feira"]):
        return "CORP"
    if any(k in text for k in ["show", "balada", "arena", "casa de shows"]):
        return "SHOW"
    if any(k in text for k in ["prefeitura", "secretaria", "municipal", "governo"]):
        return "GOV"
    if any(k in text for k in ["particular"]):
        return "PARTICULAR"
    if any(k in text for k in ["festival", "cultural", "aniversário"]):
        return "FEST"
        
    return "OUTRO"

class CRMStore:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    async def init_tables(self):
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS crm_leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_key TEXT UNIQUE,
                nome_evento TEXT,
                cidade TEXT,
                estado TEXT DEFAULT 'GO',
                tipo_evento TEXT,
                tipo_contratante TEXT,
                periodo TEXT,
                score INTEGER,
                porte_estimado TEXT,
                orcamento_estimado TEXT,
                decisor_nome TEXT,
                decisor_cargo TEXT,
                whatsapp TEXT,
                telefone TEXT,
                instagram TEXT,
                website TEXT,
                sinais_contratacao TEXT,
                justificativa TEXT,
                pdf_path TEXT,
                dossier_html TEXT,
                discovered_at REAL,
                updated_at REAL
            )
        """)
        await self._db.commit()

    async def save_lead(self, lead: dict, target_key: str, pdf_path: str, dossier_html: str, discovered_at: float):
        nome = lead.get("nome_evento", target_key)
        cidade = lead.get("cidade", "GO")
        contratante = lead.get("tipo_contratante", "N/A")
        tipo_evento = classify_event_type(nome, contratante)
        
        await self._db.execute("""
            INSERT INTO crm_leads (
                target_key, nome_evento, cidade, tipo_evento, tipo_contratante,
                periodo, score, porte_estimado, orcamento_estimado, decisor_nome, decisor_cargo,
                whatsapp, telefone, instagram, website, sinais_contratacao, justificativa,
                pdf_path, dossier_html, discovered_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(target_key) DO UPDATE SET
                score=excluded.score,
                orcamento_estimado=excluded.orcamento_estimado,
                whatsapp=COALESCE(excluded.whatsapp, crm_leads.whatsapp),
                telefone=COALESCE(excluded.telefone, crm_leads.telefone),
                pdf_path=excluded.pdf_path,
                dossier_html=excluded.dossier_html,
                updated_at=excluded.updated_at
        """, (
            target_key, nome, cidade, tipo_evento, contratante,
            lead.get("periodo", ""), lead.get("score", 0), lead.get("porte_estimado", ""),
            lead.get("orcamento_estimado", ""), lead.get("decisor_nome", ""), lead.get("decisor_cargo", ""),
            lead.get("whatsapp", ""), lead.get("telefone", ""), lead.get("instagram", ""), lead.get("website", ""),
            lead.get("sinais_contratacao", ""), lead.get("justificativa", ""),
            pdf_path, dossier_html, discovered_at, discovered_at
        ))
        await self._db.commit()

    async def get_recent(self, limit: int = 15) -> List[Dict]:
        async with self._db.execute("SELECT * FROM crm_leads ORDER BY discovered_at DESC LIMIT ?", (limit,)) as cur:
            rows = await cur.fetchall()
            cols = [col[0] for col in cur.description]
            return [dict(zip(cols, row)) for row in rows]

    async def search_by_city(self, city: str) -> List[Dict]:
        async with self._db.execute("SELECT * FROM crm_leads WHERE cidade LIKE ? ORDER BY score DESC, discovered_at DESC", (f"%{city}%",)) as cur:
            rows = await cur.fetchall()
            cols = [col[0] for col in cur.description]
            return [dict(zip(cols, row)) for row in rows]

    async def search_by_month(self, month_keyword: str) -> List[Dict]:
        async with self._db.execute("SELECT * FROM crm_leads WHERE periodo LIKE ? ORDER BY score DESC, discovered_at DESC", (f"%{month_keyword}%",)) as cur:
            rows = await cur.fetchall()
            cols = [col[0] for col in cur.description]
            return [dict(zip(cols, row)) for row in rows]

    async def search_by_type(self, type_event: str) -> List[Dict]:
        async with self._db.execute("SELECT * FROM crm_leads WHERE tipo_evento = ? ORDER BY score DESC, discovered_at DESC", (type_event,)) as cur:
            rows = await cur.fetchall()
            cols = [col[0] for col in cur.description]
            return [dict(zip(cols, row)) for row in rows]
            
    async def get_stats(self) -> Dict[str, Any]:
        stats = {}
        # Pipeline value
        async with self._db.execute("SELECT orcamento_estimado FROM crm_leads") as cur:
            rows = await cur.fetchall()
            # Simplistic sum, looking for 'k' or numbers in string
            total_k = 0
            for r in rows:
                val = str(r[0]).lower()
                import re
                nums = re.findall(r'(\d+)k', val)
                if nums:
                    total_k += sum(int(n) for n in nums) / len(nums) # average if range
            stats['pipeline_value'] = f"R${total_k:,.0f}K" if total_k else "N/A"
            
        # City density
        async with self._db.execute("SELECT cidade, COUNT(*) as c FROM crm_leads GROUP BY cidade ORDER BY c DESC LIMIT 5") as cur:
            stats['top_cities'] = await cur.fetchall()
            
        # Decaying leads (> 14 days old)
        fourteen_days_ago = __import__('time').time() - (14 * 86400)
        async with self._db.execute("SELECT COUNT(*) FROM crm_leads WHERE discovered_at < ?", (fourteen_days_ago,)) as cur:
            stats['decaying_count'] = (await cur.fetchone())[0]
            
        # Event types
        async with self._db.execute("SELECT tipo_evento, COUNT(*) as c FROM crm_leads GROUP BY tipo_evento ORDER BY c DESC") as cur:
            stats['types'] = await cur.fetchall()
            
        return stats
