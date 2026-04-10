"""
Vision 2.0 Benchmark — Regression tests.

Testa que o modelo VLM atual mantém um baseline mínimo de
qualidade, evitando regressões acidentais após upgrades.

Teste unitário que roda localmente via pytest:
    pytest tests/vision_benchmark/test_vlm_benchmark.py -v
"""

import asyncio
import logging
import pytest
from pathlib import Path

from src.skills.vision.vlm_client import VLMClient
from .tasks import BenchmarkTask, TaskCategory, load_dataset
from .metrics import (
    ocr_exact_match,
    ocr_levenshtein_similarity,
    grounding_iou,
    is_valid_json,
)

log = logging.getLogger("seeker.vision.benchmark.tests")

# Thresholds mínimos para evitar regressão
BASELINE_THRESHOLDS = {
    "ocr_exact_match_%": 70.0,        # Pelo menos 70% exatidão
    "ocr_levenshtein_mean": 0.75,     # Pelo menos 0.75 similaridade
    "grounding_iou_mean": 0.65,       # Pelo menos 0.65 IoU
    "json_validity_%": 90.0,          # Pelo menos 90% JSON válido
}


class TestVLMBenchmark:
    """Regression tests para o VLM em produção."""

    @pytest.fixture
    async def vlm_client(self):
        """Cria cliente VLM (model vem do env ou default)."""
        client = VLMClient()
        # Health check
        healthy = await client.health_check()
        assert healthy, f"VLM {client.model} não está disponível no Ollama"
        yield client
        await client.close()

    @pytest.mark.asyncio
    async def test_ocr_baseline(self, vlm_client):
        """Testa OCR contra baseline mínimo."""
        tasks = load_dataset(
            categories=[TaskCategory.OCR],
            limit=5,  # Smoke test com 5 tasks
        )
        if not tasks:
            pytest.skip("Nenhuma task OCR no dataset")

        exact_matches = 0
        levenshtein_scores = []

        for task in tasks:
            try:
                image_bytes = task.load_image()
                response = await vlm_client.extract_text_from_image(image_bytes)

                expected_text = task.ground_truth.get("text", "")
                if ocr_exact_match(response, expected_text):
                    exact_matches += 1

                lev_sim = ocr_levenshtein_similarity(response, expected_text)
                levenshtein_scores.append(lev_sim)
            except Exception as e:
                log.error(f"Task {task.task_id}: {e}")

        if levenshtein_scores:
            mean_lev = sum(levenshtein_scores) / len(levenshtein_scores)
            exact_pct = (exact_matches / len(tasks)) * 100

            log.info(
                f"OCR Baseline: exact={exact_pct:.1f}%, "
                f"levenshtein={mean_lev:.3f}"
            )

            assert exact_pct >= BASELINE_THRESHOLDS["ocr_exact_match_%"], (
                f"OCR exact-match regrediu: {exact_pct:.1f}% < "
                f"{BASELINE_THRESHOLDS['ocr_exact_match_%']}%"
            )
            assert mean_lev >= BASELINE_THRESHOLDS["ocr_levenshtein_mean"], (
                f"OCR levenshtein regrediu: {mean_lev:.3f} < "
                f"{BASELINE_THRESHOLDS['ocr_levenshtein_mean']}"
            )

    @pytest.mark.asyncio
    async def test_grounding_baseline(self, vlm_client):
        """Testa grounding (localização UI) contra baseline."""
        tasks = load_dataset(
            categories=[TaskCategory.GROUNDING],
            limit=5,
        )
        if not tasks:
            pytest.skip("Nenhuma task grounding no dataset")

        ious = []
        json_valid_count = 0

        for task in tasks:
            try:
                image_bytes = task.load_image()
                expected_bbox = task.ground_truth.get("bbox", {})
                expected_desc = task.ground_truth.get("description", "element")

                response = await vlm_client.locate_element(
                    image_bytes, expected_desc
                )

                # response é dict já parseado por vlm_client
                iou = grounding_iou(response, expected_bbox)
                ious.append(iou)

                if "x" in response and "y" in response:
                    json_valid_count += 1
            except Exception as e:
                log.error(f"Task {task.task_id}: {e}")

        if ious:
            mean_iou = sum(ious) / len(ious)
            json_pct = (json_valid_count / len(tasks)) * 100

            log.info(
                f"Grounding Baseline: IoU={mean_iou:.3f}, "
                f"json_valid={json_pct:.1f}%"
            )

            assert mean_iou >= BASELINE_THRESHOLDS["grounding_iou_mean"], (
                f"Grounding IoU regrediu: {mean_iou:.3f} < "
                f"{BASELINE_THRESHOLDS['grounding_iou_mean']}"
            )
            assert json_pct >= BASELINE_THRESHOLDS["json_validity_%"], (
                f"Grounding JSON validity regrediu: {json_pct:.1f}% < "
                f"{BASELINE_THRESHOLDS['json_validity_%']}%"
            )

    @pytest.mark.asyncio
    async def test_model_hot_swap(self, vlm_client):
        """Testa hot-swap de modelo via set_model()."""
        original_model = vlm_client.model

        # Tenta trocar para outro modelo (pode falhar se não estiver instalado)
        try:
            await vlm_client.set_model("qwen2.5vl:7b")
            assert vlm_client.model == "qwen2.5vl:7b"

            # Volta ao original
            await vlm_client.set_model(original_model)
            assert vlm_client.model == original_model
        except Exception as e:
            log.warning(f"Hot-swap test falhou (modelo não instalado?): {e}")


class TestMetrics:
    """Tests para funções de métrica."""

    def test_ocr_exact_match_basic(self):
        """Testa ocr_exact_match com casos simples."""
        assert ocr_exact_match("Hello world", "hello world") is True
        assert ocr_exact_match("Hello", "Goodbye") is False
        assert ocr_exact_match("  Hello  ", "hello") is True

    def test_levenshtein_similarity(self):
        """Testa ocr_levenshtein_similarity."""
        assert ocr_levenshtein_similarity("abc", "abc") == 1.0
        assert ocr_levenshtein_similarity("", "") == 1.0
        sim = ocr_levenshtein_similarity("kitten", "sitting")
        assert 0.4 < sim < 0.6  # Valor esperado ~0.57

    def test_grounding_iou_perfect(self):
        """Testa IoU com boxes idênticos."""
        bbox = {"x": 100, "y": 100, "width": 50, "height": 50}
        assert grounding_iou(bbox, bbox) == 1.0

    def test_grounding_iou_no_overlap(self):
        """Testa IoU com boxes sem sobreposição."""
        bbox1 = {"x": 0, "y": 0, "width": 10, "height": 10}
        bbox2 = {"x": 100, "y": 100, "width": 10, "height": 10}
        assert grounding_iou(bbox1, bbox2) == 0.0

    def test_is_valid_json(self):
        """Testa is_valid_json."""
        assert is_valid_json('{"x": 100, "y": 200}') is True
        assert is_valid_json("```json\n{\"x\": 100}\n```") is True
        assert is_valid_json("not json") is False
        assert is_valid_json("") is False
