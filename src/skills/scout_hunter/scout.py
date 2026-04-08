"""
Seeker.Bot — Scout B2B Lead Generation Engine

Adapted from Seeker.ai Project's scout_*.py modules.
Complete B2B prospection pipeline:
  1. Scraping: 6 sources (Google Maps, Sympla, Instagram, Casamentos, OSINT, Calendar)
  2. Enrichment: Website, Instagram, CNPJ validation
  3. Qualification: BANT scoring via cascade
  4. Copywriting: 3 formats (Email, LinkedIn, SMS)

Usage:
    scout = ScoutEngine(memory_store, cascade_adapter, model_router, api_keys)
    await scout.init()
    result = await scout.run_campaign(region="Goiânia", niche="eventos", limit=100)
"""

import asyncio
import logging
import json
import time
import re
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from enum import Enum

log = logging.getLogger("seeker.scout")


class CascadeRole(str, Enum):
    """Cascade LLM roles for different task types."""
    FAST = "FAST"
    CREATIVE = "CREATIVE"
    SYNTHESIS = "SYNTHESIS"


class ScoutEngine:
    """
    Multi-stage B2B lead prospection engine with scraping, enrichment, qualification, and copy generation.
    Integrates with Seeker.Bot's memory store and cascade LLM provider.
    """

    LEADS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS scout_leads (
        lead_id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        name TEXT,
        company TEXT,
        role TEXT,
        industry TEXT,
        location TEXT,
        source_url TEXT,
        bio_summary TEXT,

        -- Enrichment fields
        email_address TEXT,
        phone TEXT,
        whatsapp TEXT,
        instagram TEXT,
        website TEXT,
        facebook TEXT,
        cnpj TEXT,
        buying_signal TEXT,
        enriched_at TIMESTAMP,

        -- Qualification fields
        score INTEGER DEFAULT 0,
        score_reason TEXT,
        status TEXT DEFAULT 'novo',  -- novo, aprovado, rejeitado, enviado, respondeu, converteu
        content_draft TEXT,
        copy_formats TEXT,  -- JSON: {email, linkedin, sms}

        -- Metadata
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        UNIQUE(campaign_id, name, company)
    );

    CREATE INDEX IF NOT EXISTS idx_scout_campaign ON scout_leads(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_scout_status ON scout_leads(status);
    CREATE INDEX IF NOT EXISTS idx_scout_score ON scout_leads(score DESC);
    """

    def __init__(self, memory_store, cascade_adapter, model_router, api_keys: dict):
        self.memory = memory_store
        self.cascade = cascade_adapter
        self.model_router = model_router
        self.api_keys = api_keys

        self._campaign_cache = {}

    async def init(self) -> None:
        """Initialize schema."""
        try:
            await self.memory._db.executescript(self.LEADS_SCHEMA)
            await self.memory._db.commit()
            log.info("[scout] Schema initialized")
        except Exception as e:
            log.error(f"[scout] Schema init failed: {e}")

    # ──────────────────────────────────────────────────────────
    # PHASE 1: SCRAPING (6 sources)
    # ──────────────────────────────────────────────────────────

    async def scrape_campaign(
        self,
        region: str = "Goiânia",
        niche: str = "eventos",
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Execute scraping across 6 sources.
        Returns dict with campaign_id, leads scraped, and source stats.
        """
        campaign_id = f"scout_{uuid.uuid4().hex[:8]}"
        log.info(f"[scout] Starting campaign '{campaign_id}' | Region: {region} | Niche: {niche}")

        t0 = time.time()
        all_leads = []
        source_stats = {}

        # 1. Google Maps
        try:
            maps_leads = self._scrape_google_maps(region, niche)
            all_leads.extend(maps_leads)
            source_stats["google_maps"] = len(maps_leads)
            log.info(f"[scout] Google Maps: {len(maps_leads)} leads")
        except Exception as e:
            log.warning(f"[scout] Google Maps failed: {e}")
            source_stats["google_maps"] = f"error: {str(e)[:50]}"

        # 2. Sympla
        try:
            sympla_leads = self._scrape_sympla(region, niche)
            all_leads.extend(sympla_leads)
            source_stats["sympla"] = len(sympla_leads)
            log.info(f"[scout] Sympla: {len(sympla_leads)} leads")
        except Exception as e:
            log.warning(f"[scout] Sympla failed: {e}")
            source_stats["sympla"] = f"error: {str(e)[:50]}"

        # 3. Instagram (via Google)
        try:
            insta_leads = self._scrape_instagram_public(region, niche)
            all_leads.extend(insta_leads)
            source_stats["instagram"] = len(insta_leads)
            log.info(f"[scout] Instagram: {len(insta_leads)} leads")
        except Exception as e:
            log.warning(f"[scout] Instagram failed: {e}")
            source_stats["instagram"] = f"error: {str(e)[:50]}"

        # 4. Casamentos.com.br (wedding niche)
        if niche in ("eventos", "casamento", "wedding"):
            try:
                casamentos_leads = self._scrape_casamentos(region)
                all_leads.extend(casamentos_leads)
                source_stats["casamentos_com_br"] = len(casamentos_leads)
                log.info(f"[scout] Casamentos: {len(casamentos_leads)} leads")
            except Exception as e:
                log.warning(f"[scout] Casamentos failed: {e}")
                source_stats["casamentos_com_br"] = f"error: {str(e)[:50]}"

        # 5. Google OSINT (decision makers)
        try:
            osint_leads = self._scrape_google_osint(region, niche)
            all_leads.extend(osint_leads)
            source_stats["google_osint"] = len(osint_leads)
            log.info(f"[scout] OSINT: {len(osint_leads)} leads")
        except Exception as e:
            log.warning(f"[scout] OSINT failed: {e}")
            source_stats["google_osint"] = f"error: {str(e)[:50]}"

        # 6. Event Calendar (future events radar)
        try:
            calendar_leads = self._scrape_event_calendar(region, niche)
            all_leads.extend(calendar_leads)
            source_stats["calendario"] = len(calendar_leads)
            log.info(f"[scout] Calendar: {len(calendar_leads)} leads")
        except Exception as e:
            log.warning(f"[scout] Calendar failed: {e}")
            source_stats["calendario"] = f"error: {str(e)[:50]}"

        # Dedup by name + company
        seen = set()
        unique_leads = []
        for lead in all_leads:
            key = (lead.get("name", "").lower().strip(), lead.get("company", "").lower().strip())
            if key not in seen and key != ("", ""):
                seen.add(key)
                unique_leads.append(lead)

        # Save to DB
        saved = await self._save_leads_to_db(unique_leads, campaign_id)

        elapsed = time.time() - t0
        log.info(f"[scout] Campaign complete: {saved} unique leads in {elapsed:.1f}s from {len(source_stats)} sources")

        return {
            "status": "success",
            "campaign_id": campaign_id,
            "region": region,
            "niche": niche,
            "total_raw": len(all_leads),
            "total_unique": len(unique_leads),
            "total_saved": saved,
            "sources": source_stats,
            "elapsed_seconds": round(elapsed, 1),
        }

    def _scrape_google_maps(self, region: str, niche: str) -> List[Dict]:
        """Mock implementation for Google Maps scraping."""
        # In production, would use browser automation (Playwright/Selenium)
        log.debug(f"[scout] Google Maps: Searching for '{niche}' in '{region}'")
        return [
            {
                "name": f"Lead Maps {region} #{i}",
                "company": f"Empresa {i}",
                "location": region,
                "role": "Estabelecimento",
                "industry": niche,
                "source_url": "https://maps.google.com",
                "bio_summary": f"Negócio de {niche} em {region}",
            }
            for i in range(3)
        ]

    def _scrape_sympla(self, region: str, niche: str) -> List[Dict]:
        """Mock implementation for Sympla (event organizers)."""
        log.debug(f"[scout] Sympla: Searching for '{niche}' events in '{region}'")
        return [
            {
                "name": f"Organizador Sympla {region} #{i}",
                "company": f"Evento {niche} {i}",
                "location": region,
                "role": "Organizador de Eventos",
                "industry": niche,
                "source_url": "https://sympla.com.br",
                "bio_summary": f"Produtor de eventos de {niche}",
            }
            for i in range(2)
        ]

    def _scrape_instagram_public(self, region: str, niche: str) -> List[Dict]:
        """Mock implementation for Instagram (public profiles via Google)."""
        log.debug(f"[scout] Instagram: Searching for public profiles in '{region}'")
        return [
            {
                "name": f"@insta_{region.lower()}_{i}",
                "company": f"Criador {niche} {region}",
                "location": region,
                "role": "Perfil Instagram",
                "industry": niche,
                "instagram": f"@insta_{region.lower()}_{i}",
                "source_url": f"https://instagram.com/insta_{region.lower()}_{i}",
                "bio_summary": f"Especializado em {niche}",
            }
            for i in range(2)
        ]

    def _scrape_casamentos(self, region: str) -> List[Dict]:
        """Mock implementation for Casamentos.com.br (wedding professionals)."""
        log.debug(f"[scout] Casamentos: Searching wedding professionals in '{region}'")
        return [
            {
                "name": f"Cerimonialista {region} #{i}",
                "company": f"Assessoria de Casamento {i}",
                "location": region,
                "role": "Cerimonialista",
                "industry": "casamento",
                "source_url": "https://casamentos.com.br",
                "bio_summary": f"Assessoria de casamentos em {region}",
                "phone": f"(62) 999{1000 + i}-{1000 + i}",
            }
            for i in range(2)
        ]

    def _scrape_google_osint(self, region: str, niche: str) -> List[Dict]:
        """Mock implementation for Google OSINT (decision makers by role)."""
        log.debug(f"[scout] OSINT: Searching decision makers for '{niche}' in '{region}'")
        roles = ["RH", "Diretor", "Produtor", "Gerente de Eventos", "Coordenador"]
        return [
            {
                "name": f"{role} {region} #{i}",
                "company": f"Empresa {niche} {i}",
                "location": region,
                "role": role,
                "industry": niche,
                "source_url": "https://google.com/search",
                "bio_summary": f"{role} responsável por {niche}",
            }
            for i, role in enumerate(roles[:3])
        ]

    def _scrape_event_calendar(self, region: str, niche: str, days_ahead: int = 180) -> List[Dict]:
        """Mock implementation for future events calendar."""
        log.debug(f"[scout] Calendar: Searching future {niche} events in '{region}' (next {days_ahead} days)")
        return [
            {
                "name": f"Evento Futuro {niche} #{i}",
                "company": f"Organizador {niche} {i}",
                "location": region,
                "role": "Organizador (evento futuro)",
                "industry": niche,
                "source_url": "https://google.com/search",
                "bio_summary": f"Planejando evento de {niche}",
                "buying_signal": f"Evento agendado para os próximos {days_ahead} dias",
            }
            for i in range(2)
        ]

    # ──────────────────────────────────────────────────────────
    # PHASE 2: ENRICHMENT
    # ──────────────────────────────────────────────────────────

    async def enrich_campaign(self, campaign_id: str, limit: int = 30) -> Dict[str, Any]:
        """
        Enrich all un-enriched leads from a campaign.
        Extracts contact info from websites, Instagram, CNPJ.
        """
        log.info(f"[scout] Starting enrichment for campaign '{campaign_id}' (limit: {limit})")

        # Get un-enriched leads
        query = """
            SELECT lead_id, name, company, location, industry, source_url, bio_summary
            FROM scout_leads
            WHERE campaign_id = ? AND enriched_at IS NULL AND status != 'rejeitado'
            LIMIT ?
        """
        async with self.memory._db.execute(query, (campaign_id, limit)) as cur:
            leads = await cur.fetchall()

        if not leads:
            log.info(f"[scout] No un-enriched leads for campaign '{campaign_id}'")
            return {"status": "success", "campaign_id": campaign_id, "enriched": 0}

        log.info(f"[scout] Enriching {len(leads)} leads from campaign '{campaign_id}'")

        enriched_count = 0
        for lead_row in leads:
            try:
                lead_dict = dict(lead_row)
                result = await self._enrich_lead(lead_dict)

                if result.get("enriched_fields"):
                    await self._update_lead_enrichment(lead_dict["lead_id"], result["data"])
                    enriched_count += 1
            except Exception as e:
                log.warning(f"[scout] Enrichment failed for lead #{lead_row['lead_id']}: {e}")

        log.info(f"[scout] Enrichment complete: {enriched_count}/{len(leads)} leads enriched")

        return {
            "status": "success",
            "campaign_id": campaign_id,
            "total_processed": len(leads),
            "enriched": enriched_count,
        }

    async def _enrich_lead(self, lead: Dict) -> Dict[str, Any]:
        """Enrich a single lead with contact information."""
        enriched = {}

        # 1. Website extraction
        if lead.get("source_url") and "instagram" not in lead.get("source_url", "").lower():
            website_data = self._extract_from_website(lead)
            enriched.update(website_data)

        # 2. Instagram extraction
        if lead.get("instagram"):
            insta_data = self._extract_from_instagram(lead)
            for k, v in insta_data.items():
                if k not in enriched or not enriched[k]:
                    enriched[k] = v

        # 3. CNPJ lookup (Brazilian business registry)
        if lead.get("company"):
            cnpj_data = self._lookup_cnpj(lead)
            enriched.update(cnpj_data)

        return {
            "status": "success",
            "enriched_fields": list(enriched.keys()),
            "data": enriched,
        }

    def _extract_from_website(self, lead: Dict) -> Dict[str, Any]:
        """Extract contact info from website."""
        # Mock implementation
        enriched = {}
        if lead.get("source_url") and "maps.google.com" not in lead.get("source_url"):
            enriched["website"] = lead.get("source_url")
            enriched["email_address"] = f"contato@{lead.get('company', 'empresa').lower().replace(' ', '')}.com"
        return enriched

    def _extract_from_instagram(self, lead: Dict) -> Dict[str, Any]:
        """Extract bio and links from Instagram profile."""
        enriched = {}
        if lead.get("instagram"):
            enriched["instagram"] = lead.get("instagram")
            enriched["bio_summary"] = lead.get("bio_summary", "")
        return enriched

    def _lookup_cnpj(self, lead: Dict) -> Dict[str, Any]:
        """Lookup Brazilian business registry."""
        # Mock implementation
        enriched = {}
        if lead.get("company") and "lead" not in lead.get("company", "").lower():
            enriched["cnpj"] = f"{uuid.uuid4().hex[:14]}"
        return enriched

    async def _update_lead_enrichment(self, lead_id: int, enriched_data: Dict) -> None:
        """Update lead with enriched data."""
        sets = []
        vals = []

        allowed_fields = {
            "email_address", "phone", "whatsapp", "instagram",
            "website", "facebook", "cnpj", "bio_summary", "buying_signal"
        }

        for col, val in enriched_data.items():
            if col in allowed_fields and val:
                sets.append(f"{col} = ?")
                vals.append(val)

        if sets:
            sets.append("enriched_at = ?")
            vals.append(datetime.now().isoformat())
            vals.append(lead_id)

            sql = f"UPDATE scout_leads SET {', '.join(sets)} WHERE lead_id = ?"
            await self.memory._db.execute(sql, vals)
            await self.memory._db.commit()

    # ──────────────────────────────────────────────────────────
    # PHASE 3: QUALIFICATION & COPYWRITING
    # ──────────────────────────────────────────────────────────

    async def run_full_pipeline(self, campaign_id: str, limit: int = 100) -> Dict[str, Any]:
        """
        Complete pipeline: Scrape → Enrich → Qualify → Generate Copy
        """
        log.info(f"[scout] Starting full pipeline for campaign '{campaign_id}'")

        # Enrich leads first
        await self.enrich_campaign(campaign_id, limit)

        # Get leads to qualify
        query = """
            SELECT lead_id, name, company, location, industry, bio_summary,
                   email_address, phone, whatsapp, instagram
            FROM scout_leads
            WHERE campaign_id = ? AND status = 'novo' LIMIT ?
        """
        async with self.memory._db.execute(query, (campaign_id, limit)) as cur:
            leads = await cur.fetchall()

        if not leads:
            log.info(f"[scout] No 'novo' leads to process for campaign '{campaign_id}'")
            return {"status": "success", "campaign_id": campaign_id, "qualified": 0}

        log.info(f"[scout] Processing {len(leads)} leads for qualification and copy")

        results = {"qualified": 0, "written": 0, "rejected": 0}
        semaphore = asyncio.Semaphore(3)  # Max 3 concurrent LLM calls

        async def _process_lead(lead_row):
            lead = dict(lead_row)
            lead_id = lead["lead_id"]

            ctx = (
                f"Name: {lead.get('name', 'Unknown')}\n"
                f"Company: {lead.get('company', '')}\n"
                f"Industry: {lead.get('industry', '')}\n"
                f"Location: {lead.get('location', '')}\n"
                f"Bio: {lead.get('bio_summary', '')}"
            )

            async with semaphore:
                # Qualification
                qual_prompt = (
                    "You are a B2B SDR qualification expert.\n"
                    "Evaluate this lead and return ONLY a valid JSON object:\n"
                    '{"score": <0-100 integer>, "reason": "<short explanation>", "fit": "<ideal_customer>"}\n\n'
                    f"Context:\n{ctx}"
                )

                qual_res = await self.cascade.call(
                    role=CascadeRole.FAST,
                    messages=[{"role": "user", "content": qual_prompt}],
                    temperature=0.2,
                    max_tokens=200,
                )

                score = 50
                try:
                    raw = qual_res.get("content", "{}")
                    s = raw.find("{")
                    e = raw.rfind("}") + 1
                    if s != -1 and e > s:
                        data = json.loads(raw[s:e])
                        score = int(data.get("score", 50))
                except Exception as parse_err:
                    log.warning(f"[scout] Parse error for lead {lead_id}: {parse_err}")

                # Copy generation if score is high
                if score >= 70:
                    results["qualified"] += 1

                    copy_prompt = (
                        "You are an expert B2B copywriter.\n"
                        "Write 3 personalized outreach formats for this lead:\n"
                        "1. Professional email (5 sentences)\n"
                        "2. LinkedIn DM (2-3 sentences)\n"
                        "3. WhatsApp message (1-2 sentences)\n"
                        "Be direct, personalized, and ready-to-send. Reply in Portuguese.\n\n"
                        f"Context:\n{ctx}"
                    )

                    copy_res = await self.cascade.call(
                        role=CascadeRole.CREATIVE,
                        messages=[{"role": "user", "content": copy_prompt}],
                        temperature=0.7,
                        max_tokens=400,
                    )

                    copy_text = copy_res.get("content", "")

                    # Update lead
                    await self._update_lead_qualification(lead_id, score, copy_text, "aprovado")
                    results["written"] += 1
                else:
                    await self._update_lead_qualification(lead_id, score, "", "rejeitado")
                    results["rejected"] += 1

        # Process all leads concurrently
        await asyncio.gather(*[_process_lead(l) for l in leads])

        log.info(
            f"[scout] Pipeline complete: "
            f"Qualified={results['qualified']}, "
            f"Written={results['written']}, "
            f"Rejected={results['rejected']}"
        )

        return {
            "status": "success",
            "campaign_id": campaign_id,
            "results": results,
        }

    async def _update_lead_qualification(self, lead_id: int, score: int, copy: str, status: str) -> None:
        """Update lead with qualification score and copy."""
        sql = """
            UPDATE scout_leads SET score = ?, content_draft = ?, status = ?, updated_at = ?
            WHERE lead_id = ?
        """
        await self.memory._db.execute(
            sql,
            (score, copy[:2000] if copy else None, status, datetime.now().isoformat(), lead_id)
        )
        await self.memory._db.commit()

    # ──────────────────────────────────────────────────────────
    # DASHBOARD & UTILITIES
    # ──────────────────────────────────────────────────────────

    async def get_campaign_dashboard(self, campaign_id: str = "latest") -> Dict[str, Any]:
        """Get dashboard metrics for a campaign."""
        if campaign_id == "latest":
            async with self.memory._db.execute(
                "SELECT campaign_id FROM scout_leads ORDER BY created_at DESC LIMIT 1"
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    return {"status": "empty", "message": "No campaigns found"}
                campaign_id = row["campaign_id"]

        # Get funnel stats
        async with self.memory._db.execute(
            "SELECT status, COUNT(*) as count FROM scout_leads WHERE campaign_id = ? GROUP BY status",
            (campaign_id,)
        ) as cur:
            stats = await cur.fetchall()

        funnel = {r["status"]: r["count"] for r in stats}
        total = sum(funnel.values())

        # Get top leads
        async with self.memory._db.execute(
            """
            SELECT lead_id, name, company, score, status
            FROM scout_leads
            WHERE campaign_id = ? AND score > 0
            ORDER BY score DESC
            LIMIT 5
            """,
            (campaign_id,)
        ) as cur:
            top_leads = await cur.fetchall()

        return {
            "status": "success",
            "campaign_id": campaign_id,
            "total": total,
            "funnel": funnel,
            "top_leads": [dict(l) for l in top_leads] if top_leads else [],
        }

    async def update_lead_status(self, lead_id: int, new_status: str) -> Dict[str, Any]:
        """Update lead status."""
        valid_statuses = {"novo", "aprovado", "rejeitado", "enviado", "respondeu", "converteu"}

        if new_status not in valid_statuses:
            return {"status": "error", "message": f"Invalid status. Use: {valid_statuses}"}

        await self.memory._db.execute(
            "UPDATE scout_leads SET status = ?, updated_at = ? WHERE lead_id = ?",
            (new_status, datetime.now().isoformat(), lead_id)
        )
        await self.memory._db.commit()

        return {"status": "success", "message": f"Lead {lead_id} updated to '{new_status}'"}

    async def get_lead_detail(self, lead_id: int) -> Optional[Dict]:
        """Get complete lead details."""
        async with self.memory._db.execute(
            "SELECT * FROM scout_leads WHERE lead_id = ?",
            (lead_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def _save_leads_to_db(self, leads: List[Dict], campaign_id: str) -> int:
        """Save raw leads to database."""
        saved = 0

        for lead in leads:
            try:
                await self.memory._db.execute(
                    """
                    INSERT INTO scout_leads
                    (campaign_id, name, company, role, industry, location, source_url, bio_summary, phone)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        campaign_id,
                        lead.get("name", ""),
                        lead.get("company", ""),
                        lead.get("role", ""),
                        lead.get("industry", ""),
                        lead.get("location", ""),
                        lead.get("source_url", ""),
                        lead.get("bio_summary", ""),
                        lead.get("phone", ""),
                    )
                )
                saved += 1
            except Exception as e:
                log.warning(f"[scout] Error saving lead '{lead.get('name')}': {e}")

        await self.memory._db.commit()
        log.info(f"[scout] Saved {saved} leads to campaign '{campaign_id}'")

        return saved
