"""
Seeker.Bot — Intent Card System
src/core/intent_card.py

Classifica intenções do usuário e determina autonomy tier para a resposta.
Estrutura decisões para auditoria e compliance.

Intenção = O que o usuário quer fazer
Autonomy Tier = Quanto de liberdade o Bot tem para executar
"""

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

log = logging.getLogger("seeker.intent_card")


class IntentType(Enum):
    """Tipos de intenção detectados."""

    INFORMATION = auto()  # "O que é X?", "Como...?"
    ANALYSIS = auto()  # "Analise isso", "Compare A e B"
    ACTION = auto()  # "Faça X", "Execute Y"
    LEARNING = auto()  # "Aprenda sobre X", "Estude Y"
    CORRECTION = auto()  # "Corrija isso", "Não, é assim"
    MAINTENANCE = auto()  # "/status", "/memory", admin commands
    UNKNOWN = auto()  # Não conseguiu classificar


class RiskLevel(Enum):
    """Nível de risco da intenção."""

    LOW = 1  # Leitura, análise, información
    MEDIUM = 2  # Ações reversíveis, modificações menores
    HIGH = 3  # Ações irreversíveis, deletar, send money, etc


class AutonomyTier(Enum):
    """
    Nível de autonomia permitido para executar a intenção.

    Tier 1 (Manual): Requer aprovação explícita do usuário
    Tier 2 (Reversível): Bot pode executar, mas deve ter logs/undo
    Tier 3 (Autônomo): Bot executa sem aprovação (máximo cuidado)
    """

    MANUAL = 1  # Tier 1: Desktop Takeover, deletar dados, send money
    REVERSIBLE = 2  # Tier 2: Modificar settings, create resources
    AUTONOMOUS = 3  # Tier 3: Leitura, análise, notificações


@dataclass
class IntentCard:
    """
    Cartão de intenção: estrutura que acompanha toda decisão do Bot.
    Usado para auditoria, compliance e histórico de decisões.
    """

    user_input: str
    intent_type: IntentType
    risk_level: RiskLevel
    autonomy_tier: AutonomyTier
    confidence: float  # 0-1, quão confiante estamos na classificação
    reasoning: str  # Por que classificamos assim
    required_permissions: list[str]  # Ex: ["read:facts", "write:memory"]
    timestamp: float
    user_id: Optional[str] = None

    def to_log_entry(self) -> str:
        """Formata para logging estruturado."""
        return (
            f"[IntentCard] type={self.intent_type.name} "
            f"risk={self.risk_level.name} tier={self.autonomy_tier.name} "
            f"conf={self.confidence:.0%} | {self.reasoning}"
        )

    def requires_approval(self) -> bool:
        """Verdadeiro se precisa de aprovação explícita."""
        return self.autonomy_tier == AutonomyTier.MANUAL

    def is_safe_for_autonomous(self) -> bool:
        """Verdadeiro se é seguro executar autonomamente."""
        return (
            self.autonomy_tier == AutonomyTier.AUTONOMOUS
            and self.risk_level == RiskLevel.LOW
        )


