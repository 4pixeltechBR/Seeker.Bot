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

from src.providers.cascade import CascadeRole
from src.skills.scout_hunter.discovery_matrix import DiscoveryMatrix
from src.skills.scout_hunter.account_research import AccountResearcher
from src.core.evidence import EvidenceEntry, get_evidence_store

log = logging.getLogger("seeker.scout")


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

        -- Enrichment fields (Phase 2)
        email_address TEXT,
        phone TEXT,
        whatsapp TEXT,
        instagram TEXT,
        website TEXT,
        facebook TEXT,
        cnpj TEXT,
        buying_signal TEXT,
        enriched_at TIMESTAMP,

        -- Discovery Matrix fields (Phase 2.5 — Scout Hunter 2.0)
        fit_score INTEGER DEFAULT 0,
        fit_score_reasoning TEXT,
        intent_signals_level INTEGER DEFAULT 0,
        intent_signals_evidence TEXT,  -- JSON
        budget_indicator TEXT,

        -- Account Research fields (Phase 2.75 — Scout Hunter 2.0)
        company_description TEXT,
        company_size TEXT,
        company_revenue_range TEXT,
        tech_stack TEXT,  -- JSON: ["Salesforce", "AWS", ...]
        identified_pain_points TEXT,  -- JSON: ["integration", "cost", ...]
        current_solution TEXT,
        competitive_landscape TEXT,  -- JSON: [{name, position}, ...]
        decision_makers TEXT,  -- JSON: [{name, title, email, linkedin_url, influence_level}, ...]
        account_research_cache_ttl INTEGER DEFAULT 168,  -- 7 dias em horas
        account_research_source TEXT,

        -- Qualification fields (Phase 3)
        bant_score INTEGER DEFAULT 0,
        bant_reasoning TEXT,
        qualification_status TEXT,  -- high_priority, medium, low, not_qualified
        score INTEGER DEFAULT 0,
        score_reason TEXT,
        status TEXT DEFAULT 'novo',  -- novo, aprovado, rejeitado, enviado, respondeu, converteu
        content_draft TEXT,
        copy_formats TEXT,  -- JSON: {email, linkedin, sms}
        copy_variant TEXT,  -- Qual pain_point foi abordado
        copy_target_decision_maker TEXT,

        -- Metadata
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        UNIQUE(campaign_id, name, company)
    );

    CREATE INDEX IF NOT EXISTS idx_scout_campaign ON scout_leads(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_scout_status ON scout_leads(status);
    CREATE INDEX IF NOT EXISTS idx_scout_score ON scout_leads(score DESC);
    CREATE INDEX IF NOT EXISTS idx_scout_fit_score ON scout_leads(fit_score DESC);
    CREATE INDEX IF NOT EXISTS idx_scout_bant_score ON scout_leads(bant_score DESC);
    """

    def __init__(self, memory_store, cascade_adapter, model_router, api_keys: dict):
        self.memory = memory_store
        self.cascade = cascade_adapter
        self.model_router = model_router
        self.api_keys = api_keys

        self._campaign_cache = {}

        # Context vars for current pipeline run (used by Discovery Matrix & Account Research)
        self.current_niche = None
        self.current_region = None

    async def init(self) -> None:
        """Initialize schema with migration support."""
        try:
            await self.memory._db.executescript(self.LEADS_SCHEMA)
            await self.memory._db.commit()
            log.info("[scout] Schema initialized")

            # Migration: Add missing columns for Phase 2.5 (Discovery Matrix)
            await self._migrate_schema()
        except Exception as e:
            log.error(f"[scout] Schema init failed: {e}")

    async def _migrate_schema(self) -> None:
        """Apply schema migrations for new features."""
        try:
            # Check if fit_score column exists
            cursor = await self.memory._db.execute(
                "PRAGMA table_info(scout_leads)"
            )
            columns = await cursor.fetchall()
            column_names = {col[1] for col in columns}

            migrations = [
                ("fit_score", "ALTER TABLE scout_leads ADD COLUMN fit_score INTEGER DEFAULT 0"),
                ("fit_score_reasoning", "ALTER TABLE scout_leads ADD COLUMN fit_score_reasoning TEXT"),
                ("discovery_matrix_at", "ALTER TABLE scout_leads ADD COLUMN discovery_matrix_at TIMESTAMP"),
                ("intent_signals_level", "ALTER TABLE scout_leads ADD COLUMN intent_signals_level INTEGER DEFAULT 0"),
                ("qualification_status", "ALTER TABLE scout_leads ADD COLUMN qualification_status TEXT"),
                ("bant_score", "ALTER TABLE scout_leads ADD COLUMN bant_score INTEGER DEFAULT 0"),
                ("copy_generated_at", "ALTER TABLE scout_leads ADD COLUMN copy_generated_at TIMESTAMP"),
                ("outreach_copy", "ALTER TABLE scout_leads ADD COLUMN outreach_copy TEXT"),
            ]

            for col_name, migration_sql in migrations:
                if col_name not in column_names:
                    try:
                        await self.memory._db.execute(migration_sql)
                        await self.memory._db.commit()
                        log.info(f"[scout] ✓ Migração: coluna '{col_name}' adicionada")
                    except Exception as e:
                        if "already exists" not in str(e).lower():
                            log.warning(f"[scout] Erro na migração '{col_name}': {e}")
        except Exception as e:
            log.warning(f"[scout] Erro ao verificar schema: {e}")

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
    # PHASE 2.5: DISCOVERY MATRIX (Scout Hunter 2.0)
    # ──────────────────────────────────────────────────────────

    async def _evaluate_discovery_matrix(self, campaign_id: str, limit: int = 100) -> None:
        """
        Avalia leads com Discovery Matrix (Fit Score, Intent Signals, Budget Indicator).
        Filtra leads com fit_score < 60 para economizar LLM na qualification avançada.
        """
        log.info(f"[scout] Avaliando Discovery Matrix para campaign '{campaign_id}'")

        # Instanciar Discovery Matrix
        discovery_matrix = DiscoveryMatrix(self.cascade)

        # Query leads enriquecidos
        query = """
            SELECT lead_id, name, company, role, industry, location, bio_summary, source_url, email_address, website
            FROM scout_leads
            WHERE campaign_id = ? AND status = 'novo' LIMIT ?
        """

        async with self.memory._db.execute(query, (campaign_id, limit)) as cur:
            leads = await cur.fetchall()

        if not leads:
            log.info(f"[scout] Nenhum lead 'novo' para Discovery Matrix")
            return

        log.info(f"[scout] Avaliando {len(leads)} leads com Discovery Matrix")

        # Avaliar leads (com semáforo para limitar concorrência)
        semaphore = asyncio.Semaphore(5)  # Max 5 concurrent evaluations
        results_dm = {}
        filtered_count = 0

        async def _evaluate_with_semaphore(lead_row):
            lead = dict(lead_row)
            lead_id = lead["lead_id"]

            async with semaphore:
                try:
                    result = await discovery_matrix.evaluate_lead(
                        lead,
                        niche=self.current_niche or "geral",
                        region=self.current_region or "geral"
                    )

                    # Update DB
                    sql = """
                        UPDATE scout_leads SET
                            fit_score = ?,
                            fit_score_reasoning = ?,
                            intent_signals_level = ?,
                            intent_signals_evidence = ?,
                            budget_indicator = ?
                        WHERE lead_id = ?
                    """

                    await self.memory._db.execute(sql, (
                        result.fit_score,
                        result.fit_score_reasoning,
                        result.intent_signals_level,
                        json.dumps(result.intent_signals_evidence),
                        result.budget_indicator,
                        lead_id
                    ))

                    results_dm[lead_id] = result

                    # Contar filtragens (fit < 60)
                    if not result.passed_minimum_threshold:
                        nonlocal filtered_count
                        filtered_count += 1
                        # Atualizar status para rejeitado se fit < 60
                        await self.memory._db.execute(
                            "UPDATE scout_leads SET status = ? WHERE lead_id = ?",
                            ("rejeitado", lead_id)
                        )

                except Exception as e:
                    log.warning(f"[scout] Erro ao avaliar lead {lead_id}: {e}")

        # Executar avaliações em paralelo
        tasks = [_evaluate_with_semaphore(lead) for lead in leads]
        await asyncio.gather(*tasks)

        await self.memory._db.commit()

        log.info(f"[scout] Discovery Matrix completo: {len(results_dm)} avaliados, {filtered_count} filtrados")

    # ──────────────────────────────────────────────────────────
    # PHASE 2.75: ACCOUNT RESEARCH (Scout Hunter 2.0)
    # ──────────────────────────────────────────────────────────

    async def _research_accounts(self, campaign_id: str, limit: int = 100) -> None:
        """
        Pesquisa profunda de contas (empresa, tech stack, pain points, decisores).
        Roda APÓS Discovery Matrix e ANTES de Qualification Avançada.
        """
        log.info(f"[scout] Iniciando Account Research para campaign '{campaign_id}'")

        # Instanciar Account Researcher
        account_researcher = AccountResearcher(self.cascade, web_searcher=None)

        # Query leads aprovados em Discovery Matrix (fit >= 60)
        query = """
            SELECT DISTINCT lead_id, company, industry, location
            FROM scout_leads
            WHERE campaign_id = ? AND status IN ('novo', 'aprovado') AND fit_score >= 60 LIMIT ?
        """

        async with self.memory._db.execute(query, (campaign_id, limit)) as cur:
            leads = await cur.fetchall()

        if not leads:
            log.info(f"[scout] Nenhum lead qualificado para Account Research")
            return

        log.info(f"[scout] Pesquisando {len(leads)} contas")

        # Deduplicar companies
        companies = {}
        for lead_row in leads:
            lead = dict(lead_row)
            company_name = lead.get("company", "Unknown")
            if company_name not in companies:
                companies[company_name] = {
                    "company_name": company_name,
                    "industry": lead.get("industry", ""),
                    "region": lead.get("location", "")
                }

        # Research batch com semáforo (max 2 concurrent)
        research_results = await account_researcher.research_batch(
            list(companies.values()),
            max_concurrent=2
        )

        log.info(f"[scout] Account Research concluído para {len(research_results)} contas")

        # Update DB com results
        for lead_row in leads:
            lead = dict(lead_row)
            company_name = lead.get("company")
            lead_id = lead.get("lead_id")

            if company_name not in research_results:
                continue

            ar_result = research_results[company_name]

            sql = """
                UPDATE scout_leads SET
                    company_description = ?,
                    company_size = ?,
                    company_revenue_range = ?,
                    tech_stack = ?,
                    identified_pain_points = ?,
                    current_solution = ?,
                    competitive_landscape = ?,
                    account_research_source = ?,
                    account_research_cache_ttl = ?
                WHERE lead_id = ?
            """

            await self.memory._db.execute(sql, (
                ar_result.company_description,
                ar_result.company_size,
                ar_result.company_revenue_range,
                json.dumps(ar_result.tech_stack),
                json.dumps(ar_result.identified_pain_points),
                ar_result.current_solution,
                json.dumps(ar_result.competitive_landscape),
                ar_result.data_source,
                168,  # 7 dias em horas
                lead_id
            ))

        await self.memory._db.commit()

    # ──────────────────────────────────────────────────────────
    # PHASE 3: QUALIFICATION & COPYWRITING (Scout Hunter 2.0 — ADVANCED)
    # ──────────────────────────────────────────────────────────

    async def _qualify_and_generate_copy(self, campaign_id: str, limit: int = 100) -> None:
        """
        Fase 3 completa: Qualification avançada + Copy Generation contextual.

        NOVO em Scout Hunter 2.0:
        - Qualification usa contexto de fit_score, intent_signals, pain_points
        - Copy menciona company context, pain points específicos, decision maker
        - 2 filtros: Fit Score >= 60 (Discovery Matrix) + BANT >= 70 (Qualification)
        """
        log.info(f"[scout] Iniciando Qualification Avançada para campaign '{campaign_id}'")

        # Query leads aprovados em Account Research (status 'novo' com fit_score >= 60)
        query = """
            SELECT
                lead_id, name, company, role, email_address,
                fit_score, intent_signals_level, intent_signals_evidence, budget_indicator,
                company_description, tech_stack, identified_pain_points, current_solution,
                competitive_landscape, decision_makers
            FROM scout_leads
            WHERE campaign_id = ? AND status = 'novo' AND fit_score >= 60
            LIMIT ?
        """

        async with self.memory._db.execute(query, (campaign_id, limit)) as cur:
            leads = await cur.fetchall()

        if not leads:
            log.info(f"[scout] Nenhum lead qualificado em Discovery Matrix para Qualification")
            return

        log.info(f"[scout] Qualificando {len(leads)} leads com contexto avançado")

        results = {"qualified": 0, "written": 0, "rejected": 0}
        semaphore = asyncio.Semaphore(3)

        async def _process_lead_advanced(lead_row):
            lead = dict(lead_row)
            lead_id = lead["lead_id"]

            # Executar qualification + copy em paralelo com semáforo
            async with semaphore:
                # Step 1: Qualification avançada (BANT com contexto)
                bant_score, bant_reasoning = await self._qualify_lead_advanced(lead)

                # Step 2: Se aprovado (BANT >= 70 ou qualification_status == "high_priority")
                if bant_score >= 70:
                    results["qualified"] += 1

                    # Step 3: Copy contextual
                    copy_text = await self._generate_copy_advanced(lead)

                    # Update DB com BANT score + copy
                    sql = """
                        UPDATE scout_leads SET
                            bant_score = ?,
                            bant_reasoning = ?,
                            qualification_status = ?,
                            status = ?,
                            content_draft = ?,
                            copy_target_decision_maker = ?,
                            updated_at = ?
                        WHERE lead_id = ?
                    """

                    await self.memory._db.execute(sql, (
                        bant_score,
                        bant_reasoning,
                        "high_priority" if bant_score >= 85 else "medium",
                        "aprovado",
                        copy_text[:2000] if copy_text else None,
                        lead.get("name", "Unknown"),
                        datetime.now().isoformat(),
                        lead_id
                    ))

                    results["written"] += 1

                else:
                    results["rejected"] += 1
                    # Update DB com rejeição
                    await self.memory._db.execute(
                        """
                        UPDATE scout_leads SET
                            bant_score = ?,
                            bant_reasoning = ?,
                            qualification_status = ?,
                            status = ?,
                            updated_at = ?
                        WHERE lead_id = ?
                        """,
                        (bant_score, bant_reasoning, "not_qualified", "rejeitado",
                         datetime.now().isoformat(), lead_id)
                    )

        # Processar leads em paralelo
        tasks = [_process_lead_advanced(l) for l in leads]
        await asyncio.gather(*tasks)

        await self.memory._db.commit()

        log.info(
            f"[scout] Qualification avançada completa: "
            f"Qualificados={results['qualified']}, "
            f"Copy gerado={results['written']}, "
            f"Rejeitados={results['rejected']}"
        )

    async def _qualify_lead_advanced(self, lead: Dict) -> tuple[int, str]:
        """
        Qualification BANT contextualizado com dados de Discovery Matrix + Account Research.

        Input do lead inclui:
        - fit_score, intent_signals, budget_indicator (de Discovery Matrix)
        - company_description, tech_stack, pain_points (de Account Research)

        Output: (bant_score, bant_reasoning)
        """
        # Construir contexto rico do lead
        pain_points = []
        try:
            pain_points_json = lead.get("identified_pain_points", "[]")
            if isinstance(pain_points_json, str):
                pain_points = json.loads(pain_points_json)
        except:
            pain_points = []

        tech_stack = []
        try:
            tech_stack_json = lead.get("tech_stack", "[]")
            if isinstance(tech_stack_json, str):
                tech_stack = json.loads(tech_stack_json)
        except:
            tech_stack = []

        ctx = (
            f"LEAD PROFILE:\n"
            f"- Name: {lead.get('name', 'Unknown')}\n"
            f"- Company: {lead.get('company', '')}\n"
            f"- Role: {lead.get('role', 'Unknown')}\n"
            f"\nDISCOVERY MATRIX RESULTS:\n"
            f"- Fit Score: {lead.get('fit_score', 0)}/100\n"
            f"- Intent Signals: {lead.get('intent_signals_level', 0)}/5\n"
            f"- Budget Range: {lead.get('budget_indicator', 'Unknown')}\n"
            f"\nACCOUNT RESEARCH:\n"
            f"- Description: {lead.get('company_description', 'N/A')[:200]}\n"
            f"- Tech Stack: {', '.join(tech_stack[:5]) if tech_stack else 'Unknown'}\n"
            f"- Pain Points: {', '.join(pain_points[:3]) if pain_points else 'Unknown'}\n"
            f"- Current Solution: {lead.get('current_solution', 'Unknown')}"
        )

        prompt = (
            "You are a B2B BANT qualification expert (Budget/Authority/Need/Timeline).\n\n"
            "Analyze the lead and company context. Score on 4 dimensions:\n\n"
            "BUDGET (0-25): Does company have budget for solution?\n"
            "AUTHORITY (0-25): Is lead a decision-maker?\n"
            "NEED (0-25): Do identified pain points match?\n"
            "TIMELINE (0-25): Urgency from signals?\n\n"
            "Return ONLY valid JSON:\n"
            "{\n"
            '  "bant_score": <0-100 sum of dimensions>,\n'
            '  "reasoning": "<brief explanation>"\n'
            "}\n\n"
            f"{ctx}"
        )

        try:
            response = await self.cascade.call(
                role=CascadeRole.FAST,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=200,
            )

            raw = response.get("content", "{}")
            s = raw.find("{")
            e = raw.rfind("}") + 1

            if s != -1 and e > s:
                data = json.loads(raw[s:e])
                score = int(data.get("bant_score", 50))
                reasoning = data.get("reasoning", "")

                # Log Evidence entry para qualificação
                evidence = EvidenceEntry(
                    feature="scout_qualification",
                    decision=f"bant_score_{score}",
                    inputs={
                        "company": lead.get("company", ""),
                        "fit_score": lead.get("fit_score", 0),
                        "intent_level": lead.get("intent_signals_level", 0),
                        "pain_points": pain_points[:3],
                    },
                    output={
                        "bant_score": score,
                        "qualification_status": "high_priority" if score >= 75 else "medium" if score >= 50 else "low",
                    },
                    confidence=0.85,
                    model_used="cascade_fast_bant_scorer",
                    reasoning=reasoning,
                    executed=False,  # Qualificação não é execução
                )
                get_evidence_store().store(evidence)

                return max(0, min(100, score)), reasoning

        except Exception as e:
            log.warning(f"[scout] BANT qualification error: {e}")

        return 50, "Error in qualification, using default"

    async def _generate_copy_advanced(self, lead: Dict) -> str:
        """
        Geração de copy contextual mencionando:
        - Company context (indústria, tamanho, current solution)
        - Pain points identificados
        - Decision maker pelo nome
        """
        pain_points = []
        try:
            pain_points_json = lead.get("identified_pain_points", "[]")
            if isinstance(pain_points_json, str):
                pain_points = json.loads(pain_points_json)
        except:
            pain_points = []

        primary_pain = pain_points[0] if pain_points else "increase efficiency"

        ctx = (
            f"PERSONALIZATION DATA:\n"
            f"- Decision Maker: {lead.get('name', 'There')}\n"
            f"- Company: {lead.get('company', '')}\n"
            f"- Current Solution: {lead.get('current_solution', 'Manual processes')}\n"
            f"- Key Challenge: {primary_pain}\n"
        )

        prompt = (
            "You are an expert B2B copywriter specializing in personalized outreach.\n\n"
            "Write 3 ready-to-send formats that reference the specific pain point and company context:\n"
            "1. Professional Email (5-6 sentences, mention pain point explicitly)\n"
            "2. LinkedIn DM (2-3 sentences, personal tone)\n"
            "3. WhatsApp (1-2 sentences, casual but professional)\n\n"
            "Be direct, specific, and reference their company's situation.\n"
            "Reply in Portuguese.\n\n"
            f"{ctx}"
        )

        try:
            response = await self.cascade.call(
                role=CascadeRole.CREATIVE,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=400,
            )

            return response.get("content", "")

        except Exception as e:
            log.warning(f"[scout] Copy generation error: {e}")
            return ""

    async def _get_pipeline_results(self, campaign_id: str) -> Dict[str, Any]:
        """Coleta resultados finais do pipeline para retorno."""
        # Query funnel stats
        async with self.memory._db.execute(
            "SELECT status, COUNT(*) as count FROM scout_leads WHERE campaign_id = ? GROUP BY status",
            (campaign_id,)
        ) as cur:
            stats = await cur.fetchall()

        funnel = {r["status"]: r["count"] for r in stats}

        # Query qualified count
        async with self.memory._db.execute(
            "SELECT COUNT(*) as count FROM scout_leads WHERE campaign_id = ? AND bant_score >= 70",
            (campaign_id,)
        ) as cur:
            row = await cur.fetchone()
            qualified_count = row["count"] if row else 0

        # Query copy generated count
        async with self.memory._db.execute(
            "SELECT COUNT(*) as count FROM scout_leads WHERE campaign_id = ? AND content_draft IS NOT NULL",
            (campaign_id,)
        ) as cur:
            row = await cur.fetchone()
            copy_count = row["count"] if row else 0

        return {
            "qualified": qualified_count,
            "written": copy_count,
            "rejected": funnel.get("rejeitado", 0),
            "funnel": funnel
        }

    # ──────────────────────────────────────────────────────────
    # MAIN PIPELINE
    # ──────────────────────────────────────────────────────────

    async def run_full_pipeline(self, campaign_id: str, limit: int = 100, niche: str = "geral", region: str = "geral") -> Dict[str, Any]:
        """
        Complete pipeline: Scrape → Enrich → Discovery Matrix → Account Research → Qualify → Generate Copy

        Scout Hunter 2.0: Com 5 fases em vez de 4, incluindo Discovery Matrix e Account Research.
        """
        log.info(f"[scout] Starting full pipeline for campaign '{campaign_id}'")

        # Store current niche/region para uso em métodos auxiliares
        self.current_niche = niche
        self.current_region = region

        # Enrich leads first
        await self.enrich_campaign(campaign_id, limit)

        # NEW: Phase 2.5 - Discovery Matrix
        await self._evaluate_discovery_matrix(campaign_id, limit)

        # NEW: Phase 2.75 - Account Research
        await self._research_accounts(campaign_id, limit)

        # Phase 3: QUALIFICATION AVANÇADA (com contexto de Discovery Matrix + Account Research)
        await self._qualify_and_generate_copy(campaign_id, limit)

        # Get final results
        results = await self._get_pipeline_results(campaign_id)

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
