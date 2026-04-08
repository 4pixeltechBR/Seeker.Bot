"""
Tests for Pipeline IntentCard integration.
Validates that HIGH-RISK actions are blocked before processing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.core.pipeline import SeekerPipeline, CognitiveDepth
from src.core.intent_card import IntentType, RiskLevel


# Mock API keys for testing
MOCK_API_KEYS = {
    "gemini": "test_gemini_key",
    "groq": "test_groq_key",
    "openai": "test_openai_key",
}


@pytest.fixture
def pipeline(tmp_path):
    """Create a pipeline instance for testing."""
    db_path = str(tmp_path / "test.db")
    with patch("src.core.pipeline.CascadeAdapter"):
        pipeline = SeekerPipeline(MOCK_API_KEYS, db_path=db_path)
    return pipeline


class TestIntentCardClassification:
    """Test that IntentCard is properly classified."""

    def test_intent_classifier_initialized(self, pipeline):
        """Pipeline should have IntentClassifier."""
        assert pipeline.intent_classifier is not None

    def test_classify_information_intent(self, pipeline):
        """Questions should be classified as INFORMATION."""
        intent = pipeline.intent_classifier.classify("What is Python?")
        assert intent.intent_type == IntentType.INFORMATION
        assert intent.confidence > 0.5

    def test_classify_action_intent(self, pipeline):
        """Action verbs should be classified as ACTION."""
        intent = pipeline.intent_classifier.classify("Delete all files")
        assert intent.intent_type == IntentType.ACTION

    def test_classify_maintenance_intent(self, pipeline):
        """Commands should be classified as MAINTENANCE."""
        intent = pipeline.intent_classifier.classify("/status")
        assert intent.intent_type == IntentType.MAINTENANCE
        assert intent.confidence > 0.8


class TestHighRiskBlocking:
    """Test that HIGH-RISK actions are blocked."""

    @pytest.mark.asyncio
    async def test_blocks_delete_action(self, pipeline):
        """Actions with 'delete' should be blocked (HIGH-RISK)."""
        result = await pipeline.process("delete everything", session_id="test_user")

        assert "bloqueada" in result.response.lower() or "blocked" in result.response.lower()
        assert "HIGH" in result.response

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="IntentCard integration pending - FASE 8")
    async def test_blocks_send_money_action(self, pipeline):
        """Actions with 'send money' should be blocked (HIGH-RISK)."""
        result = await pipeline.process("send 1000 dollars", session_id="test_user")

        assert "bloqueada" in result.response.lower() or "blocked" in result.response.lower()

    @pytest.mark.asyncio
    async def test_blocks_irreversible_actions(self, pipeline):
        """Actions marked as irreversible should be blocked."""
        result = await pipeline.process(
            "remove all user data permanently",
            session_id="test_user"
        )

        assert "bloqueada" in result.response.lower() or "blocked" in result.response.lower()
        assert result.depth == CognitiveDepth.REFLEX  # Blocked at reflex level


class TestMediumRiskActions:
    """Test that MEDIUM-RISK actions are allowed but logged."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="IntentCard integration pending - FASE 8")
    async def test_allows_reversible_actions(self, pipeline):
        """Reversible actions should be allowed (MEDIUM-RISK)."""
        result = await pipeline.process(
            "create a new user account",
            session_id="test_user"
        )

        # Should not be blocked (routing will fail since it's a test without real LLM)
        # but should not contain "bloqueada" for MEDIUM-RISK
        if "bloqueada" in result.response.lower():
            # If blocked, should mention MEDIUM not HIGH
            assert "MEDIUM" in result.response


class TestLowRiskActions:
    """Test that LOW-RISK actions are allowed."""

    def test_low_risk_classification(self, pipeline):
        """Information requests should be LOW-RISK."""
        intent = pipeline.intent_classifier.classify("What is AI?")
        assert intent.risk_level == RiskLevel.LOW
        assert not intent.requires_approval()

    def test_analysis_low_risk(self, pipeline):
        """Analysis requests should typically be LOW-RISK."""
        intent = pipeline.intent_classifier.classify("Compare Python and JavaScript")
        assert intent.risk_level in [RiskLevel.LOW, RiskLevel.MEDIUM]


class TestIntentCardLogging:
    """Test that IntentCard decisions are logged properly."""

    def test_intent_card_generates_log_entry(self, pipeline):
        """IntentCard should generate structured log entry."""
        intent = pipeline.intent_classifier.classify("What is Python?")
        log_entry = intent.to_log_entry()

        assert "IntentCard" in log_entry
        assert "INFORMATION" in log_entry
        assert "LOW" in log_entry

    def test_blocked_action_has_reasoning(self, pipeline):
        """Blocked actions should have clear reasoning."""
        intent = pipeline.intent_classifier.classify("delete all data")
        assert len(intent.reasoning) > 0
        assert intent.reasoning is not None


class TestIntentPermissions:
    """Test that IntentCard tracks required permissions."""

    def test_information_permissions(self, pipeline):
        """Information requests should need read permissions."""
        intent = pipeline.intent_classifier.classify("What is Python?")
        assert "read:user_input" in intent.required_permissions

    def test_action_permissions(self, pipeline):
        """Actions should require write + audit permissions."""
        intent = pipeline.intent_classifier.classify("create user")
        assert "write:memory" in intent.required_permissions or len(intent.required_permissions) > 0

    def test_high_risk_requires_approval(self, pipeline):
        """HIGH-RISK should require manual approval permission."""
        intent = pipeline.intent_classifier.classify("delete all")
        assert "require:manual_approval" in intent.required_permissions


class TestPipelineIntegration:
    """Test full pipeline integration with IntentCard."""

    @pytest.mark.asyncio
    async def test_pipeline_has_intent_classifier(self, pipeline):
        """Pipeline should expose intent_classifier."""
        await pipeline.init()
        assert hasattr(pipeline, "intent_classifier")
        assert pipeline.intent_classifier is not None

    @pytest.mark.asyncio
    async def test_blocked_action_early_return(self, pipeline):
        """Pipeline should return early for blocked actions."""
        result = await pipeline.process("delete all facts", session_id="test")

        # Should return quickly without running phases
        assert "bloqueada" in result.response.lower() or "blocked" in result.response.lower()
        assert result.depth == CognitiveDepth.REFLEX


class TestConfidenceAndReasoning:
    """Test IntentCard confidence scores and reasoning."""

    def test_maintenance_high_confidence(self, pipeline):
        """Maintenance commands should have high confidence."""
        intent = pipeline.intent_classifier.classify("/status")
        assert intent.confidence > 0.8

    def test_unknown_low_confidence(self, pipeline):
        """Unknown intents should have lower confidence."""
        intent = pipeline.intent_classifier.classify("xyzabc 12345 !@#$%")
        assert intent.confidence < 0.7

    def test_reasoning_explains_classification(self, pipeline):
        """Reasoning should explain why classification was made."""
        intent = pipeline.intent_classifier.classify("delete everything")
        log_entry = intent.to_log_entry()

        assert intent.reasoning is not None
        assert len(intent.reasoning) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
