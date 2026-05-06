"""
Evidence Layer — Rastreabilidade completa de decisões do Seeker

Exporta:
- EvidenceEntry: dataclass para registrar uma decisão
- EvidenceStore: gerencia persistência e queries
- get_evidence_store(): singleton global
"""

from .models import EvidenceEntry, DecisionTrace, ProvenanceNode
from .storage import EvidenceStore, get_evidence_store

__all__ = [
    "EvidenceEntry",
    "DecisionTrace",
    "ProvenanceNode",
    "EvidenceStore",
    "get_evidence_store",
]
