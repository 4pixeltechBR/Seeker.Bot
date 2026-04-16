"""
Seeker.Bot — Bug Context Collector
src/skills/bug_analyzer/context_collector.py

Coleta contexto de chat e terminal para análise de bugs.
"""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from .models import BugReport, ChatMessage, TerminalLine

log = logging.getLogger("seeker.bug_analyzer")


class ContextCollector:
    """Coleta contexto para análise de bugs"""

    def __init__(self, log_file_path: str = "logs/seeker.log"):
        self.log_file_path = Path(log_file_path)

    async def collect_context(
        self,
        bug_description: str,
        chat_history: list[dict],  # [{"timestamp": "...", "text": "...", "is_user": True/False}]
        user_id: str = "unknown"
    ) -> BugReport:
        """
        Coleta contexto completo do bug.

        Args:
            bug_description: Descrição do bug fornecida pelo usuário
            chat_history: Histórico de chat (últimas 5 mensagens)
            user_id: ID do usuário que reportou

        Returns:
            BugReport com contexto coletado
        """
        log.info(f"[context_collector] Coletando contexto para bug: {bug_description[:60]}...")

        # 1. Processa histórico de chat
        chat_messages = self._process_chat_history(chat_history)

        # 2. Coleta últimas linhas do terminal/log
        terminal_output = await self._collect_terminal_output()

        # 3. Detecta padrões de erro
        error_patterns = self._detect_error_patterns(terminal_output)

        # 4. Identifica arquivos possivelmente afetados
        affected_files = self._identify_affected_files(terminal_output, error_patterns)

        report = BugReport(
            bug_description=bug_description,
            chat_history=chat_messages,
            terminal_output=terminal_output,
            affected_files=affected_files,
            error_patterns=error_patterns,
            user_id=user_id,
        )

        log.info(
            f"[context_collector] Contexto coletado: "
            f"{len(chat_messages)} mensagens, "
            f"{len(terminal_output)} linhas de log, "
            f"{len(error_patterns)} padrões de erro"
        )

        return report

    def _process_chat_history(self, chat_history: list[dict]) -> list[ChatMessage]:
        """Processa histórico de chat em objetos ChatMessage"""
        messages = []

        for msg in chat_history[-5:]:  # Últimas 5
            messages.append(
                ChatMessage(
                    timestamp=msg.get("timestamp", datetime.now().isoformat()),
                    user_id=msg.get("user_id", "unknown"),
                    text=msg.get("text", ""),
                    is_user=msg.get("is_user", True),
                )
            )

        return messages

    async def _collect_terminal_output(self) -> list[TerminalLine]:
        """Coleta últimas 25 linhas do arquivo de log"""
        lines = []

        if not self.log_file_path.exists():
            log.warning(f"[context_collector] Log file não encontrado: {self.log_file_path}")
            return lines

        try:
            with open(self.log_file_path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()

            # Últimas 25 linhas
            for line in all_lines[-25:]:
                line = line.rstrip()
                if not line:
                    continue

                # Extrai timestamp (padrão: [HH:MM:SS])
                timestamp_match = re.match(r"\[?(\d{2}:\d{2}:\d{2})", line)
                timestamp = timestamp_match.group(1) if timestamp_match else datetime.now().isoformat()

                # Detecta se é erro/warning
                is_error = any(
                    kw in line.upper() for kw in ["ERROR", "EXCEPTION", "FAILED", "FATAL"]
                )
                is_warning = any(
                    kw in line.upper() for kw in ["WARNING", "WARN", "DEPRECATED"]
                )

                lines.append(
                    TerminalLine(
                        timestamp=timestamp,
                        line=line,
                        is_error=is_error,
                        is_warning=is_warning,
                    )
                )

            log.debug(f"[context_collector] Coletadas {len(lines)} linhas do log")

        except Exception as e:
            log.error(f"[context_collector] Erro ao ler log: {e}")

        return lines

    def _detect_error_patterns(self, terminal_output: list[TerminalLine]) -> list[str]:
        """Detecta padrões de erro na saída do terminal"""
        patterns = []
        error_lines = [line for line in terminal_output if line.is_error or line.is_warning]

        # Extrai mensagens de erro mais comuns
        for line in error_lines:
            # Busca por "error: ..." ou "ERROR: ..."
            error_match = re.search(r"(?:error|exception|failed)[\s:]*([^;]+)(?:;|$)", line.line, re.IGNORECASE)
            if error_match:
                pattern = error_match.group(1).strip()
                if pattern and pattern not in patterns:
                    patterns.append(pattern[:100])  # Limita tamanho

        return patterns[:5]  # Top 5 padrões

    def _identify_affected_files(
        self, terminal_output: list[TerminalLine], error_patterns: list[str]
    ) -> list[str]:
        """Identifica arquivos possivelmente afetados baseado em rastreamento de stack"""
        files = set()

        # Padrão para caminhos de arquivo em stack traces
        # Ex: "File "src/core/goals/scheduler.py", line 123, in ..."
        file_pattern = r'File\s+"([^"]+\.py)"'

        for line in terminal_output:
            matches = re.findall(file_pattern, line.line)
            files.update(matches)

        # Também procura em error patterns
        for pattern in error_patterns:
            matches = re.findall(file_pattern, pattern)
            files.update(matches)

        return sorted(list(files))[:10]  # Top 10 arquivos

    def format_report_for_llm(self, report: BugReport) -> str:
        """Formata BugReport em texto para análise LLM"""
        lines = [
            "=== CONTEXTO DE BUG ===\n",
            f"Descrição do Usuário: {report.bug_description}\n",
            f"Data/Hora: {report.collected_at.isoformat()}\n",
            f"Usuário ID: {report.user_id}\n",
        ]

        if report.chat_history:
            lines.append("\n=== HISTÓRICO DE CHAT (últimas 5 mensagens) ===\n")
            for msg in report.chat_history:
                sender = "Usuário" if msg.is_user else "Bot"
                lines.append(f"[{msg.timestamp}] {sender}: {msg.text}\n")

        if report.error_patterns:
            lines.append("\n=== PADRÕES DE ERRO DETECTADOS ===\n")
            for i, pattern in enumerate(report.error_patterns, 1):
                lines.append(f"{i}. {pattern}\n")

        if report.affected_files:
            lines.append("\n=== ARQUIVOS POSSIVELMENTE AFETADOS ===\n")
            for file in report.affected_files:
                lines.append(f"- {file}\n")

        if report.terminal_output:
            lines.append("\n=== ÚLTIMAS 25 LINHAS DO LOG ===\n")
            for line in report.terminal_output:
                prefix = "⚠️" if line.is_warning else "🔴" if line.is_error else "  "
                lines.append(f"{prefix} [{line.timestamp}] {line.line}\n")

        return "".join(lines)
