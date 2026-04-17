"""
Seeker.Bot — Event Map Scout Engine
src/skills/event_map_scout/scout.py

Máquina de descoberta preditiva de eventos em municípios do interior usando histórico.
"""

import asyncio
import json
import logging
from typing import Dict, List, Any
from datetime import datetime

from src.core.pipeline import SeekerPipeline
from src.providers.base import LLMRequest, invoke_with_fallback
from config.models import CognitiveRole
from src.core.utils import parse_llm_json

from src.skills.event_map_scout.prompts import (
    EVENT_CATEGORIES, EXTRACTION_PROMPT, SYNTHESIS_PROMPT
)
from src.skills.event_map_scout.pdf_builder import build_event_map_pdf

log = logging.getLogger("seeker.event_map.engine")

class EventMapEngine:
    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self.current_year = datetime.now().year
        self.last_year = self.current_year - 1
        self.last_last_year = self.current_year - 2

    async def scan_city(self, cidade: str, estado: str) -> Dict[str, Any]:
        """Varredura pontual de uma cidade: descobre, salva no DB e gera PDF."""
        log.info(f"[event_map] 🔍 Iniciando mapeamento temporal de {cidade} - {estado}")
        
        # FASE 1: Extração por Categoria em Paralelo
        tasks = []
        for cat_name, queries in EVENT_CATEGORIES.items():
            tasks.append(self._scan_category(cidade, estado, cat_name, queries))
        
        results = await asyncio.gather(*tasks)
        
        todas_extracao = []
        for res in results:
            if res: todas_extracao.extend(res)
            
        log.info(f"[event_map] 🧠 Total de ocorrências brutas extraídas: {len(todas_extracao)}")
        
        # FASE 2: Deduplicação Local (Merge)
        dedup_events = self._dedup_events(todas_extracao)
        log.info(f"[event_map] 🔗 Eventos únicos pós-merge: {len(dedup_events)}")
        
        # FASE 3: Persistir no DB
        saved_count = await self._save_to_db(dedup_events, cidade, estado)
        
        # FASE 4: Síntese e PDF
        report_md, pdf_path = await self._generate_report(cidade, estado)
        
        return {
            "cidade": cidade,
            "estado": estado,
            "total_extracted": len(todas_extracao),
            "total_unique": len(dedup_events),
            "total_saved": saved_count,
            "pdf_path": pdf_path,
            "markdown": report_md
        }

    async def _scan_category(self, cidade: str, estado: str, categoria: str, queries_tpl: List[str]) -> List[Dict]:
        cidade_slug = cidade.lower().replace(" ", "")
        
        search_snippets = []
        # Faz as buscas no Search API em paralelo para essa categoria
        async def _run_search(tpl: str):
            query = tpl.format(cidade=cidade, estado=estado, cidade_slug=cidade_slug)
            try:
                res = await self.pipeline.searcher.search(query, max_results=5)
                return res.to_context(max_results=5) if res.results else ""
            except Exception as e:
                log.warning(f"[event_map] Erro em busca '{query}': {e}")
                return ""

        search_tasks = [_run_search(q) for q in queries_tpl]
        search_contexts = await asyncio.gather(*search_tasks)
        
        full_context = "\n\n".join([c for c in search_contexts if c])
        if not full_context.strip():
            return []

        # Extração via LLM FAST
        prompt = EXTRACTION_PROMPT.format(
            cidade=cidade, 
            categoria=categoria,
            last_last_year=self.last_last_year,
            last_year=self.last_year,
            current_year=self.current_year,
            search_context=full_context[:6000] # Limite para não explodir tokens
        )

        try:
            resp = await invoke_with_fallback(
                CognitiveRole.FAST,
                LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                ),
                self.pipeline.model_router,
                self.pipeline.api_keys
            )
            
            data = parse_llm_json(resp.text)
            eventos = data.get("eventos", [])
            for e in eventos:
                e["categoria"] = categoria # Garante que a categoria está certa
            return eventos
            
        except Exception as e:
            log.warning(f"[event_map] JSON de extração falhou para {categoria}: {e}")
            return []

    def _dedup_events(self, raw_events: List[Dict]) -> List[Dict]:
        """Normaliza nomes e mescla eventos duplicados identificados em categorias múltiplas."""
        import copy
        unique_map = {}
        
        def normalizar(n):
            s = str(n).lower().replace("-", " ").replace("ª", "").replace("°", "")
            # Remove o numero da edicao do comeco se houver (ex: 32 expoagro -> expoagro)
            parts = s.split()
            if parts and parts[0].isdigit():
                parts.pop(0)
            return " ".join(parts).strip()
            
        for e in raw_events:
            nome = e.get("nome_evento", "")
            if not nome or e.get("score_oportunidade", 0) < 4: 
                continue
                
            chave = normalizar(nome)
            
            if chave in unique_map:
                existing = unique_map[chave]
                # Merge campos nulos
                for kb, vb in e.items():
                    if not existing.get(kb) and vb:
                        existing[kb] = vb
                # Mescla historico
                if e.get("historico_anos") and e["historico_anos"] != existing.get("historico_anos"):
                    existing["historico_anos"] = f"{existing.get('historico_anos', '')} | {e['historico_anos']}"
                # Mescla urls
                ext_urls = existing.get("fontes_urls", [])
                new_urls = e.get("fontes_urls", [])
                if isinstance(ext_urls, list) and isinstance(new_urls, list):
                    existing["fontes_urls"] = list(set(ext_urls + new_urls))
            else:
                e["nome_normalizado"] = chave
                unique_map[chave] = copy.deepcopy(e)
                
        return list(unique_map.values())

    async def _save_to_db(self, eventos: List[Dict], cidade: str, estado: str) -> int:
        count = 0
        for ev in eventos:
            try:
                # Pega valores com defaults
                n = ev.get("nome_evento", "Desconhecido")
                nn = ev.get("nome_normalizado", "desconhecido")
                c = ev.get("categoria", "GERAL")
                p = str(ev.get("periodo", ""))
                p_mes = ev.get("periodo_mes_num")
                h_anos = str(ev.get("historico_anos", ""))
                s_prev = str(ev.get("status_previsao", "previsto"))
                porte = str(ev.get("porte_estimado", ""))
                v_contrato = str(ev.get("valor_contrato_publico", ""))
                d_nome = str(ev.get("decisor_nome", ""))
                d_cargo = str(ev.get("decisor_cargo", ""))
                tel = str(ev.get("telefone", ""))
                ig = str(ev.get("instagram", ""))
                urls_str = json.dumps(ev.get("fontes_urls", []))

                sql = """
                    INSERT INTO event_map 
                    (cidade, estado, nome_evento, nome_normalizado, categoria, historico_anos,
                     historico_mes, status_previsao, porte_estimado, valor_contrato_publico, 
                     decisor_nome, decisor_cargo, telefone, instagram, fontes_urls)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(estado, cidade, nome_normalizado) DO UPDATE SET
                    status_previsao=excluded.status_previsao,
                    historico_anos=excluded.historico_anos,
                    valor_contrato_publico=excluded.valor_contrato_publico,
                    telefone=excluded.telefone,
                    instagram=excluded.instagram,
                    fontes_urls=excluded.fontes_urls,
                    atualizado_em=CURRENT_TIMESTAMP
                """
                
                await self.pipeline.memory._db.execute(sql, (
                    cidade, estado, n, nn, c, h_anos, p_mes, s_prev, porte,
                    v_contrato, d_nome, d_cargo, tel, ig, urls_str
                ))
                count += 1
            except Exception as e:
                log.error(f"[event_map] DB Save faltal para {n}: {e}")
                
        await self.pipeline.memory._db.commit()
        return count

    async def _generate_report(self, cidade: str, estado: str) -> tuple[str, str]:
        # Busca no banco
        q = "SELECT * FROM event_map WHERE cidade=? AND estado=? ORDER BY historico_mes ASC"
        async with self.pipeline.memory._db.execute(q, (cidade, estado)) as cur:
            rows = await cur.fetchall()
            columns = [col[0] for col in cur.description]
            event_dicts = [dict(zip(columns, row)) for row in rows]
            
        events_json = json.dumps(event_dicts, indent=2, ensure_ascii=False)
        
        prompt = SYNTHESIS_PROMPT.format(
            cidade=cidade, estado=estado,
            current_year=self.current_year, 
            next_year=self.current_year+1,
            current_month=datetime.now().month,
            events_json=events_json
        )
        
        try:
            resp = await invoke_with_fallback(
                CognitiveRole.SYNTHESIS,
                LLMRequest(messages=[{"role": "user", "content": prompt}]),
                self.pipeline.model_router,
                self.pipeline.api_keys
            )
            report_md = resp.text.strip('`').removeprefix("markdown\n").removeprefix("md\n")
            
            pdf_path = build_event_map_pdf(report_md, cidade, estado, events=event_dicts)
            return report_md, pdf_path
            
        except Exception as e:
            log.error(f"[event_map] Falha no report: {e}")
            return "Erro na síntese.", ""