class IntentClassifier:
    """
    Classifica intenções de input do usuário.
    Usa heurísticas simples + patterns para determinar tipo e risco.
    """

    def __init__(self):
        """Inicializa o classificador."""
        self.classifier_version = "1.0"

    def classify(self, user_input: str, user_id: Optional[str] = None) -> IntentCard:
        """
        Classifica a intenção do input.

        Args:
            user_input: Input do usuário
            user_id: ID do usuário (para auditoria)

        Returns:
            IntentCard com classificação completa
        """
        import time

        text_lower = user_input.lower()

        # Detecta tipo de intenção
        intent_type = self._detect_intent_type(text_lower)
        risk_level = self._assess_risk(text_lower, intent_type)
        autonomy_tier = self._determine_autonomy(risk_level, intent_type)
        confidence = self._calculate_confidence(intent_type, text_lower)
        reasoning = self._generate_reasoning(intent_type, risk_level)
        permissions = self._list_required_permissions(intent_type, risk_level)

        return IntentCard(
            user_input=user_input,
            intent_type=intent_type,
            risk_level=risk_level,
            autonomy_tier=autonomy_tier,
            confidence=confidence,
            reasoning=reasoning,
            required_permissions=permissions,
            timestamp=time.time(),
            user_id=user_id,
        )

    def _detect_intent_type(self, text_lower: str) -> IntentType:
        """Detecta tipo de intenção."""
        # Maintenance commands
        if any(cmd in text_lower for cmd in ["/start", "/status", "/memory", "/saude"]):
            return IntentType.MAINTENANCE

        # Correction/Learning
        if any(word in text_lower for word in ["corrija", "wrong", "não", "assim"]):
            return IntentType.CORRECTION

        if any(word in text_lower for word in ["aprenda", "estude", "learn", "study"]):
            return IntentType.LEARNING

        # Action verbs
        if any(verb in text_lower for verb in ["faça", "execute", "delete", "deleta"]):
            return IntentType.ACTION

        # Analysis verbs
        if any(verb in text_lower for verb in ["analise", "compare", "análise", "versus"]):
            return IntentType.ANALYSIS

        # Questions → Information
        if "?" in text_lower or any(
            word in text_lower for word in ["o que", "como", "qual", "what", "how"]
        ):
            return IntentType.INFORMATION

        return IntentType.UNKNOWN

    def _assess_risk(self, text_lower: str, intent_type: IntentType) -> RiskLevel:
        """Avalia risco da intenção."""
        # Alto risco: ações irreversíveis
        if any(
            word in text_lower
            for word in ["delete", "deleta", "remove", "send money", "irreversível"]
        ):
            return RiskLevel.HIGH

        if intent_type == IntentType.ACTION:
            return RiskLevel.MEDIUM

        if intent_type in [IntentType.INFORMATION, IntentType.ANALYSIS, IntentType.LEARNING]:
            return RiskLevel.LOW

        return RiskLevel.MEDIUM

    def _determine_autonomy(
        self, risk_level: RiskLevel, intent_type: IntentType
    ) -> AutonomyTier:
        """Determina tier de autonomia baseado no risco."""
        if risk_level == RiskLevel.HIGH:
            return AutonomyTier.MANUAL

        if risk_level == RiskLevel.MEDIUM:
            return AutonomyTier.REVERSIBLE

        return AutonomyTier.AUTONOMOUS

    def _calculate_confidence(self, intent_type: IntentType, text_lower: str) -> float:
        """Calcula confiança da classificação."""
        # Maintenance commands têm alta confiança
        if intent_type == IntentType.MAINTENANCE:
            return 0.95

        # Claros action verbs
        if intent_type in [IntentType.ACTION, IntentType.ANALYSIS]:
            return 0.8

        # Information (questions) são geralmente claros
        if intent_type == IntentType.INFORMATION and "?" in text_lower:
            return 0.85

        # Unknown ou ambíguo
        if intent_type == IntentType.UNKNOWN:
            return 0.5

        return 0.7

    def _generate_reasoning(self, intent_type: IntentType, risk_level: RiskLevel) -> str:
        """Gera explicação textual da classificação."""
        base = f"Intent: {intent_type.name}, Risk: {risk_level.name}"

        if intent_type == IntentType.MAINTENANCE:
            return f"{base} — Sistema/administração"

        if risk_level == RiskLevel.HIGH:
            return f"{base} — Requer aprovação manual (ação irreversível)"

        if risk_level == RiskLevel.MEDIUM:
            return f"{base} — Ação reversível, pode ser auditada"

        return f"{base} — Seguro para execução autônoma"

    def _list_required_permissions(
        self, intent_type: IntentType, risk_level: RiskLevel
    ) -> list[str]:
        """Lista permissões necessárias."""
        perms = ["read:user_input"]

        if intent_type in [IntentType.ACTION, IntentType.LEARNING]:
            perms.append("write:memory")

        if intent_type == IntentType.ACTION or risk_level == RiskLevel.HIGH:
            perms.append("audit:log")

        if risk_level == RiskLevel.HIGH:
            perms.append("require:manual_approval")

        return perms
