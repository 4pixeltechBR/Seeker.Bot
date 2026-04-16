"""
Seeker.Bot — Bug Analyzer Skill
src/skills/bug_analyzer/__init__.py

Análise automática de bugs com coleta de contexto, LLM analysis e sugestões de correção.
"""

from .models import (
    BugReport,
    BugAnalysis,
    AnalysisPhase,
    ChatMessage,
    TerminalLine,
    AnalysisFinding,
    FixSuggestion,
)
from .context_collector import ContextCollector
from .analyzer import BugAnalyzer
from .telegram_interface import BugAnalyzerTelegramInterface

__all__ = [
    "BugReport",
    "BugAnalysis",
    "AnalysisPhase",
    "ChatMessage",
    "TerminalLine",
    "AnalysisFinding",
    "FixSuggestion",
    "ContextCollector",
    "BugAnalyzer",
    "BugAnalyzerTelegramInterface",
]
