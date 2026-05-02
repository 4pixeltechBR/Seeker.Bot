"""
Seeker.Bot — Bug Analyzer
src/skills/bug_analyzer/analyzer.py

Análise de bugs com cascade LLM e sugestões de correção.
"""

import logging
import json
import re
import time
from .models import BugReport, BugAnalysis, AnalysisPhase, AnalysisFinding, FixSuggestion
from .context_collector import ContextCollector

log = logging.getLogger("seeker.bug_analyzer")


class BugAnalyzer:
    """Analisa bugs com LLM e retorna sugestões de correção"""

    def __init__(self, cascade_adapter, model_router):
        """
        Inicializa o analisador.

        Args:
            cascade_adapter: Adapter para chamar LLMs com cascade
            model_router: Router para seleção de modelos
        """
        self.cascade_adapter = cascade_adapter
        self.model_router = model_router
        self.context_collector = ContextCollector()

    async def analyze_bug(
        self,
        bug_description: str,
        chat_history: list[dict],
        user_id: str = "unknown",
    ) -> BugAnalysis:
        """
        Analisa um bug completo.

        Fluxo:
        1. Coleta contexto (chat + terminal)
        2. Envia para análise com modelo Coder
        3. Parseia resposta do modelo
        4. Extrai sugestões de correção

        Args:
            bug_description: O que o usuário disse que é o bug
            chat_history: Histórico de chat
            user_id: ID do usuário

        Returns:
            BugAnalysis com análise completa
        """
        log.info(f"[bug_analyzer] Iniciando análise de bug: {bug_description[:60]}...")

        start_time = time.time()

        try:
            # 1. Coleta contexto
            bug_report = await self.context_collector.collect_context(
                bug_description, chat_history, user_id
            )

            # 2. Formata para LLM
            context_text = self.context_collector.format_report_for_llm(bug_report)

            # 3. Cria prompt de análise
            analysis_prompt = self._build_analysis_prompt(context_text)

            # 4. Chama modelo com cascade (DEEP role = Nemotron Ultra → QwQ → DeepSeek)
            from config.models import CognitiveRole

            log.info("[bug_analyzer] Chamando modelo Coder via cascade (DEEP role)")

            response = await self.cascade_adapter.call(
                messages=[{"role": "user", "content": analysis_prompt}],
                model_role=CognitiveRole.DEEP,
                temperature=0.3,  # Determinístico para análise de código
                max_tokens=2048,
            )

            analysis_text = response.get("content", "")
            model_used = response.get("model_id", "unknown")

            log.info(f"[bug_analyzer] Resposta do modelo: {len(analysis_text)} chars")

            # 5. Parseia resposta
            analysis = self._parse_analysis_response(
                bug_report, analysis_text, model_used
            )

            # 6. Calcula latência
            elapsed_ms = (time.time() - start_time) * 1000
            analysis.analysis_latency_ms = elapsed_ms
            analysis.phase = AnalysisPhase.COMPLETE

            log.info(
                f"[bug_analyzer] Análise completa: "
                f"{len(analysis.findings)} achados, "
                f"{len(analysis.suggestions)} sugestões"
            )

            return analysis

        except Exception as e:
            log.error(f"[bug_analyzer] Erro na análise: {e}", exc_info=True)

            # Retorna análise com erro
            return BugAnalysis(
                bug_report=bug_report,
                phase=AnalysisPhase.ANALYZING,
                root_cause=f"Erro na análise: {str(e)[:100]}",
                summary="Análise falhou - tente novamente",
            )

    def _build_analysis_prompt(self, context_text: str) -> str:
        """Constrói prompt para análise de bug"""
        return f"""You are an expert Python/Telegram bot debugger. Analyze the following bug report and provide:

1. **Root Cause**: Identify the core issue
2. **Summary**: Brief explanation of what's happening
3. **Findings**: List 3-5 key findings with severity (critical/high/medium/low)
4. **Fix Suggestions**: For each fixable issue:
   - File path
   - Current problematic code (if identified)
   - Suggested replacement code
   - Risk level (low/medium/high)
   - Brief explanation

Format your response as JSON with this structure:
{{
  "root_cause": "...",
  "summary": "...",
  "findings": [
    {{"category": "...", "severity": "...", "description": "...", "affected_file": "...", "confidence": 0.8}}
  ],
  "suggestions": [
    {{
      "file_path": "...",
      "current_code": "...",
      "suggested_code": "...",
      "explanation": "...",
      "risk_level": "low"
    }}
  ]
}}

Context:
{context_text}

Provide detailed, actionable analysis. Focus on actual bugs, not style improvements.
CRITICAL RULES FOR DIAGNOSIS:
1. If the context does NOT contain actual Error Tracebacks or Stack Traces (e.g., terminal output is empty or lacks Python errors), do NOT invent complex architectural causes like network timeouts, async state sync issues, or worker deaths.
2. If the user reports a visual/formatting issue (e.g., text missing data, weird string literals like \\n, or wrong counters), assume it's a simple string formatting or dictionary parsing bug.
3. If you do not have the exact file path and current code snippet, DO NOT generate a blind FixSuggestion that creates new generic wrapper/retry files (like auto_retry). Provide a diagnosis pointing to formatting/logic and explicitly say: "Code inspection required".
4. Do NOT hallucinate import paths. If a function is missing, DO NOT guess its module path."""

    def _parse_analysis_response(
        self, bug_report: BugReport, response_text: str, model_used: str
    ) -> BugAnalysis:
        """Parseia resposta do modelo em estrutura BugAnalysis"""
        analysis = BugAnalysis(
            bug_report=bug_report,
            phase=AnalysisPhase.COMPLETE,
            model_used=model_used,
        )

        try:
            # Tenta extrair JSON da resposta
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if not json_match:
                log.warning("[bug_analyzer] JSON não encontrado na resposta")
                analysis.summary = response_text[:500]
                return analysis

            json_str = json_match.group(0)
            data = json.loads(json_str)

            # Root cause
            analysis.root_cause = data.get("root_cause", "")

            # Summary
            analysis.summary = data.get("summary", "")

            # Findings
            for finding_data in data.get("findings", []):
                finding = AnalysisFinding(
                    category=finding_data.get("category", "unknown"),
                    severity=finding_data.get("severity", "low"),
                    description=finding_data.get("description", ""),
                    affected_file=finding_data.get("affected_file", ""),
                    confidence=finding_data.get("confidence", 0.5),
                )
                analysis.findings.append(finding)

            # Suggestions
            for sugg_data in data.get("suggestions", []):
                suggestion = FixSuggestion(
                    file_path=sugg_data.get("file_path", ""),
                    current_code=sugg_data.get("current_code", ""),
                    suggested_code=sugg_data.get("suggested_code", ""),
                    explanation=sugg_data.get("explanation", ""),
                    risk_level=sugg_data.get("risk_level", "medium"),
                    requires_approval=True,
                )
                analysis.suggestions.append(suggestion)

            log.info(f"[bug_analyzer] Parsed: {len(analysis.findings)} findings, {len(analysis.suggestions)} suggestions")

        except json.JSONDecodeError as e:
            log.error(f"[bug_analyzer] Erro ao parsear JSON: {e}")
            analysis.summary = response_text[:500]
        except Exception as e:
            log.error(f"[bug_analyzer] Erro ao processar resposta: {e}", exc_info=True)

        return analysis
