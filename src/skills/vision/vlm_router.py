"""
Vision Router for Vision 3.0 (Sexta-feira Stack).

Intelligent routing between:
1. Gemini VLM (Cloud - Primary Grounding & Logic)
2. Qwen2.5-VL (Local - Fallback Grounding)
3. GLM-OCR (Local - Pure OCR Specialist)

Routing logic:
- TaskType.OCR → GLM-OCR specialist (94.5% accuracy, 1.2s)
- TaskType.GROUNDING → Gemini Robotics-ER/1.5-Pro (Cloud) -> Fallback: Qwen2.5-VL (Local)
- TaskType.DESCRIPTION → Gemini 2.5 (Cloud) -> Fallback: Qwen2.5-VL (Local)
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
    """Intelligent router between Cloud (Gemini), Local VLM (Qwen), and OCR specialist (GLM-OCR)."""

    def __init__(
        self,
        cloud_vlm_client,  # Gemini
        local_vlm_client,  # Qwen2.5-VL via Ollama
        glm_ocr_enabled: bool = True,
        glm_ocr_mode: str = "selfhost",
        strict_guardrail: bool = True, # Se True, desativa locais quando VRAM está cheia (ex: ViralClip rodando)
    ):
        self.cloud_vlm = cloud_vlm_client
        self.local_vlm = local_vlm_client
        self.classifier = TaskClassifier()
        self.strict_guardrail = strict_guardrail

        # Initialize GLM-OCR specialist
        self.glm_ocr_enabled = glm_ocr_enabled
        self.glm_ocr = None
        if glm_ocr_enabled:
            try:
                self.glm_ocr = GlmOcrClient(
                    mode=glm_ocr_mode,
                    fallback_vlm_client=self.cloud_vlm, # Fallback to cloud if OCR fails
                )
                if self.glm_ocr.enabled:
                    log.info(f"[router] GLM-OCR specialist initialized (mode={glm_ocr_mode})")
                else:
                    log.warning("[router] GLM-OCR failed to initialize, disabling")
                    self.glm_ocr_enabled = False
            except Exception as e:
                log.error(f"[router] Failed to initialize GLM-OCR: {e}")
                self.glm_ocr_enabled = False

        self.metrics = {
            "total_routed": 0,
            "routed_to_glm_ocr": 0,
            "routed_to_cloud": 0,
            "routed_to_local": 0,
            "latencies": {"glm_ocr": [], "cloud": [], "local": []},
        }

    def _is_vram_exhausted(self) -> bool:
        """
        Check if VRAM is exhausted (e.g., ViralClip State Machine active).
        This acts as the strict guardrail to route everything to Cloud.
        """
        # For implementation: Integrate with Seeker Pipeline State / System Monitor
        # For now, we assume we check the local_vlm's GPU semaphore if available
        if hasattr(self.local_vlm, "_is_gpu_available"):
            return not self.local_vlm._is_gpu_available()
        return False

    async def _execute_with_routing(self, task_type: TaskType, image_path: str | bytes, action: str, **kwargs) -> Dict:
        """Core routing logic engine."""
        self.metrics["total_routed"] += 1
        start_time = time.time()
        
        vram_exhausted = self._is_vram_exhausted() and self.strict_guardrail
        routed_to = "cloud" # Default safe option

        # Decide Router
        if task_type == TaskType.OCR and not vram_exhausted and self.glm_ocr_enabled:
            routed_to = "glm_ocr"
        elif not vram_exhausted and self.local_vlm and await self.local_vlm.health_check():
            # If local VLM is healthy and we have VRAM, we could use it as fallback 
            # Or use Cloud as primary if we prefer speed.
            # Usually Cloud is Primary for grounding if we have limits available.
            if getattr(self.cloud_vlm, "enabled", True):
                routed_to = "cloud"
            else:
                routed_to = "local"
        else:
            routed_to = "cloud"

        # Execute
        try:
            if routed_to == "glm_ocr" and action == "extract_text_from_image":
                result = await self.glm_ocr.extract_text_from_image(image_path)
            elif routed_to == "local":
                method = getattr(self.local_vlm, action)
                result = await method(image_path, **kwargs)
            else:
                # Cloud
                method = getattr(self.cloud_vlm, action)
                result = await method(image_path, **kwargs)
        except Exception as e:
            log.error(f"[router] Primary route {routed_to} failed: {e}. Falling back to Cloud.")
            routed_to = "cloud_fallback"
            method = getattr(self.cloud_vlm, action)
            result = await method(image_path, **kwargs)

        latency = (time.time() - start_time) * 1000
        
        # Update metrics
        target_metric = "cloud" if "cloud" in routed_to else routed_to
        self.metrics[f"routed_to_{target_metric}"] += 1
        self.metrics["latencies"][target_metric].append(latency)

        log.debug(f"[router] Task {action} routed to {routed_to} in {latency:.1f}ms")
        return result

    async def extract_text_from_image(self, image_path: str | bytes) -> Dict:
        """Route OCR task to GLM-OCR specialist or Cloud."""
        task_type = TaskType.OCR
        return await self._execute_with_routing(task_type, image_path, "extract_text_from_image")

    async def analyze_screenshot(self, image_path: str | bytes, prompt: Optional[str] = None) -> Dict:
        """Route screenshot analysis to General VLM."""
        task_type = TaskType.DESCRIPTION
        kwargs = {"prompt": prompt} if prompt is not None else {}
        return await self._execute_with_routing(task_type, image_path, "analyze_screenshot", **kwargs)

    async def locate_element(self, image_path: str | bytes, description: str) -> Dict:
        """Route element localization (Grounding) to Primary VLM."""
        task_type = TaskType.GROUNDING
        return await self._execute_with_routing(task_type, image_path, "locate_element", description=description)

    async def describe_page(self, image_path: str | bytes) -> Dict:
        """Route page description."""
        task_type = TaskType.DESCRIPTION
        return await self._execute_with_routing(task_type, image_path, "describe_page")

    async def health_check(self) -> bool:
        """Check health of router."""
        if getattr(self.cloud_vlm, "enabled", False):
            return True
        if self.local_vlm:
            return await self.local_vlm.health_check()
        return False
