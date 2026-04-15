"""
RemoteExecutorMiner — Detector de Intenção ACTION para Execução Remota

Responsabilidades:
1. Detectar intenções de ação (bash, file ops, desktop control, delegações)
2. Classificar nível de autonomia (L0_MANUAL, L1_LOGGED, L2_SILENT)
3. Validar context e executabilidade
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional
from enum import Enum

log = logging.getLogger("seeker.remote_executor")


class ActionCategory(Enum):
    """Categorias de ações detectadas"""
    BASH = "bash"
    FILE_OPS = "file_ops"
    DESKTOP = "desktop"
    DELEGATION = "delegation"
    UNKNOWN = "unknown"


class AutonomyTier(Enum):
    """Classificação de autonomia para execução"""
    L2_SILENT = "L2_SILENT"      # Auto-execute, sem notificação
    L1_LOGGED = "L1_LOGGED"      # Auto-execute + audit log
    L0_MANUAL = "L0_MANUAL"      # Requer aprovação explícita


@dataclass
class ActionDetectionResult:
    """Resultado da detecção de intenção"""
    detected: bool                 # True se intenção foi detectada
    category: ActionCategory       # Tipo de ação
    autonomy_tier: AutonomyTier   # Nível de autonomia
    intent_text: str              # Intenção original do usuário
    commands: list[str]           # Comandos detectados (se bash)
    confidence: float             # 0.0-1.0 (confiança na detecção)
    reasoning: str                # Explicação breve


class RemoteExecutorMiner:
    """
    Detector de intenções ACTION para execução remota.

    Usa padrões de regex + heurísticas para identificar:
    - Bash commands: "execute ls", "run git commit", "execute npm test"
    - File operations: "create file X", "delete folder Y", "move Z to W"
    - Desktop actions: "click button", "take screenshot", "type message"
    - Delegations: "use Claude Code", "delegate to remote", "execute on desktop"
    """

    # Regex patterns para detecção
    BASH_KEYWORDS = [
        r"(execute|run|exec)\s+(bash|shell|cmd|command)",
        r"execute\s+(.+)",                    # catch-all para "execute XYZ"
        r"(git|npm|pip|python|node)\s+\w+",  # language commands
        r"(mkdir|touch|cp|mv|rm|ls|grep|cat|head|tail)",
    ]

    FILE_OPS_KEYWORDS = [
        r"(create|write|save|delete|remove|move|copy|rename)\s+(file|folder|directory)",
        r"(read|open|download)\s+(file|document)",
    ]

    DESKTOP_KEYWORDS = [
        r"(click|hover|drag|scroll|type|press|key)",
        r"(take|capture)\s+(screenshot|screen|window)",
        r"(switch|activate|close|minimize|maximize)\s+(window|app|application)",
    ]

    DELEGATION_KEYWORDS = [
        r"(use|call|delegate|trigger)\s+(Claude Code|remote|desktop)",
        r"(execute|run)\s+(on desktop|remotely|via Claude)",
    ]

    # Comandos perigosos que requerem L0_MANUAL
    DANGEROUS_BASH_COMMANDS = [
        "rm", "rmdir", "dd", "chmod", "chown", "sudo", "passwd",
        "mkfs", "fdisk", "delpart", "format",
    ]

    # Comandos seguros que permitem L2_SILENT
    SAFE_BASH_COMMANDS = [
        "ls", "cat", "grep", "find", "head", "tail", "wc", "echo",
        "git status", "git log",
    ]

    def __init__(self):
        """Inicializa miner com padrões compilados."""
        self.bash_patterns = [re.compile(p, re.IGNORECASE) for p in self.BASH_KEYWORDS]
        self.file_patterns = [re.compile(p, re.IGNORECASE) for p in self.FILE_OPS_KEYWORDS]
        self.desktop_patterns = [re.compile(p, re.IGNORECASE) for p in self.DESKTOP_KEYWORDS]
        self.delegation_patterns = [re.compile(p, re.IGNORECASE) for p in self.DELEGATION_KEYWORDS]

    def detect(self, intent: str) -> ActionDetectionResult:
        """
        Detecta tipo de ação e classifica autonomia.

        Args:
            intent: Intenção do usuário (text)

        Returns:
            ActionDetectionResult com detecção e classificação
        """
        intent = intent.strip()
        if not intent:
            return ActionDetectionResult(
                detected=False,
                category=ActionCategory.UNKNOWN,
                autonomy_tier=AutonomyTier.L0_MANUAL,
                intent_text=intent,
                commands=[],
                confidence=0.0,
                reasoning="Empty intent",
            )

        # Tenta detectar cada categoria
        # Ordem de preferência: delegation > bash > file_ops > desktop

        if self._matches_patterns(intent, self.delegation_patterns):
            return self._build_result(
                category=ActionCategory.DELEGATION,
                intent=intent,
                reasoning="Delegação detectada",
                commands=self._extract_delegation_target(intent),
            )

        if self._matches_patterns(intent, self.bash_patterns):
            commands = self._extract_bash_commands(intent)
            tier = self._classify_bash_tier(commands)
            return self._build_result(
                category=ActionCategory.BASH,
                intent=intent,
                autonomy_tier=tier,
                reasoning=f"Comando bash detectado (tier: {tier.value})",
                commands=commands,
            )

        if self._matches_patterns(intent, self.file_patterns):
            return self._build_result(
                category=ActionCategory.FILE_OPS,
                intent=intent,
                autonomy_tier=AutonomyTier.L1_LOGGED,
                reasoning="Operação de arquivo detectada",
                commands=self._extract_file_operations(intent),
            )

        if self._matches_patterns(intent, self.desktop_patterns):
            return self._build_result(
                category=ActionCategory.DESKTOP,
                intent=intent,
                autonomy_tier=AutonomyTier.L0_MANUAL,  # Desktop sempre requer aprovação
                reasoning="Ação de desktop detectada",
                commands=self._extract_desktop_actions(intent),
            )

        # Nenhuma categoria detectada
        return ActionDetectionResult(
            detected=False,
            category=ActionCategory.UNKNOWN,
            autonomy_tier=AutonomyTier.L0_MANUAL,
            intent_text=intent,
            commands=[],
            confidence=0.0,
            reasoning="Nenhuma intenção de ação detectada",
        )

    def _matches_patterns(self, intent: str, patterns: list) -> bool:
        """Verifica se intent bate em algum padrão."""
        return any(p.search(intent) for p in patterns)

    def _build_result(
        self,
        category: ActionCategory,
        intent: str,
        autonomy_tier: AutonomyTier = AutonomyTier.L1_LOGGED,
        reasoning: str = "",
        commands: list = None,
        confidence: float = 0.85,
    ) -> ActionDetectionResult:
        """Constrói resultado estruturado."""
        return ActionDetectionResult(
            detected=True,
            category=category,
            autonomy_tier=autonomy_tier,
            intent_text=intent,
            commands=commands or [],
            confidence=confidence,
            reasoning=reasoning,
        )

    def _extract_bash_commands(self, intent: str) -> list[str]:
        """Extrai comando bash da intenção (heurística simples)."""
        # Procura padrão "execute XYZ" ou similar
        match = re.search(r"execute\s+(.+?)(?:\s+to\s+|$)", intent, re.IGNORECASE)
        if match:
            return [match.group(1).strip()]

        # Procura comandos conhecidos
        found = []
        for cmd in self.SAFE_BASH_COMMANDS + self.DANGEROUS_BASH_COMMANDS:
            if cmd.lower() in intent.lower():
                found.append(cmd)

        return found if found else ["unknown_command"]

    def _extract_file_operations(self, intent: str) -> list[str]:
        """Extrai operações de arquivo detectadas."""
        ops = []
        for op in ["create", "delete", "move", "copy", "read", "write"]:
            if op.lower() in intent.lower():
                ops.append(op)
        return ops

    def _extract_desktop_actions(self, intent: str) -> list[str]:
        """Extrai ações de desktop detectadas."""
        actions = []
        for action in ["click", "type", "screenshot", "hover", "scroll"]:
            if action.lower() in intent.lower():
                actions.append(action)
        return actions

    def _extract_delegation_target(self, intent: str) -> list[str]:
        """Extrai alvo de delegação."""
        if "claude code" in intent.lower():
            return ["claude_code"]
        if "remote" in intent.lower():
            return ["remote_trigger"]
        if "desktop" in intent.lower():
            return ["desktop_controller"]
        return ["delegation"]

    def _classify_bash_tier(self, commands: list[str]) -> AutonomyTier:
        """Classifica tier de segurança para comandos bash."""
        if not commands:
            return AutonomyTier.L1_LOGGED

        cmd_lower = " ".join(commands).lower()

        # Verificar comandos perigosos
        for dangerous in self.DANGEROUS_BASH_COMMANDS:
            if dangerous in cmd_lower:
                return AutonomyTier.L0_MANUAL

        # Verificar comandos seguros
        for safe in self.SAFE_BASH_COMMANDS:
            if safe in cmd_lower:
                return AutonomyTier.L2_SILENT

        # Default para meio do caminho
        return AutonomyTier.L1_LOGGED


def create_miner() -> RemoteExecutorMiner:
    """Factory para criação de miner."""
    return RemoteExecutorMiner()
