"""
Account Research — Pesquisa Profunda de Contas

Fase 2.75 do Scout Hunter 2.0:
- Pesquisa empresa: descrição, tamanho, tech stack, pain points
- Encontra decision makers específicos
- Cache 7 dias por company_name (empresa muda pouco)
- Parallelização com Semaphore(2) pois é pesada
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

log = logging.getLogger("seeker.scout_hunter.account_research")


@dataclass
class DecisionMaker:
    """Decisor/executivo encontrado na empresa"""
    name: str
    title: str
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    influence_level: str = "manager"  # "executive", "manager", "influencer"


@dataclass
class AccountResearchResult:
    """Resultado completo da pesquisa de conta"""
    company_description: str            # O que empresa faz
    company_size: str                   # "startup", "scaleup", "enterprise"
    company_revenue_range: str          # Estimativa de faturamento
    tech_stack: List[str]               # ["Salesforce", "AWS", "Stripe", ...]
    identified_pain_points: List[str]   # ["integration_complexity", "cost_optimization", ...]
    current_solution: str               # Solução que usam hoje
    competitive_landscape: List[Dict]   # [{"name": "CompetitorA", "position": "market_leader"}]
    decision_makers: List[DecisionMaker] = field(default_factory=list)
    data_source: str = "unknown"        # "crunchbase", "linkedin", "google", "cache_hit"
    confidence_score: float = 0.5       # 0.0-1.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class AccountResearcher:
    """
    Pesquisa profunda de contas (empresas).

    1. Verifica cache (TTL 7 dias)
    2. Se não em cache: web_search + LLM analysis
    3. Extrai: company description, tech stack, pain points, decision makers
    4. Persiste em cache
    """

    def __init__(self, cascade_adapter, web_searcher=None):
        """
        Inicializa Account Researcher.

        Args:
            cascade_adapter: CascadeAdapter para chamadas LLM
            web_searcher: WebSearcher para pesquisa na web (opcional)
        """
        self.cascade = cascade_adapter
        self.web_searcher = web_searcher
        self._company_cache = {}  # {company_name: (result, timestamp)}
        self._cache_ttl_hours = 168  # 7 dias

    def _is_cache_valid(self, cached_timestamp: str) -> bool:
        """Verifica se entry em cache ainda é válido."""
        try:
            cached_time = datetime.fromisoformat(cached_timestamp)
            age = datetime.now() - cached_time
            return age < timedelta(hours=self._cache_ttl_hours)
        except:
            return False

    async def research_account(
        self,
        company_name: str,
        industry: str = "",
        region: str = ""
    ) -> AccountResearchResult:
        """
        Pesquisa empresa completa.

        Args:
            company_name: Nome da empresa
            industry: Indústria (opcional)
            region: Região (opcional)

        Returns:
            AccountResearchResult com dados da empresa
        """
        # 1. Verificar cache
        if company_name in self._company_cache:
            cached_result, cached_time = self._company_cache[company_name]
            if self._is_cache_valid(cached_time):
                log.info(f"[account_research] Cache HIT para '{company_name}'")
                cached_result.data_source = "cache_hit"
                return cached_result

        log.info(f"[account_research] Iniciando pesquisa de '{company_name}'")

        try:
            # 2. Pesquisar na web (se disponível)
            search_results = ""
            if self.web_searcher:
                try:
                    search_results = await self._web_search(company_name, industry)
                except Exception as e:
                    log.warning(f"[account_research] Web search falhou: {e}")

            # 3. Chamar LLM para análise
            result = await self._analyze_company(company_name, industry, search_results)

            # 4. Encontrar decision makers
            if self.web_searcher:
                try:
                    decision_makers = await self._find_decision_makers(company_name)
                    result.decision_makers = decision_makers
                except Exception as e:
                    log.warning(f"[account_research] Não conseguiu encontrar decision makers: {e}")

            # 5. Cache
            self._company_cache[company_name] = (result, datetime.now().isoformat())

            log.info(
                f"[account_research] Pesquisa concluída para '{company_name}': "
                f"size={result.company_size}, pain_points={len(result.identified_pain_points)}"
            )

            return result

        except Exception as e:
            log.error(f"[account_research] Erro ao pesquisar '{company_name}': {e}", exc_info=True)
            return self._default_result(company_name)

    async def _web_search(self, company_name: str, industry: str) -> str:
        """Pesquisa web sobre a empresa (se web_searcher disponível)."""
        if not self.web_searcher:
            return ""

        try:
            query = f"{company_name}"
            if industry:
                query += f" {industry}"

            # Mock: retornar query (em produção, seria web_searcher.search())
            log.info(f"[account_research] Web search query: {query}")
            return f"Search results for {query}: (mock data)"

        except Exception as e:
            log.warning(f"[account_research] Web search error: {e}")
            return ""

    async def _analyze_company(
        self,
        company_name: str,
        industry: str,
        search_results: str
    ) -> AccountResearchResult:
        """Analisa empresa via LLM."""
        prompt = self._build_analysis_prompt(company_name, industry, search_results)

        try:
            response = await self.cascade.call(
                role="FAST",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
            )

            return self._parse_analysis_response(company_name, response.get("content", "{}"))

        except Exception as e:
            log.error(f"[account_research] LLM analysis error: {e}")
            return self._default_result(company_name)

    def _build_analysis_prompt(self, company_name: str, industry: str, search_results: str) -> str:
        """Constrói prompt para análise de empresa."""
        return (
            "You are a B2B account research expert. Analyze the company data and return ONLY valid JSON.\n\n"
            "Provide:\n"
            "1. Company description (what they do)\n"
            "2. Company size (startup/scaleup/enterprise)\n"
            "3. Revenue range estimate\n"
            "4. Tech stack (tools/platforms they likely use)\n"
            "5. Identified pain points (problems they likely face)\n"
            "6. Current solution (what they use today)\n"
            "7. Competitive landscape (top 3 competitors)\n\n"

            "Return JSON:\n"
            "{\n"
            '  "company_description": "<what they do>",\n'
            '  "company_size": "<startup|scaleup|enterprise>",\n'
            '  "company_revenue_range": "<estimate>",\n'
            '  "tech_stack": ["tool1", "tool2", ...],\n'
            '  "identified_pain_points": ["pain1", "pain2", ...],\n'
            '  "current_solution": "<what they use>",\n'
            '  "competitive_landscape": [{"name": "CompetitorA", "position": "..."}]\n'
            "}\n\n"

            f"Company: {company_name}\n"
            f"Industry: {industry if industry else 'Unknown'}\n"
            f"Search results:\n{search_results}"
        )

    def _parse_analysis_response(self, company_name: str, response_text: str) -> AccountResearchResult:
        """Parseia resposta JSON da análise."""
        try:
            # Extrair JSON
            s = response_text.find("{")
            e = response_text.rfind("}") + 1

            if s == -1 or e <= s:
                log.warning("[account_research] Nenhum JSON na resposta")
                return self._default_result(company_name)

            json_str = response_text[s:e]
            data = json.loads(json_str)

            # Parsear campos com validação
            tech_stack = data.get("tech_stack", [])
            if not isinstance(tech_stack, list):
                tech_stack = []

            pain_points = data.get("identified_pain_points", [])
            if not isinstance(pain_points, list):
                pain_points = []

            competitors = data.get("competitive_landscape", [])
            if not isinstance(competitors, list):
                competitors = []

            return AccountResearchResult(
                company_description=data.get("company_description", "")[:500],
                company_size=data.get("company_size", "unknown"),
                company_revenue_range=data.get("company_revenue_range", "unknown"),
                tech_stack=tech_stack,
                identified_pain_points=pain_points,
                current_solution=data.get("current_solution", "")[:200],
                competitive_landscape=competitors,
                data_source="llm_analysis",
                confidence_score=0.7
            )

        except (json.JSONDecodeError, ValueError) as e:
            log.warning(f"[account_research] Parse error: {e}")
            return self._default_result(company_name)

    async def _find_decision_makers(self, company_name: str) -> List[DecisionMaker]:
        """Encontra decision makers da empresa via web search."""
        if not self.web_searcher:
            return []

        try:
            # Mock: em produção seria search("company_name decision makers")
            log.info(f"[account_research] Procurando decision makers para '{company_name}'")

            # Retornar lista vazia (em produção teria lógica real)
            return []

        except Exception as e:
            log.warning(f"[account_research] Decision maker search error: {e}")
            return []

    def _default_result(self, company_name: str) -> AccountResearchResult:
        """Resultado padrão para erros."""
        return AccountResearchResult(
            company_description="Company information not available",
            company_size="unknown",
            company_revenue_range="unknown",
            tech_stack=["unknown"],
            identified_pain_points=["data_unavailable"],
            current_solution="unknown",
            competitive_landscape=[],
            data_source="fallback",
            confidence_score=0.0
        )

    async def research_batch(
        self,
        companies: List[Dict[str, str]],
        max_concurrent: int = 2
    ) -> Dict[str, AccountResearchResult]:
        """
        Pesquisa múltiplas empresas em paralelo (com limite de concorrência).

        Args:
            companies: Lista de {company_name, industry, region}
            max_concurrent: Max 2 (pesquisa é pesada)

        Returns:
            Dict {company_name: AccountResearchResult}
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        results = {}

        async def _research_with_semaphore(company_data):
            async with semaphore:
                company_name = company_data.get("company_name")
                try:
                    result = await self.research_account(
                        company_name,
                        company_data.get("industry", ""),
                        company_data.get("region", "")
                    )
                    results[company_name] = result
                except Exception as e:
                    log.error(f"[account_research] Batch error for '{company_name}': {e}")
                    results[company_name] = self._default_result(company_name)

        # Executar em paralelo
        tasks = [_research_with_semaphore(c) for c in companies]
        await asyncio.gather(*tasks)

        return results

    def clear_cache(self):
        """Limpar cache (para testes ou refresh forçado)."""
        self._company_cache.clear()
        log.info("[account_research] Cache limpo")
