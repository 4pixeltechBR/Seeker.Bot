"""
Evidence Layer — Rastreabilidade de Decisões do Seeker

Cada decisão importante (routing VLM, aprovação de ação, qualificação de lead)
é registrada com:
- inputs que alimentaram a decisão
- output/resultado
- reasoning explicito
- lineage (qual decisão anterior causou esta?)
- custo e latência
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
import uuid

@dataclass
class EvidenceEntry:
    """Registro de uma decisão importante no Seeker"""

    # O que foi decidido (OBRIGATÓRIOS - SEM DEFAULTS)
    feature: str                    # "vision_routing" | "executor_action" | "scout_qualification"
    decision: str                   # Descrição da decisão ("routed_to_glm_ocr", "approved_L1_LOGGED", "fit_score_78")

    # Entrada/Saída (OBRIGATÓRIOS)
    inputs: Dict[str, Any]          # O que alimentou a decisão
    output: Dict[str, Any]          # O resultado da decisão

    # Confiança e Modelo (OBRIGATÓRIOS)
    confidence: float               # 0.0-1.0 (quão certo estamos?)
    model_used: str                 # Qual modelo/classifier/LLM usou?

    # Identificação (COM DEFAULTS)
    evidence_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Métricas
    cost_usd: float = 0.0
    latency_ms: int = 0
    tokens_used: int = 0

    # Rastreabilidade
    parent_evidence_id: Optional[str] = None  # Qual decisão anterior causou esta?
    reasoning: str = ""             # Por quê essa decisão?

    # Execução/Resultado
    executed: bool = False          # Foi executada?
    execution_status: str = "pending"  # "pending" | "success" | "failed" | "rolled_back"
    execution_error: Optional[str] = None

    # Metadata
    user_id: str = "system"
    session_id: Optional[str] = None
    feature_version: str = "v1"     # Controle de versão da feature que gerou evidence

    def __repr__(self) -> str:
        return (
            f"Evidence({self.feature}:{self.decision} "
            f"| conf={self.confidence:.2f} "
            f"| cost=${self.cost_usd:.4f} "
            f"| {self.latency_ms}ms)"
        )

@dataclass
class ProvenanceNode:
    """Nó no grafo de provenance"""
    evidence_id: str
    feature: str
    decision: str
    parents: List[str] = field(default_factory=list)  # evidence_ids que causaram este

    def __repr__(self) -> str:
        return f"{self.feature}:{self.decision}"

@dataclass
class DecisionTrace:
    """Traço completo de uma decisão e seus ancestrais"""
    root_evidence: EvidenceEntry
    ancestors: List[EvidenceEntry] = field(default_factory=list)  # Decisões que causaram a raiz

    def chain(self) -> str:
        """Retorna trace em formato legível"""
        lines = []
        for i, evidence in enumerate([self.root_evidence] + self.ancestors):
            indent = "→ " * i
            lines.append(
                f"{indent}{evidence.feature}:{evidence.decision}\n"
                f"{indent}   Reasoning: {evidence.reasoning}\n"
                f"{indent}   Confidence: {evidence.confidence:.2f} | Cost: ${evidence.cost_usd:.4f}"
            )
        return "\n".join(lines)
