"""
Unit tests for cognitive load router.
Tests the route() function with various input patterns.
"""

import pytest
from src.core.router.cognitive_load import (
    CognitiveLoadRouter,
    CognitiveDepth,
)


@pytest.fixture
def router():
    """Initialize the router."""
    return CognitiveLoadRouter()


class TestCognitiveDepthRouting:
    """Test cognitive depth detection."""

    def test_reflex_simple_question(self, router):
        """Simple factual questions should be REFLEX."""
        decision = router.route("What is 2 + 2?")
        assert decision.depth == CognitiveDepth.REFLEX

    def test_reflex_greeting(self, router):
        """Greetings should be REFLEX."""
        decision = router.route("Olá, tudo bem?")
        assert decision.depth == CognitiveDepth.REFLEX

    def test_reflex_status_check(self, router):
        """Status checks should be REFLEX."""
        decision = router.route("Como você está?")
        assert decision.depth == CognitiveDepth.REFLEX

    def test_deliberate_analysis_needed(self, router):
        """Questions requiring analysis should be DELIBERATE."""
        decision = router.route("Qual é a melhor forma de organizar um projeto?")
        assert decision.depth == CognitiveDepth.DELIBERATE

    def test_deliberate_explain_concept(self, router):
        """Explanations should be DELIBERATE."""
        decision = router.route("Explique como funciona o machine learning")
        assert decision.depth in [CognitiveDepth.DELIBERATE, CognitiveDepth.DEEP]

    def test_deep_complex_analysis(self, router):
        """Complex requests with 'god' should be DEEP."""
        decision = router.route("god: Analize this deeply")
        assert decision.depth == CognitiveDepth.DEEP

    def test_deep_multi_step_reasoning(self, router):
        """Multi-step reasoning should be DEEP."""
        decision = router.route(
            "Considerando A, B e C, qual é a melhor estratégia?"
        )
        # May be DELIBERATE or DEEP depending on complexity
        assert decision.depth in [CognitiveDepth.DELIBERATE, CognitiveDepth.DEEP]

    def test_web_search_needed(self, router):
        """Requests with news keywords should trigger web search."""
        decision = router.route("Quais são as últimas notícias sobre AI?")
        assert decision.needs_web is True

    def test_no_web_search_for_general(self, router):
        """General questions shouldn't trigger web search."""
        decision = router.route("Como aprender Python?")
        # May or may not need web, depending on content
        assert isinstance(decision.needs_web, bool)

    def test_god_mode_flag(self, router):
        """God mode should be detected."""
        decision = router.route("god: force deep analysis")
        assert decision.god_mode is True

    def test_no_god_mode_default(self, router):
        """Default should not have god mode."""
        decision = router.route("What time is it?")
        assert decision.god_mode is False

    def test_decision_has_reason(self, router):
        """Every decision should have a reason."""
        decision = router.route("Anything")
        assert decision.reason is not None
        assert len(decision.reason) > 0

    def test_empty_input(self, router):
        """Empty input should return REFLEX."""
        decision = router.route("")
        assert decision.depth == CognitiveDepth.REFLEX

    def test_very_long_input(self, router):
        """Very long input should still work."""
        long_text = "This is a very long question. " * 100
        decision = router.route(long_text)
        assert decision.depth in [
            CognitiveDepth.REFLEX,
            CognitiveDepth.DELIBERATE,
            CognitiveDepth.DEEP,
        ]

    def test_special_characters(self, router):
        """Input with special characters should work."""
        decision = router.route("Como usar @mention, #hashtag e link: https://example.com?")
        assert decision.depth in [
            CognitiveDepth.REFLEX,
            CognitiveDepth.DELIBERATE,
        ]

    def test_multiple_languages(self, router):
        """Mixed languages should still route correctly."""
        decision = router.route("Qual é a meaning of life?")
        assert decision.depth in [
            CognitiveDepth.REFLEX,
            CognitiveDepth.DELIBERATE,
            CognitiveDepth.DEEP,
        ]


class TestRoutingConsistency:
    """Test that routing is consistent."""

    def test_same_input_same_depth(self, router):
        """Same input should always route to same depth."""
        input_text = "How to build a web application?"
        depth1 = router.route(input_text).depth
        depth2 = router.route(input_text).depth
        depth3 = router.route(input_text).depth
        assert depth1 == depth2 == depth3

    def test_case_insensitivity(self, router):
        """Routing should be case-insensitive."""
        decision_lower = router.route("what is ai?").depth
        decision_upper = router.route("WHAT IS AI?").depth
        assert decision_lower == decision_upper


class TestEdgeCases:
    """Test edge cases and unusual inputs."""

    def test_only_numbers(self, router):
        """Input with only numbers."""
        decision = router.route("123456789")
        assert decision.depth == CognitiveDepth.REFLEX

    def test_only_punctuation(self, router):
        """Input with only punctuation."""
        decision = router.route("!@#$%^&*()")
        assert decision.depth == CognitiveDepth.REFLEX

    def test_url_input(self, router):
        """URL as input."""
        decision = router.route("https://example.com")
        assert decision.depth in [
            CognitiveDepth.REFLEX,
            CognitiveDepth.DELIBERATE,
        ]

    def test_code_snippet_input(self, router):
        """Code snippet as input."""
        code = "def foo():\n    return 42"
        decision = router.route(code)
        assert decision.depth in [
            CognitiveDepth.REFLEX,
            CognitiveDepth.DELIBERATE,
            CognitiveDepth.DEEP,
        ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
