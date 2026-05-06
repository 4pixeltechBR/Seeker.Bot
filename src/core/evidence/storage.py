"""
Evidence Storage — Persistência de Evidence Entries

Usa append-only JSONL para auditoria completa e immutabilidade.
"""

import json
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from .models import EvidenceEntry, DecisionTrace, ProvenanceNode

log = logging.getLogger("seeker.evidence")

class EvidenceStore:
    """Gerencia persistência e query de Evidence entries"""

    def __init__(self, storage_path: str = "data/evidence"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.evidence_log = self.storage_path / "evidence.jsonl"
        self.provenance_index = self.storage_path / "provenance.json"

        # Em-memory cache para queries rápidas
        self._cache: dict[str, EvidenceEntry] = {}
        self._provenance_graph: dict[str, ProvenanceNode] = {}

        self._load_cache()

    def _load_cache(self):
        """Carrega cache em-memory do JSONL"""
        if not self.evidence_log.exists():
            return

        try:
            with open(self.evidence_log, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    entry = self._dict_to_evidence(data)
                    self._cache[entry.evidence_id] = entry

                    # Atualiza provenance graph
                    node = ProvenanceNode(
                        evidence_id=entry.evidence_id,
                        feature=entry.feature,
                        decision=entry.decision,
                        parents=[entry.parent_evidence_id] if entry.parent_evidence_id else []
                    )
                    self._provenance_graph[entry.evidence_id] = node

            log.info(f"[evidence] Loaded {len(self._cache)} entries from cache")
        except Exception as e:
            log.error(f"[evidence] Error loading cache: {e}")

    def store(self, evidence: EvidenceEntry) -> str:
        """Persiste Evidence entry e retorna ID"""
        try:
            # Append ao JSONL
            entry_dict = self._evidence_to_dict(evidence)
            with open(self.evidence_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry_dict) + "\n")

            # Atualiza cache
            self._cache[evidence.evidence_id] = evidence

            # Atualiza provenance graph
            node = ProvenanceNode(
                evidence_id=evidence.evidence_id,
                feature=evidence.feature,
                decision=evidence.decision,
                parents=[evidence.parent_evidence_id] if evidence.parent_evidence_id else []
            )
            self._provenance_graph[evidence.evidence_id] = node

            log.debug(f"[evidence] Stored: {evidence.evidence_id} ({evidence.feature})")
            return evidence.evidence_id

        except Exception as e:
            log.error(f"[evidence] Error storing evidence: {e}")
            raise

    def get(self, evidence_id: str) -> Optional[EvidenceEntry]:
        """Recupera Evidence entry por ID"""
        return self._cache.get(evidence_id)

    def trace(self, evidence_id: str, max_depth: int = 10) -> Optional[DecisionTrace]:
        """
        Reconstrói trace completo de uma decisão e seus ancestrais.

        Args:
            evidence_id: ID da decisão raiz
            max_depth: Quantos níveis acima seguir (prevenção de loops)

        Returns:
            DecisionTrace com raiz e ancestrais
        """
        root = self.get(evidence_id)
        if not root:
            return None

        ancestors = []
        current = root
        depth = 0

        while current.parent_evidence_id and depth < max_depth:
            parent = self.get(current.parent_evidence_id)
            if not parent:
                break
            ancestors.append(parent)
            current = parent
            depth += 1

        return DecisionTrace(root_evidence=root, ancestors=ancestors)

    def list_by_feature(self, feature: str, limit: int = 100) -> List[EvidenceEntry]:
        """Lista Evidence entries por feature"""
        results = [e for e in self._cache.values() if e.feature == feature]
        return sorted(results, key=lambda e: e.timestamp, reverse=True)[:limit]

    def list_by_user(self, user_id: str, limit: int = 100) -> List[EvidenceEntry]:
        """Lista Evidence entries por usuário"""
        results = [e for e in self._cache.values() if e.user_id == user_id]
        return sorted(results, key=lambda e: e.timestamp, reverse=True)[:limit]

    def stats(self) -> dict:
        """Retorna estatísticas do evidence store"""
        entries = list(self._cache.values())
        if not entries:
            return {
                "total_entries": 0,
                "features": {},
                "total_cost_usd": 0.0,
                "avg_latency_ms": 0,
                "avg_confidence": 0.0,
            }

        features = {}
        total_cost = 0.0
        total_latency = 0
        total_confidence = 0.0

        for e in entries:
            if e.feature not in features:
                features[e.feature] = 0
            features[e.feature] += 1
            total_cost += e.cost_usd
            total_latency += e.latency_ms
            total_confidence += e.confidence

        return {
            "total_entries": len(entries),
            "features": features,
            "total_cost_usd": round(total_cost, 4),
            "avg_latency_ms": int(total_latency / len(entries)) if entries else 0,
            "avg_confidence": round(total_confidence / len(entries), 3) if entries else 0.0,
        }

    @staticmethod
    def _evidence_to_dict(evidence: EvidenceEntry) -> dict:
        """Converte EvidenceEntry para dict serializável"""
        return {
            "evidence_id": evidence.evidence_id,
            "timestamp": evidence.timestamp.isoformat(),
            "feature": evidence.feature,
            "decision": evidence.decision,
            "inputs": evidence.inputs,
            "output": evidence.output,
            "confidence": evidence.confidence,
            "model_used": evidence.model_used,
            "cost_usd": evidence.cost_usd,
            "latency_ms": evidence.latency_ms,
            "tokens_used": evidence.tokens_used,
            "parent_evidence_id": evidence.parent_evidence_id,
            "reasoning": evidence.reasoning,
            "executed": evidence.executed,
            "execution_status": evidence.execution_status,
            "execution_error": evidence.execution_error,
            "user_id": evidence.user_id,
            "session_id": evidence.session_id,
            "feature_version": evidence.feature_version,
        }

    @staticmethod
    def _dict_to_evidence(data: dict) -> EvidenceEntry:
        """Converte dict para EvidenceEntry"""
        return EvidenceEntry(
            evidence_id=data.get("evidence_id", ""),
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.utcnow().isoformat())),
            feature=data.get("feature", ""),
            decision=data.get("decision", ""),
            inputs=data.get("inputs", {}),
            output=data.get("output", {}),
            confidence=data.get("confidence", 0.0),
            model_used=data.get("model_used", ""),
            cost_usd=data.get("cost_usd", 0.0),
            latency_ms=data.get("latency_ms", 0),
            tokens_used=data.get("tokens_used", 0),
            parent_evidence_id=data.get("parent_evidence_id"),
            reasoning=data.get("reasoning", ""),
            executed=data.get("executed", False),
            execution_status=data.get("execution_status", "pending"),
            execution_error=data.get("execution_error"),
            user_id=data.get("user_id", "system"),
            session_id=data.get("session_id"),
            feature_version=data.get("feature_version", "v1"),
        )


# Singleton global
_evidence_store: Optional[EvidenceStore] = None

def get_evidence_store() -> EvidenceStore:
    """Retorna instância global do EvidenceStore"""
    global _evidence_store
    if _evidence_store is None:
        _evidence_store = EvidenceStore()
    return _evidence_store
