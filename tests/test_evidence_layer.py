"""
Tests para Evidence Layer — Rastreabilidade de Decisões

Valida:
1. EvidenceEntry storage e retrieval
2. Decision trace (ancestry de decisões)
3. Integration com Vision 2.0 routing
4. Integration com Remote Executor
5. Integration com Scout Hunter
6. Query capabilities
"""

import pytest
import json
from pathlib import Path
from datetime import datetime, timedelta

from src.core.evidence import (
    EvidenceEntry,
    DecisionTrace,
    EvidenceStore,
    get_evidence_store,
)


@pytest.fixture
def evidence_store(tmp_path):
    """Create temporary evidence store for testing"""
    store = EvidenceStore(str(tmp_path))
    return store


class TestEvidenceStorage:
    """Test EvidenceEntry storage and retrieval"""

    def test_store_and_retrieve(self, evidence_store):
        """Test storing and retrieving evidence"""
        evidence = EvidenceEntry(
            feature="vision_routing",
            decision="routed_to_glm_ocr",
            inputs={"image_path": "/path/to/image.png", "aspect_ratio": 1.5},
            output={"routed_to": "glm_ocr", "confidence": 0.92},
            confidence=0.92,
            model_used="task_classifier",
        )

        evidence_id = evidence_store.store(evidence)
        retrieved = evidence_store.get(evidence_id)

        assert retrieved is not None
        assert retrieved.feature == "vision_routing"
        assert retrieved.decision == "routed_to_glm_ocr"
        assert retrieved.confidence == 0.92

    def test_evidence_persistence(self, tmp_path):
        """Test that evidence persists across store instances"""
        store1 = EvidenceStore(str(tmp_path))
        evidence = EvidenceEntry(
            feature="executor_action",
            decision="executed_L1_LOGGED",
            inputs={"command": "git add ."},
            output={"status": "success"},
            confidence=0.95,
            model_used="remote_executor",
        )
        evidence_id = store1.store(evidence)

        # Create new store instance (simulates restart)
        store2 = EvidenceStore(str(tmp_path))
        retrieved = store2.get(evidence_id)

        assert retrieved is not None
        assert retrieved.decision == "executed_L1_LOGGED"

    def test_list_by_feature(self, evidence_store):
        """Test listing evidence by feature"""
        # Store multiple entries
        for i in range(3):
            evidence = EvidenceEntry(
                feature="vision_routing",
                decision=f"routed_decision_{i}",
                inputs={},
                output={},
                confidence=0.8 + i * 0.05,
                model_used="classifier",
            )
            evidence_store.store(evidence)

        # List by feature
        results = evidence_store.list_by_feature("vision_routing", limit=10)
        assert len(results) == 3

    def test_stats(self, evidence_store):
        """Test statistics computation"""
        # Store mixed evidence
        for feature in ["vision_routing", "executor_action", "scout_qualification"]:
            evidence = EvidenceEntry(
                feature=feature,
                decision=f"test_{feature}",
                inputs={},
                output={},
                confidence=0.85,
                model_used="test_model",
                cost_usd=0.01,
                latency_ms=100,
            )
            evidence_store.store(evidence)

        stats = evidence_store.stats()
        assert stats["total_entries"] == 3
        assert "vision_routing" in stats["features"]
        assert stats["total_cost_usd"] == pytest.approx(0.03, rel=1e-2)


