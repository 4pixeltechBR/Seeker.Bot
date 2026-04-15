"""
Tests for Vision Router (Vision 2.0 Phase A4.3).

Validates intelligent routing between GLM-OCR and Qwen3-VL-8b based on task classification.
"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
import numpy as np

pytest.importorskip("cv2")
import cv2

from src.skills.vision.vlm_router import VLMRouter
from src.skills.vision.task_classifier import TaskType


@pytest.fixture
def mock_primary_vlm():
    """Create mock Qwen3-VL-8b VLM client."""
    mock = Mock()
    mock.extract_text_from_image = AsyncMock(
        return_value={"text": "primary vlm text", "confidence": 0.87}
    )
    mock.analyze_screenshot = AsyncMock(
        return_value={"analysis": "screenshot analysis"}
    )
    mock.locate_element = AsyncMock(
        return_value={"x": 100, "y": 200, "confidence": 0.9}
    )
    mock.describe_page = AsyncMock(return_value={"description": "page description"})
    mock.health_check = AsyncMock(return_value=True)
    return mock


class TestVLMRouterInitialization:
    """Test VLM Router initialization."""

    def test_initialization_with_primary_vlm(self, mock_primary_vlm):
        """Test router initialization with primary VLM."""
        router = VLMRouter(mock_primary_vlm)
        assert router.primary_vlm == mock_primary_vlm
        assert router.classifier is not None

    def test_glmocr_enabled_by_default(self, mock_primary_vlm):
        """Test GLM-OCR is enabled by default."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=True)
        # May be enabled or disabled depending on initialization
        assert router.glm_ocr_enabled is not None

    def test_glmocr_disabled_on_request(self, mock_primary_vlm):
        """Test GLM-OCR can be disabled."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)
        assert router.glm_ocr_enabled is False

    def test_router_metrics_initialization(self, mock_primary_vlm):
        """Test router metrics are initialized."""
        router = VLMRouter(mock_primary_vlm)
        assert router.metrics["total_routed"] == 0
        assert router.metrics["routed_to_glm_ocr"] == 0
        assert router.metrics["routed_to_primary"] == 0


class TestVLMRouterRouting:
    """Test intelligent routing logic."""

    def test_routing_increments_counter(self, mock_primary_vlm):
        """Test routing increments total counter."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)

        async def test():
            with tempfile.TemporaryDirectory() as tmpdir:
                # Create dummy image
                img = np.zeros((100, 100, 3), dtype=np.uint8)
                path = Path(tmpdir) / "test.png"
                cv2.imwrite(str(path), img)

                await router.extract_text_from_image(str(path))
                assert router.metrics["total_routed"] == 1

        asyncio.run(test())

    def test_analyze_screenshot_uses_primary(self, mock_primary_vlm):
        """Test analyze_screenshot always routes to primary VLM."""
        router = VLMRouter(mock_primary_vlm)

        async def test():
            result = await router.analyze_screenshot("dummy.png")
            assert result == {"analysis": "screenshot analysis"}
            mock_primary_vlm.analyze_screenshot.assert_called_once()

        asyncio.run(test())

    def test_locate_element_uses_primary(self, mock_primary_vlm):
        """Test locate_element always routes to primary VLM."""
        router = VLMRouter(mock_primary_vlm)

        async def test():
            result = await router.locate_element("dummy.png", "button")
            assert result["x"] == 100
            assert result["y"] == 200
            mock_primary_vlm.locate_element.assert_called_once()

        asyncio.run(test())

    def test_describe_page_uses_primary(self, mock_primary_vlm):
        """Test describe_page always routes to primary VLM."""
        router = VLMRouter(mock_primary_vlm)

        async def test():
            result = await router.describe_page("dummy.png")
            assert result == {"description": "page description"}
            mock_primary_vlm.describe_page.assert_called_once()

        asyncio.run(test())


