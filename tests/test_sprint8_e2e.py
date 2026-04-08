"""
End-to-end tests for Sprint 8 integrations.
Validates TFIDFSearch, IntentCard, and OODALoop working together.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.core.memory.embeddings import GeminiEmbedder, SemanticSearch
from src.core.memory.tfidf_search import TFIDFSearch
from src.core.intent_card import IntentClassifier, IntentType, RiskLevel
from src.core.reasoning.ooda_loop import OODALoop, LoopResult
from src.core.pipeline import SeekerPipeline
from src.core.router.cognitive_load import CognitiveDepth


# Mock Memory Protocol
class MockMemory:
    async def load_all_embeddings(self):
        return {1: [0.1, 0.2], 2: [0.3, 0.4]}

    async def get_facts(self, min_confidence=0.0, limit=9999):
        return [
            {"id": 1, "fact": "Python is powerful"},
            {"id": 2, "fact": "JavaScript is everywhere"},
        ]

    async def store_embedding(self, fact_id, vector):
        pass

    async def delete_embedding(self, fact_id):
        pass

    async def search_facts(self, query, limit=5):
        return []

    async def get_episode_stats(self):
        return {"total_episodes": 0, "total_cost_usd": 0.0, "avg_latency_ms": None}


class TestE2ETFIDFIntegration:
    """Test TFIDFSearch fallback in SemanticSearch."""

    @pytest.mark.asyncio
    async def test_tfidf_fallback_when_gemini_fails(self):
        """E2E: TFIDFSearch fallback when Gemini unavailable."""

        class FailingEmbedder(GeminiEmbedder):
            async def embed(self, text):
                return []  # Simulate Gemini failure

        memory = MockMemory()
        embedder = FailingEmbedder("fake_key")
        search = SemanticSearch(embedder, memory)
        await search.load()

        # Query should use TF-IDF fallback
        results = await search.find_similar("Python", top_k=2)

        assert len(results) > 0, "TF-IDF should provide fallback results"
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

    @pytest.mark.asyncio
    async def test_find_similar_facts_with_tfidf_fallback(self):
        """E2E: find_similar_facts uses TF-IDF when Gemini fails."""

        class FailingEmbedder(GeminiEmbedder):
            async def embed(self, text):
                return []

        memory = MockMemory()
        memory.get_facts = AsyncMock(
            return_value=[
                {"id": 1, "fact": "Python programming", "confidence": 0.9},
                {"id": 2, "fact": "JavaScript basics", "confidence": 0.8},
            ]
        )

        embedder = FailingEmbedder("fake_key")
        search = SemanticSearch(embedder, memory)
        await search.load()

        results = await search.find_similar_facts("Python")

        assert len(results) > 0
        assert all("similarity" in r for r in results)


class TestE2EIntentCardIntegration:
    """Test IntentCard blocking in pipeline."""

    def test_intent_classification_blocks_delete(self):
        """E2E: IntentCard blocks delete actions."""
        classifier = IntentClassifier()

        intent = classifier.classify("delete all user data")

        assert intent.risk_level == RiskLevel.HIGH
        assert intent.requires_approval()
        assert len(intent.reasoning) > 0  # Reasoning should exist

    def test_intent_classification_allows_information(self):
        """E2E: IntentCard allows information requests."""
        classifier = IntentClassifier()

        intent = classifier.classify("What is the capital of France?")

        # Should be either INFORMATION or LEARNING
        assert intent.intent_type in [IntentType.INFORMATION, IntentType.LEARNING]
        assert intent.risk_level == RiskLevel.LOW
        assert not intent.requires_approval()

    def test_intent_includes_permissions(self):
        """E2E: IntentCard includes required permissions."""
        classifier = IntentClassifier()

        intent = classifier.classify("create new user")

        assert len(intent.required_permissions) > 0
        assert "read:user_input" in intent.required_permissions


class TestE2EOODALoopIntegration:
    """Test OODALoop tracking and statistics."""

    def test_ooda_loop_tracks_iterations(self):
        """E2E: OODALoop properly tracks message iterations."""
        from src.core.reasoning.ooda_loop import ObservationData, OrientationModel, Decision, ActionResult

        loop = OODALoop()

        # Simulate 3 iterations
        for i in range(3):
            iteration = loop.history[-1] if loop.history else None
            # Create new iteration
            from src.core.reasoning.ooda_loop import OODAIteration

            ooda_iter = OODAIteration(
                iteration_id=f"msg_{i}",
                user_input=f"test {i}",
                observation=ObservationData(user_input=f"test {i}"),
                orientation=OrientationModel(confidence=0.9),
                decision=Decision(
                    action_type="respond",
                    autonomy_tier=3,
                    verification_required=False,
                ),
                action_result=ActionResult(success=True, latency_ms=100),
                result=LoopResult.SUCCESS,
                total_latency_ms=100,
            )
            loop.history.append(ooda_iter)

        stats = loop.get_stats()

        assert stats["total_iterations"] == 3
        assert stats["success_rate"] == 1.0
        assert stats["avg_latency_ms"] == 100

    def test_ooda_loop_tracks_blocked_actions(self):
        """E2E: OODALoop tracks blocked (HIGH-RISK) actions."""
        from src.core.reasoning.ooda_loop import OODAIteration

        loop = OODALoop()

        # Add 2 successes
        for i in range(2):
            iteration = OODAIteration(
                iteration_id=f"iter_{i}",
                user_input=f"query {i}",
                result=LoopResult.SUCCESS,
                total_latency_ms=100,
            )
            loop.history.append(iteration)

        # Add 1 blocked
        blocked = OODAIteration(
            iteration_id="iter_blocked",
            user_input="delete everything",
            result=LoopResult.BLOCKED,
            total_latency_ms=50,
        )
        loop.history.append(blocked)

        stats = loop.get_stats()

        assert stats["total_iterations"] == 3
        assert stats["blocked_count"] == 1
        assert stats["success_rate"] == 2 / 3  # 0.666...


class TestE2EIntegrationFlow:
    """Test complete flow of all Sprint 8 components."""

    def test_full_safety_flow(self):
        """E2E: Full flow from IntentCard blocking to OODA logging."""

        # 1. IntentCard classifies dangerous action
        classifier = IntentClassifier()
        dangerous = classifier.classify("delete database")

        assert dangerous.risk_level == RiskLevel.HIGH

        # 2. Should be blocked before reaching OODA
        blocked = dangerous.requires_approval()
        assert blocked is True

        # 3. OODALoop records the blocked decision
        from src.core.reasoning.ooda_loop import OODAIteration

        loop = OODALoop()
        blocked_iteration = OODAIteration(
            iteration_id="dangerous_1",
            user_input="delete database",
            result=LoopResult.BLOCKED,  # Action was blocked
            total_latency_ms=25,  # Quick rejection
        )
        loop.history.append(blocked_iteration)

        # 4. Verify stats show the block
        stats = loop.get_stats()
        assert stats["blocked_count"] == 1

    def test_safe_information_flow(self):
        """E2E: Safe information request flows through all components."""

        # 1. IntentCard allows information request
        classifier = IntentClassifier()
        safe = classifier.classify("How does photosynthesis work?")

        assert safe.intent_type == IntentType.INFORMATION
        assert safe.risk_level == RiskLevel.LOW
        assert not safe.requires_approval()

        # 2. OODA Loop processes successfully
        from src.core.reasoning.ooda_loop import OODAIteration

        loop = OODALoop()
        success_iteration = OODAIteration(
            iteration_id="info_1",
            user_input="How does photosynthesis work?",
            result=LoopResult.SUCCESS,
            total_latency_ms=450,
        )
        loop.history.append(success_iteration)

        # 3. Stats show success
        stats = loop.get_stats()
        assert stats["success_count"] == 1
        assert stats["success_rate"] == 1.0


class TestE2EInteroperability:
    """Test that all Sprint 8 components work together without conflicts."""

    def test_no_conflicts_between_components(self):
        """E2E: Components don't interfere with each other."""

        # Create instances of all components
        classifier = IntentClassifier()
        loop = OODALoop()

        # Process a query through both
        query = "What is AI?"

        # IntentCard processes
        intent = classifier.classify(query)

        # OODALoop processes independently
        from src.core.reasoning.ooda_loop import OODAIteration
        iteration = OODAIteration(
            iteration_id="test",
            user_input=query,
            result=LoopResult.SUCCESS,
            total_latency_ms=200,
        )
        loop.history.append(iteration)

        # Both should work without errors
        assert intent.intent_type == IntentType.INFORMATION
        assert loop.get_stats()["total_iterations"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
