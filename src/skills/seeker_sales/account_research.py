"""Account Research - Phase 2.75"""
import asyncio, json, logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

log = logging.getLogger("seeker.seeker_sales.account_research")

@dataclass
class DecisionMaker:
    name: str
    title: str
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    influence_level: str = "manager"

@dataclass
class AccountResearchResult:
    company_description: str
    company_size: str
    company_revenue_range: str
    tech_stack: List[str]
    identified_pain_points: List[str]
    current_solution: str
    competitive_landscape: List[Dict]
    decision_makers: List[DecisionMaker]
    data_source: str
    confidence_score: float
    research_timestamp: datetime = field(default_factory=datetime.utcnow)

class AccountResearcher:
    def __init__(self, cascade_adapter, web_searcher=None):
        self.cascade = cascade_adapter
        self.web_searcher = web_searcher
        self._company_cache = {}
        self._research_semaphore = asyncio.Semaphore(2)

    async def research_account(self, company_name: str, industry: str, region: str) -> AccountResearchResult:
        async with self._research_semaphore:
            cached = self._get_from_cache(company_name)
            if cached:
                return cached
            try:
                prompt = f"Analyze {company_name} ({industry}). Return JSON: company_description, company_size, tech_stack, identified_pain_points, confidence_score"
                response = await self.cascade.call(role="FAST", messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=800)
                result = self._parse_response(response.get("content", "{}"))
                makers = await self.find_decision_makers(company_name, industry)
                result.decision_makers = makers
                self._cache_result(company_name, result)
                return result
            except Exception as e:
                log.error(f"Research error: {e}")
                return self._default()

    async def research_batch(self, companies: List[Dict], max_concurrent: int = 2) -> Dict[str, 'AccountResearchResult']:
        """Pesquisa múltiplas empresas em batch com semáforo de concorrência"""
        semaphore = asyncio.Semaphore(max_concurrent)
        results = {}

        async def research_one(company: Dict):
            async with semaphore:
                result = await self.research_account(
                    company.get("company_name", ""),
                    company.get("industry", ""),
                    company.get("region", "")
                )
                results[company.get("company_name", "")] = result

        tasks = [research_one(c) for c in companies]
        await asyncio.gather(*tasks, return_exceptions=True)
        return results

    async def find_decision_makers(self, company_name: str, industry: str) -> List[DecisionMaker]:
        try:
            if not self.web_searcher:
                return []
            results = await self.web_searcher.search(f"{company_name} CEO founder")
            response = await self.cascade.call(role="FAST", messages=[{"role": "user", "content": f"Extract decision makers from {company_name}"}], temperature=0.0, max_tokens=400)
            return self._parse_makers(response.get("content", "[]"))
        except:
            return []

    def _parse_response(self, text: str) -> AccountResearchResult:
        try:
            s, e = text.find("{"), text.rfind("}") + 1
            # If no JSON found, return default
            if s < 0 or e <= s:
                return self._default()
            data = json.loads(text[s:e])
            return AccountResearchResult(
                company_description=data.get("company_description", "")[:500],
                company_size=data.get("company_size", "unknown"),
                company_revenue_range=data.get("company_revenue_range", "unknown"),
                tech_stack=data.get("tech_stack", [])[:10],
                identified_pain_points=data.get("identified_pain_points", [])[:5],
                current_solution=data.get("current_solution", "")[:300],
                competitive_landscape=data.get("competitive_landscape", [])[:3],
                decision_makers=[],
                data_source="llm_analysis",
                confidence_score=float(data.get("confidence_score", 0.7))
            )
        except:
            return self._default()

    def _parse_makers(self, text: str) -> List[DecisionMaker]:
        try:
            s, e = text.find("["), text.rfind("]") + 1
            data = json.loads(text[s:e]) if s >= 0 and e > s else []
            return [DecisionMaker(name=d.get("name", "Unknown"), title=d.get("title", "Unknown"), email=d.get("email"), linkedin_url=d.get("linkedin_url"), influence_level=d.get("influence_level", "manager")) for d in data if isinstance(d, dict)]
        except:
            return []

    def _get_from_cache(self, company: str) -> Optional[AccountResearchResult]:
        if company not in self._company_cache:
            return None
        result, ts = self._company_cache[company]
        # Handle both datetime objects and ISO strings (for test compatibility)
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if (datetime.utcnow() - ts) < timedelta(hours=168):
            result.data_source = "cache_hit"
            return result
        del self._company_cache[company]
        return None

    def _cache_result(self, company: str, result: AccountResearchResult):
        self._company_cache[company] = (result, datetime.utcnow())

    def _default(self) -> AccountResearchResult:
        return AccountResearchResult("Company information not available", "unknown", "unknown", [], [], "", [], [], "fallback", 0.0)

    def _parse_analysis_response(self, company_name: str, response: str) -> AccountResearchResult:
        """Parse analysis response (alias for _parse_response for compatibility)"""
        return self._parse_response(response)

    def clear_cache(self):
        """Clear the company cache"""
        self._company_cache.clear()