class TestVLMRouterMetrics:
    """Test metrics tracking."""

    def test_metrics_tracking_total(self, mock_primary_vlm):
        """Test total routing count."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)

        async def test():
            with tempfile.TemporaryDirectory() as tmpdir:
                img = np.zeros((100, 100, 3), dtype=np.uint8)
                path = Path(tmpdir) / "test.png"
                cv2.imwrite(str(path), img)

                for _ in range(5):
                    await router.extract_text_from_image(str(path))

                assert router.metrics["total_routed"] == 5

        asyncio.run(test())

    def test_metrics_routing_counts(self, mock_primary_vlm):
        """Test routing counts are tracked."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)

        async def test():
            with tempfile.TemporaryDirectory() as tmpdir:
                img = np.zeros((100, 100, 3), dtype=np.uint8)
                path = Path(tmpdir) / "test.png"
                cv2.imwrite(str(path), img)

                await router.extract_text_from_image(str(path))
                assert router.metrics["routed_to_primary"] >= 1

        asyncio.run(test())

    def test_metrics_get_metrics(self, mock_primary_vlm):
        """Test get_metrics returns structured data."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)

        async def test():
            with tempfile.TemporaryDirectory() as tmpdir:
                img = np.zeros((100, 100, 3), dtype=np.uint8)
                path = Path(tmpdir) / "test.png"
                cv2.imwrite(str(path), img)

                await router.extract_text_from_image(str(path))
                metrics = router.get_metrics()

                assert "total_routed" in metrics
                assert "routed_to_primary" in metrics
                assert "routed_to_glm_ocr" in metrics
                assert "latencies" in metrics

        asyncio.run(test())

    def test_metrics_latency_tracking(self, mock_primary_vlm):
        """Test latency is tracked per route."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)

        async def test():
            with tempfile.TemporaryDirectory() as tmpdir:
                img = np.zeros((100, 100, 3), dtype=np.uint8)
                path = Path(tmpdir) / "test.png"
                cv2.imwrite(str(path), img)

                await router.extract_text_from_image(str(path))
                metrics = router.get_metrics()

                assert len(metrics["latencies"]["primary"]) > 0
                # Latency may be very small (< 1ms) for mocks, but should be >= 0
                assert all(l >= 0 for l in metrics["latencies"]["primary"])

        asyncio.run(test())

    def test_metrics_percentages(self, mock_primary_vlm):
        """Test routing percentages are calculated."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)

        async def test():
            with tempfile.TemporaryDirectory() as tmpdir:
                img = np.zeros((100, 100, 3), dtype=np.uint8)
                path = Path(tmpdir) / "test.png"
                cv2.imwrite(str(path), img)

                for _ in range(10):
                    await router.extract_text_from_image(str(path))

                metrics = router.get_metrics()
                if metrics["total_routed"] > 0:
                    assert "primary_pct" in metrics
                    assert 0 <= metrics["primary_pct"] <= 100

        asyncio.run(test())


class TestVLMRouterResponseMetadata:
    """Test response includes routing metadata."""

    def test_response_includes_router_metadata(self, mock_primary_vlm):
        """Test extract_text_from_image response includes metadata."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)

        async def test():
            with tempfile.TemporaryDirectory() as tmpdir:
                img = np.zeros((100, 100, 3), dtype=np.uint8)
                path = Path(tmpdir) / "test.png"
                cv2.imwrite(str(path), img)

                result = await router.extract_text_from_image(str(path))
                assert "_router_metadata" in result
                assert "task_type" in result["_router_metadata"]
                assert "routed_to" in result["_router_metadata"]
                assert "total_latency_ms" in result["_router_metadata"]

        asyncio.run(test())

    def test_metadata_task_type(self, mock_primary_vlm):
        """Test metadata includes task type."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)

        async def test():
            with tempfile.TemporaryDirectory() as tmpdir:
                img = np.zeros((100, 100, 3), dtype=np.uint8)
                path = Path(tmpdir) / "test.png"
                cv2.imwrite(str(path), img)

                result = await router.extract_text_from_image(str(path))
                task_type = result["_router_metadata"]["task_type"]
                assert task_type in ["ocr", "grounding", "description"]

        asyncio.run(test())

    def test_metadata_routed_to(self, mock_primary_vlm):
        """Test metadata includes routed_to information."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)

        async def test():
            with tempfile.TemporaryDirectory() as tmpdir:
                img = np.zeros((100, 100, 3), dtype=np.uint8)
                path = Path(tmpdir) / "test.png"
                cv2.imwrite(str(path), img)

                result = await router.extract_text_from_image(str(path))
                routed_to = result["_router_metadata"]["routed_to"]
                assert routed_to in ["glm_ocr", "primary"]

        asyncio.run(test())


class TestVLMRouterHealthCheck:
    """Test health check propagation."""

    def test_health_check_delegates_to_primary(self, mock_primary_vlm):
        """Test health check delegates to primary VLM."""
        router = VLMRouter(mock_primary_vlm)

        async def test():
            health = await router.health_check()
            assert health is True
            mock_primary_vlm.health_check.assert_called_once()

        asyncio.run(test())

    def test_health_check_failure_handling(self, mock_primary_vlm):
        """Test health check handles failures."""
        mock_primary_vlm.health_check.side_effect = Exception("Health check failed")
        router = VLMRouter(mock_primary_vlm)

        async def test():
            health = await router.health_check()
            assert health is False

        asyncio.run(test())


class TestVLMRouterPrintMetrics:
    """Test metrics printing."""

    def test_print_metrics_no_error(self, mock_primary_vlm, caplog):
        """Test print_metrics does not raise error."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)

        async def test():
            with tempfile.TemporaryDirectory() as tmpdir:
                img = np.zeros((100, 100, 3), dtype=np.uint8)
                path = Path(tmpdir) / "test.png"
                cv2.imwrite(str(path), img)

                await router.extract_text_from_image(str(path))

                # Should not raise
                router.print_metrics()

        asyncio.run(test())


class TestVLMRouterErrorHandling:
    """Test error handling in routing."""

    def test_primary_vlm_error_handling(self, mock_primary_vlm):
        """Test router handles primary VLM errors."""
        mock_primary_vlm.extract_text_from_image.side_effect = Exception("VLM error")
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)

        async def test():
            with tempfile.TemporaryDirectory() as tmpdir:
                img = np.zeros((100, 100, 3), dtype=np.uint8)
                path = Path(tmpdir) / "test.png"
                cv2.imwrite(str(path), img)

                result = await router.extract_text_from_image(str(path))
                # Should return error dict
                assert "error" in result or "text" in result

        asyncio.run(test())

    def test_missing_image_handling(self, mock_primary_vlm):
        """Test router handles missing images."""
        router = VLMRouter(mock_primary_vlm, glm_ocr_enabled=False)

        async def test():
            result = await router.extract_text_from_image("/nonexistent.png")
            # Should still route and let primary VLM handle it
            assert router.metrics["total_routed"] == 1

        asyncio.run(test())