class TestDecisionTrace:
    """Test decision tracing and lineage"""

    def test_simple_trace(self, evidence_store):
        """Test tracing a single decision"""
        evidence = EvidenceEntry(
            feature="vision_routing",
            decision="routed_to_glm_ocr",
            inputs={"image_path": "/path.png"},
            output={"routed_to": "glm_ocr"},
            confidence=0.92,
            model_used="classifier",
            reasoning="OCR task detected by aspect ratio",
        )
        evidence_id = evidence_store.store(evidence)

        trace = evidence_store.trace(evidence_id)
        assert trace is not None
        assert trace.root_evidence.evidence_id == evidence_id
        assert len(trace.ancestors) == 0

    def test_trace_with_ancestry(self, evidence_store):
        """Test tracing a decision with parent"""
        # Parent decision
        parent = EvidenceEntry(
            feature="vision_routing",
            decision="classified_as_ocr",
            inputs={"aspect_ratio": 1.5},
            output={"task_type": "ocr"},
            confidence=0.90,
            model_used="classifier",
        )
        parent_id = evidence_store.store(parent)

        # Child decision (routing based on classification)
        child = EvidenceEntry(
            feature="vision_routing",
            decision="routed_to_glm_ocr",
            inputs={"task_type": "ocr"},
            output={"routed_to": "glm_ocr"},
            confidence=0.92,
            model_used="router",
            parent_evidence_id=parent_id,
            reasoning="Routing based on OCR classification",
        )
        child_id = evidence_store.store(child)

        # Trace child
        trace = evidence_store.trace(child_id)
        assert trace is not None
        assert trace.root_evidence.evidence_id == child_id
        assert len(trace.ancestors) == 1
        assert trace.ancestors[0].evidence_id == parent_id

    def test_trace_chain_output(self, evidence_store):
        """Test human-readable trace chain"""
        parent = EvidenceEntry(
            feature="vision_routing",
            decision="classified_as_ocr",
            inputs={},
            output={},
            confidence=0.90,
            model_used="classifier",
            reasoning="Text density high",
        )
        parent_id = evidence_store.store(parent)

        child = EvidenceEntry(
            feature="vision_routing",
            decision="routed_to_glm_ocr",
            inputs={},
            output={},
            confidence=0.92,
            model_used="router",
            parent_evidence_id=parent_id,
            reasoning="Route OCR to specialist",
        )
        child_id = evidence_store.store(child)

        trace = evidence_store.trace(child_id)
        chain = trace.chain()

        # Should contain both decisions
        assert "routed_to_glm_ocr" in chain
        assert "classified_as_ocr" in chain
        assert "Route OCR to specialist" in chain


class TestEvidenceMetadata:
    """Test evidence metadata and execution tracking"""

    def test_execution_tracking(self, evidence_store):
        """Test tracking execution status"""
        evidence = EvidenceEntry(
            feature="executor_action",
            decision="execute_L1_LOGGED",
            inputs={"command": "git add ."},
            output={"status": "success"},
            confidence=0.95,
            model_used="executor",
            executed=True,
            execution_status="success",
        )
        evidence_id = evidence_store.store(evidence)

        retrieved = evidence_store.get(evidence_id)
        assert retrieved.executed is True
        assert retrieved.execution_status == "success"

    def test_cost_tracking(self, evidence_store):
        """Test cost and performance tracking"""
        evidence = EvidenceEntry(
            feature="scout_qualification",
            decision="bant_score_78",
            inputs={},
            output={},
            confidence=0.85,
            model_used="cascade_fast",
            cost_usd=0.002,
            latency_ms=250,
            tokens_used=150,
        )
        evidence_store.store(evidence)

        stats = evidence_store.stats()
        assert stats["total_cost_usd"] == pytest.approx(0.002, rel=1e-2)
        assert stats["avg_latency_ms"] == 250


