"""
Vision 2.0 Benchmark Harness (Sprint 12)

Suite de benchmarks para avaliar modelos VLM multimodais contra
tarefas reais do Seeker.Bot: OCR, UI grounding, descrição de cenas
e detecção de estados AFK.

Uso:
    python -m tests.vision_benchmark.runner --model qwen3.5:4b
    python -m tests.vision_benchmark.report --all
"""

from .tasks import BenchmarkTask, TaskCategory, load_dataset
from .metrics import (
    ocr_exact_match,
    ocr_levenshtein_similarity,
    grounding_iou,
    grounding_center_error,
    json_validity_rate,
    latency_stats,
)

__all__ = [
    "BenchmarkTask",
    "TaskCategory",
    "load_dataset",
    "ocr_exact_match",
    "ocr_levenshtein_similarity",
    "grounding_iou",
    "grounding_center_error",
    "json_validity_rate",
    "latency_stats",
]
