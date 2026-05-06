"""
Vision Router for Vision 2.0 (Sprint 12 Phase A4.3).

Intelligent routing between GLM-OCR specialist and Qwen3-VL-8b general model.

Routing logic:
- TaskType.OCR → GLM-OCR specialist (94.5% accuracy, 1.2s)
- TaskType.GROUNDING → Qwen3-VL-8b (0.76 IoU, UI-focused)
- TaskType.DESCRIPTION → Qwen3-VL-8b (multimodal, AFK detection)

Metrics tracked:
- Per-model latency
- Per-task-type accuracy
- Routing decisions logged for analysis
"""

import asyncio
import logging
import time
from typing import Dict, Optional

from .task_classifier import TaskClassifier, TaskType
from .glm_ocr_client import GlmOcrClient
from src.core.evidence import EvidenceEntry, get_evidence_store

log = logging.getLogger("seeker.vision.vlm_router")


class VLMRouter:
    """Intelligent router between OCR specialist and general VLM."""

    def __init__(
        self,
        primary_vlm_client,  # Qwen3-VL-8b
        glm_ocr_enabled: bool = True,
        glm_ocr_mode: str = "selfhost",
    ):
        """
        Initialize vision router.

        Args:
            primary_vlm_client: VLMClient instance (Qwen3-VL-8b)
            glm_ocr_enabled: Enable GLM-OCR routing
            glm_ocr_mode: GLM-OCR deployment mode ("selfhost" or "maas")
        """
        self.primary_vlm = primary_vlm_client
        self.classifier = TaskClassifier()

        # Initialize GLM-OCR specialist
        self.glm_ocr_enabled = glm_ocr_enabled
        self.glm_ocr = None
        if glm_ocr_enabled:
            try:
                self.glm_ocr = GlmOcrClient(
                    mode=glm_ocr_mode,
                    fallback_vlm_client=primary_vlm_client,
                )
                if self.glm_ocr.enabled:
                    log.info(
                        f"[router] GLM-OCR specialist initialized (mode={glm_ocr_mode})"
                    )
                else:
                    log.warning("[router] GLM-OCR failed to initialize, disabling")
                    self.glm_ocr_enabled = False
            except Exception as e:
                log.error(f"[router] Failed to initialize GLM-OCR: {e}")
                self.glm_ocr_enabled = False

        # Metrics tracking
        self.metrics = {
            "total_routed": 0,
            "routed_to_glm_ocr": 0,
            "routed_to_primary": 0,
            "classifier_errors": 0,
            "latencies": {
                "glm_ocr": [],
                "primary": [],
                "classifier": [],
            },
        }

    async def extract_text_from_image(self, image_path: str) -> Dict:
        """
        Route OCR task to GLM-OCR specialist or primary VLM.

        Args:
            image_path: Path to image file

        Returns:
            Dict with extracted text and metadata
        """
        self.metrics["total_routed"] += 1
        start_time = time.time()
        evidence_store = get_evidence_store()

        # Classify task
        try:
            classifier_start = time.time()
            task_type = self.classifier.classify(image_path)
            classifier_latency = (time.time() - classifier_start) * 1000
            self.metrics["latencies"]["classifier"].append(classifier_latency)
        except Exception as e:
            log.error(f"[router] Task classification failed: {e}")
            self.metrics["classifier_errors"] += 1
            task_type = TaskType.DESCRIPTION  # Fallback to primary

        log.debug(f"[router] Task classified as {task_type.value}")

        # Route based on task type
        routed_to = "glm_ocr" if (task_type == TaskType.OCR and self.glm_ocr_enabled and self.glm_ocr) else "primary"

        if routed_to == "glm_ocr":
            result = await self._route_to_glm_ocr(image_path)
        else:
            result = await self._route_to_primary(image_path)

        # Track total latency
        total_latency = (time.time() - start_time) * 1000
        log.debug(f"[router] Total routing latency: {total_latency:.1f}ms")

        # Log Evidence entry for routing decision
        evidence = EvidenceEntry(
            feature="vision_routing",
            decision=f"routed_to_{routed_to}",
            inputs={
                "image_path": image_path,
                "aspect_ratio": self.classifier._get_aspect_ratio(self.classifier._load_image(image_path)) if self.classifier._load_image(image_path) is not None else 0.0,
                "task_type_detected": task_type.value,
            },
            output={
                "routed_to": routed_to,
                "text_length": len(result.get("text", "")),
                "confidence": result.get("confidence", 0.0),
            },
            confidence=0.85 if task_type == TaskType.OCR else 0.90,
            model_used="task_classifier + routing_logic",
            latency_ms=int(total_latency),
            reasoning=f"Task detected as {task_type.value}, routed to {routed_to} specialist",
        )
        evidence_store.store(evidence)

        # Add routing metadata
        result["_router_metadata"] = {
            "task_type": task_type.value,
            "routed_to": routed_to,
            "total_latency_ms": total_latency,
            "evidence_id": evidence.evidence_id,
        }

        return result

    async def _route_to_glm_ocr(self, image_path: str) -> Dict:
        """Route to GLM-OCR specialist."""
        try:
            start_time = time.time()
            result = await self.glm_ocr.extract_text_from_image(image_path)
            latency = (time.time() - start_time) * 1000

            self.metrics["routed_to_glm_ocr"] += 1
            self.metrics["latencies"]["glm_ocr"].append(latency)

            log.info(
                f"[router] Routed to GLM-OCR: "
                f"{len(result.get('text', ''))} chars, {latency:.1f}ms"
            )

            return result
        except Exception as e:
            log.error(f"[router] GLM-OCR routing failed: {e}, falling back to primary")
            return await self._route_to_primary(image_path)

    async def _route_to_primary(self, image_path: str) -> Dict:
        """Route to Qwen3-VL-8b primary model."""
        try:
            start_time = time.time()
            result = await self.primary_vlm.extract_text_from_image(image_path)
            latency = (time.time() - start_time) * 1000

            self.metrics["routed_to_primary"] += 1
            self.metrics["latencies"]["primary"].append(latency)

            log.info(
                f"[router] Routed to Primary VLM: "
                f"{len(result.get('text', ''))} chars, {latency:.1f}ms"
            )

            return result
        except Exception as e:
            log.error(f"[router] Primary VLM routing failed: {e}")
            return {
                "text": "",
                "confidence": 0.0,
                "error": str(e),
            }

    async def analyze_screenshot(self, image_path: str) -> Dict:
        """
        Route screenshot analysis to primary VLM.

        GLM-OCR is OCR-only specialist. All other tasks use primary VLM.
        """
        return await self.primary_vlm.analyze_screenshot(image_path)

    async def locate_element(self, image_path: str, description: str) -> Dict:
        """
        Route element localization to primary VLM.

        GLM-OCR is OCR-only specialist. UI grounding uses primary VLM.
        """
        return await self.primary_vlm.locate_element(image_path, description)

    async def describe_page(self, image_path: str) -> Dict:
        """
        Route page description to primary VLM.

        GLM-OCR is OCR-only specialist. Scene understanding uses primary VLM.
        """
        return await self.primary_vlm.describe_page(image_path)

    async def health_check(self) -> bool:
        """Check health of router (primary VLM)."""
        try:
            return await self.primary_vlm.health_check()
        except Exception as e:
            log.error(f"[router] Health check failed: {e}")
            return False

    def get_metrics(self) -> Dict:
        """
        Get routing metrics.

        Returns:
            Dict with routing statistics and latency analysis
        """
        metrics = self.metrics.copy()

        # Calculate averages
        if metrics["latencies"]["glm_ocr"]:
            metrics["avg_glm_ocr_latency_ms"] = (
                sum(metrics["latencies"]["glm_ocr"]) / len(metrics["latencies"]["glm_ocr"])
            )
        if metrics["latencies"]["primary"]:
            metrics["avg_primary_latency_ms"] = (
                sum(metrics["latencies"]["primary"]) / len(metrics["latencies"]["primary"])
            )
        if metrics["latencies"]["classifier"]:
            metrics["avg_classifier_latency_ms"] = (
                sum(metrics["latencies"]["classifier"]) / len(metrics["latencies"]["classifier"])
            )

        # Calculate routing percentages
        if metrics["total_routed"] > 0:
            metrics["glm_ocr_pct"] = 100 * metrics["routed_to_glm_ocr"] / metrics["total_routed"]
            metrics["primary_pct"] = 100 * metrics["routed_to_primary"] / metrics["total_routed"]

        return metrics

    def print_metrics(self):
        """Print routing metrics to log."""
        metrics = self.get_metrics()
        log.info(
            f"[router] Routing Metrics: "
            f"total={metrics['total_routed']}, "
            f"glm_ocr={metrics['routed_to_glm_ocr']} ({metrics.get('glm_ocr_pct', 0):.1f}%), "
            f"primary={metrics['routed_to_primary']} ({metrics.get('primary_pct', 0):.1f}%), "
            f"errors={metrics['classifier_errors']}"
        )
        if metrics.get("avg_glm_ocr_latency_ms"):
            log.info(
                f"[router] GLM-OCR Latency: {metrics['avg_glm_ocr_latency_ms']:.1f}ms avg"
            )
        if metrics.get("avg_primary_latency_ms"):
            log.info(
                f"[router] Primary Latency: {metrics['avg_primary_latency_ms']:.1f}ms avg"
            )
