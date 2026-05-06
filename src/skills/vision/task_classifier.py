"""
Task Classifier for Vision 2.0 — Intelligent Routing (Sprint 12 Phase A4.2).

Detects vision task type using lightweight heuristics:
- OCR-heavy: document detection (tall aspect ratio, high text density)
- UI-grounding: button/element detection (square aspect ratio, low text density)
- Description: general scene understanding (photos, natural scenes)

Routes OCR tasks to GLM-OCR specialist (94.5% accuracy, 1.2s latency)
Routes other tasks to Qwen3-VL:8b (0.76 IoU, multimodal)
"""

import logging
from enum import Enum
from pathlib import Path
from typing import Optional
import cv2
import numpy as np

log = logging.getLogger("seeker.vision.task_classifier")


class TaskType(Enum):
    """Vision task classification types."""
    OCR = "ocr"              # Document/text-heavy tasks
    GROUNDING = "grounding"   # UI element detection/localization
    DESCRIPTION = "description"  # Scene understanding, AFK detection


class TaskClassifier:
    """Lightweight task classifier for vision routing."""

    # Thresholds para detecção (tunáveis)
    ASPECT_RATIO_THRESHOLD = 1.1  # tall=document (>1.1), square=UI (<1.1)
    TEXT_DENSITY_THRESHOLD = 0.12  # high text density → OCR task
    COLOR_ENTROPY_THRESHOLD = 5.0  # low entropy → structured (document), high → natural scene

    def __init__(self):
        """Initialize classifier."""
        self.stats = {
            "total_classified": 0,
            "ocr": 0,
            "grounding": 0,
            "description": 0,
            "classifier_errors": 0,
        }

    @staticmethod
    def _load_image(image_path: str) -> Optional[np.ndarray]:
        """
        Load image from file path.

        Args:
            image_path: Path to image file

        Returns:
            Image array or None if failed
        """
        try:
            img = cv2.imread(str(image_path))
            if img is None:
                log.warning(f"[classifier] Failed to load image: {image_path}")
                return None
            return img
        except Exception as e:
            log.error(f"[classifier] Error loading image {image_path}: {e}")
            return None

    @staticmethod
    def _get_aspect_ratio(img: np.ndarray) -> float:
        """
        Calculate image aspect ratio (height/width).

        Tall images (>1.2) suggest documents.
        Square images (<1.2) suggest UIs.
        """
        height, width = img.shape[:2]
        return height / width if width > 0 else 1.0

    @staticmethod
    def _estimate_text_density(img: np.ndarray) -> float:
        """
        Estimate text density using edge detection.

        High edge density (>0.15) suggests text/documents.
        Low edge density (<0.15) suggests photos/natural scenes.
        """
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # Detect edges using Canny
            edges = cv2.Canny(gray, 50, 150)

            # Calculate density as ratio of white pixels
            text_pixels = np.count_nonzero(edges)
            total_pixels = edges.size
            density = text_pixels / total_pixels if total_pixels > 0 else 0.0

            return density
        except Exception as e:
            log.warning(f"[classifier] Error estimating text density: {e}")
            return 0.0

    @staticmethod
    def _estimate_color_entropy(img: np.ndarray) -> float:
        """
        Estimate color complexity using color distribution entropy.

        Low entropy (<5.0) suggests structured content (documents, UI).
        High entropy (>5.0) suggests natural scenes (photos, complex backgrounds).
        """
        try:
            # Convert to HSV for better color analysis
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

            # Calculate histogram for each channel
            histograms = []
            for i in range(3):
                hist = cv2.calcHist([hsv], [i], None, [32], [0, 256])
                histograms.append(hist.flatten() / hist.sum())

            # Calculate entropy for combined histogram
            combined_hist = np.mean(histograms, axis=0)
            entropy = -np.sum(combined_hist * np.log2(combined_hist + 1e-10))

            return float(entropy)  # Convert to native Python float
        except Exception as e:
            log.warning(f"[classifier] Error estimating color entropy: {e}")
            return 5.0  # Default to neutral

    def classify(self, image_path: str) -> TaskType:
        """
        Classify vision task based on image characteristics.

        Classification logic:
        1. If aspect ratio > 1.2 (tall) AND text density > 0.15 → OCR
        2. If aspect ratio < 1.2 (square) AND color entropy < 5.0 → GROUNDING
        3. Otherwise → DESCRIPTION

        Args:
            image_path: Path to image file

        Returns:
            TaskType: Classified task type (OCR, GROUNDING, or DESCRIPTION)
        """
        self.stats["total_classified"] += 1

        # Load image
        img = self._load_image(image_path)
        if img is None:
            log.warning(f"[classifier] Defaulting to DESCRIPTION for failed load")
            self.stats["description"] += 1
            self.stats["classifier_errors"] += 1
            return TaskType.DESCRIPTION

        # Extract features
        aspect_ratio = self._get_aspect_ratio(img)
        text_density = self._estimate_text_density(img)
        color_entropy = self._estimate_color_entropy(img)

        log.debug(
            f"[classifier] Image analysis: "
            f"aspect_ratio={aspect_ratio:.2f}, "
            f"text_density={text_density:.4f}, "
            f"color_entropy={color_entropy:.2f}"
        )

        # Classification heuristics
        is_tall = aspect_ratio > self.ASPECT_RATIO_THRESHOLD
        is_text_heavy = text_density > self.TEXT_DENSITY_THRESHOLD
        is_structured = color_entropy < self.COLOR_ENTROPY_THRESHOLD

        # Decision tree
        if is_text_heavy:  # High text density is strong signal for OCR
            task_type = TaskType.OCR
            log.info(f"[classifier] Classified as OCR (text_heavy={is_text_heavy})")
        elif not is_tall and is_structured:
            task_type = TaskType.GROUNDING
            log.info(f"[classifier] Classified as GROUNDING (square={not is_tall}, structured={is_structured})")
        else:
            task_type = TaskType.DESCRIPTION
            log.info(f"[classifier] Classified as DESCRIPTION (default)")

        # Update stats
        if task_type == TaskType.OCR:
            self.stats["ocr"] += 1
        elif task_type == TaskType.GROUNDING:
            self.stats["grounding"] += 1
        else:
            self.stats["description"] += 1

        return task_type

    def get_stats(self) -> dict:
        """
        Get classification statistics.

        Returns:
            Dict with classification counts and percentages
        """
        total = self.stats["total_classified"]
        if total == 0:
            return self.stats.copy()

        return {
            **self.stats,
            "ocr_pct": 100 * self.stats["ocr"] / total,
            "grounding_pct": 100 * self.stats["grounding"] / total,
            "description_pct": 100 * self.stats["description"] / total,
        }