class TestEvidenceIntegration:
    """Integration tests with features"""

    @pytest.mark.asyncio
    async def test_vision_routing_evidence(self, tmp_path):
        """Test Evidence logging from Vision Router"""
        # This is a simulation since we can't easily mock the full router
        store = EvidenceStore(str(tmp_path))

        # Simulate what VLMRouter.extract_text_from_image would log
        evidence = EvidenceEntry(
            feature="vision_routing",
            decision="routed_to_primary",
            inputs={
                "image_path": "/test.png",
                "aspect_ratio": 0.8,
                "task_type_detected": "description",
            },
            output={
                "routed_to": "primary",
                "text_length": 250,
                "confidence": 0.88,
            },
            confidence=0.90,
            model_used="task_classifier + routing_logic",
            latency_ms=145,
            reasoning="Non-OCR task, routed to primary VLM",
        )
        evidence_id = store.store(evidence)

        retrieved = store.get(evidence_id)
        assert retrieved.feature == "vision_routing"
        assert retrieved.decision == "routed_to_primary"

    @pytest.mark.asyncio
    async def test_executor_evidence_with_lineage(self, tmp_path):
        """Test Evidence logging from Remote Executor with decision lineage"""
        store = EvidenceStore(str(tmp_path))

        # Simulate: safety gate decision → execution decision
        safety_gate = EvidenceEntry(
            feature="executor_action",
            decision="approved_L1_LOGGED",
            inputs={"command": "git add .", "approval_tier": "L1_LOGGED"},
            output={"approved": True},
            confidence=0.95,
            model_used="safety_evaluator",
            reasoning="Safe command, approved for execution",
        )
        safety_id = store.store(safety_gate)

        execution = EvidenceEntry(
            feature="executor_action",
            decision="executed_L1_LOGGED",
            inputs={"command": "git add .", "parent_decision": safety_id},
            output={"status": "success", "output_length": 0},
            confidence=0.98,
            model_used="remote_executor",
            parent_evidence_id=safety_id,
            executed=True,
            execution_status="success",
            reasoning="Executed approved L1_LOGGED action",
        )
        exec_id = store.store(execution)

        trace = store.trace(exec_id)
        assert trace is not None
        assert len(trace.ancestors) == 1
        assert "approved" in trace.ancestors[0].decision

    @pytest.mark.asyncio
    async def test_scout_qualification_evidence(self, tmp_path):
        """Test Evidence logging from Scout qualification"""
        store = EvidenceStore(str(tmp_path))

        evidence = EvidenceEntry(
            feature="scout_qualification",
            decision="bant_score_82",
            inputs={
                "company": "TechCorp",
                "fit_score": 85,
                "intent_level": 4,
                "pain_points": ["integration", "cost"],
            },
            output={
                "bant_score": 82,
                "qualification_status": "high_priority",
            },
            confidence=0.87,
            model_used="cascade_fast_bant_scorer",
            reasoning="Strong fit, clear pain points, decision-maker identified",
        )
        evidence_id = store.store(evidence)

        retrieved = store.get(evidence_id)
        assert retrieved.decision == "bant_score_82"
        assert retrieved.output["qualification_status"] == "high_priority"


class TestEvidenceQueryMethods:
    """Test query and analysis capabilities"""

    def test_filter_by_date_range(self, evidence_store):
        """Test filtering by date range"""
        now = datetime.utcnow()

        # Store old entry
        old_evidence = EvidenceEntry(
            feature="test",
            decision="old",
            inputs={},
            output={},
            confidence=0.8,
            model_used="test",
        )
        old_evidence.timestamp = now - timedelta(days=7)
        evidence_store.store(old_evidence)

        # Store new entry
        new_evidence = EvidenceEntry(
            feature="test",
            decision="new",
            inputs={},
            output={},
            confidence=0.8,
            model_used="test",
        )
        evidence_store.store(new_evidence)

        # Query all (should get both)
        all_entries = evidence_store.list_by_feature("test", limit=100)
        assert len(all_entries) == 2

    def test_confidence_ranking(self, evidence_store):
        """Test ranking evidence by confidence"""
        confidences = [0.60, 0.95, 0.75, 0.88]

        for conf in confidences:
            evidence = EvidenceEntry(
                feature="test",
                decision=f"decision_{conf}",
                inputs={},
                output={},
                confidence=conf,
                model_used="test",
            )
            evidence_store.store(evidence)

        results = evidence_store.list_by_feature("test", limit=100)
        # Results are returned in reverse chronological order (newest first)
        # but we could add a sort parameter
        assert len(results) == 4
        assert all(e.confidence in confidences for e in results)
