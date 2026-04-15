"""Scout Hunter 2.0 — Advanced Testing (Track C5)"""
import asyncio
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.skills.scout_hunter.discovery_matrix import DiscoveryMatrix, DiscoveryMatrixResult
from src.skills.scout_hunter.account_research import AccountResearcher, AccountResearchResult

# Mock cascade adapter for testing
class MockCascade:
    async def call(self, role, messages, temperature=0.2, max_tokens=300):
        if "fit_score" in messages[0]["content"].lower():
            return {
                "content": '{"fit_score": 75, "fit_score_reasoning": "Good fit", "intent_signals_level": 4, "intent_signals_evidence": ["hiring"], "budget_indicator": "50k-100k"}'
            }
        elif "decision maker" in messages[0]["content"].lower():
            return {
                "content": '[{"name": "John CEO", "title": "CEO", "email": "john@company.com", "influence_level": "executive"}]'
            }
        else:
            return {
                "content": '{"company_description": "Tech company", "company_size": "startup", "tech_stack": ["AWS", "React"], "identified_pain_points": ["scaling", "costs"], "confidence_score": 0.8}'
            }

@pytest.mark.asyncio
async def test_discovery_matrix_evaluate():
    """Test Discovery Matrix evaluation"""
    cascade = MockCascade()
    dm = DiscoveryMatrix(cascade)
    
    lead = {
        "name": "John",
        "company": "TechCorp",
        "role": "CTO",
        "industry": "software",
        "location": "SãoPaulo",
        "bio_summary": "Tech leader"
    }
    
    result = await dm.evaluate_lead(lead, "eventos", "sãopaulo")
    
    assert result.fit_score >= 0
    assert result.fit_score <= 100
    assert result.intent_signals_level >= 0
    assert result.intent_signals_level <= 5
    assert result.passed_minimum_threshold == (result.fit_score >= 60)
    print("✅ Discovery Matrix test passed")

@pytest.mark.asyncio
async def test_account_research_single():
    """Test Account Research for single company"""
    cascade = MockCascade()
    ar = AccountResearcher(cascade, web_searcher=None)
    
    result = await ar.research_account("TechCorp", "software", "SãoPaulo")
    
    assert isinstance(result, AccountResearchResult)
    assert result.company_description != ""
    assert isinstance(result.tech_stack, list)
    assert isinstance(result.identified_pain_points, list)
    print("✅ Account Research test passed")

@pytest.mark.asyncio
async def test_account_research_batch():
    """Test batch research with semaphore"""
    cascade = MockCascade()
    ar = AccountResearcher(cascade, web_searcher=None)
    
    companies = [
        {"company_name": "Company1", "industry": "tech", "region": "SP"},
        {"company_name": "Company2", "industry": "events", "region": "BH"},
        {"company_name": "Company3", "industry": "wedding", "region": "RJ"},
    ]
    
    results = await ar.research_batch(companies, max_concurrent=2)
    
    assert len(results) == 3
    for name, result in results.items():
        assert isinstance(result, AccountResearchResult)
    print("✅ Account Research batch test passed")

async def main():
    print("\n[Scout Hunter 2.0 — Advanced Tests]")
    await test_discovery_matrix_evaluate()
    await test_account_research_single()
    await test_account_research_batch()
    print("\n✅ All Scout Hunter tests passed!\n")

if __name__ == "__main__":
    asyncio.run(main())
