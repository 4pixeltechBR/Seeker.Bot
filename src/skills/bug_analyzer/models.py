"""
Seeker.Bot — Bug Analyzer Models
src/skills/bug_analyzer/models.py

Estruturas de dados para contexto de bug, relatório, e análise.
"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class AnalysisPhase(str, Enum):
    """Fases da análise de bug"""
    CONTEXT_COLLECTION = "context_collection"  # Coletando contexto
    ANALYZING = "analyzing"                    # Analisando com LLM
    COMPLETE = "complete"                       # Análise completa
    APPROVED = "approved"                       # Correção aprovada
    APPLIED = "applied"                         # Correção aplicada


@dataclass
class ChatMessage:
    """Representa uma mensagem no chat"""
    timestamp: str
    user_id: str
    text: str
    is_user: bool = True


@dataclass
class TerminalLine:
    """Representa uma linha do terminal/log"""
    timestamp: str
    line: str
    is_error: bool = False
    is_warning: bool = False


@dataclass
class BugReport:
    """Contexto completo do bug relatado pelo usuário"""
    bug_description: str                    # O que o usuário disse que é o bug
    chat_history: list[ChatMessage]         # Últimas 5 mensagens do chat
    terminal_output: list[TerminalLine]     # Últimas 25 linhas do terminal
    affected_files: list[str] = field(default_factory=list)
    error_patterns: list[str] = field(default_factory=list)
    collected_at: datetime = field(default_factory=datetime.now)
    user_id: str = ""


@dataclass
class AnalysisFinding:
    """Achado da análise"""
    category: str           # "root_cause", "symptom", "config_issue", etc
    severity: str          # "critical", "high", "medium", "low"
    description: str
    affected_file: str = ""
    line_range: str = ""
    confidence: float = 0.7  # 0-1


@dataclass
class FixSuggestion:
    """Sugestão de correção"""
    file_path: str
    current_code: str       # Trecho atual
    suggested_code: str     # Código sugerido
    explanation: str
    risk_level: str         # "low", "medium", "high"
    requires_approval: bool = True


@dataclass
class BugAnalysis:
    """Resultado completo da análise de bug"""
    bug_report: BugReport
    phase: AnalysisPhase
    findings: list[AnalysisFinding] = field(default_factory=list)
    root_cause: str = ""
    summary: str = ""
    suggestions: list[FixSuggestion] = field(default_factory=list)
    analysis_cost_usd: float = 0.0
    analysis_latency_ms: float = 0.0
    analyzed_at: datetime = field(default_factory=datetime.now)
    model_used: str = ""

    def has_actionable_fixes(self) -> bool:
        """Retorna se há correções viáveis"""
        return len(self.suggestions) > 0

    def get_summary_text(self) -> str:
        """Gera sumário formatado para exibição"""
        lines = [
            f"<b>🔍 Análise de Bug Completa</b>\n",
            f"<b>Modelo:</b> {self.model_used}\n",
            f"<b>Fase:</b> {self.phase.value}\n\n",
        ]

        if self.root_cause:
            lines.append(f"<b>🎯 Causa Raiz:</b>\n{self.root_cause}\n\n")

        if self.summary:
            lines.append(f"<b>📋 Sumário:</b>\n{self.summary}\n\n")

        if self.findings:
            lines.append(f"<b>🔎 Achados ({len(self.findings)}):</b>\n")
            for finding in self.findings[:5]:  # Top 5
                severity_emoji = {
                    "critical": "🔴",
                    "high": "🟠",
                    "medium": "🟡",
                    "low": "🟢",
                }.get(finding.severity, "⚪")
                lines.append(
                    f"{severity_emoji} {finding.category}: {finding.description[:80]}"
                )
            lines.append("")

        if self.suggestions:
            lines.append(f"<b>💡 Sugestões de Correção ({len(self.suggestions)}):</b>\n")
            for i, sugg in enumerate(self.suggestions, 1):
                lines.append(f"{i}. <code>{sugg.file_path}</code>")
                lines.append(f"   Risco: {sugg.risk_level}")
            lines.append("")

        lines.append(f"<b>💰 Custo:</b> ${self.analysis_cost_usd:.4f} | <b>⏱️</b> {self.analysis_latency_ms:.0f}ms")

        return "\n".join(lines)
