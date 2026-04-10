"""
Vision 2.0 Benchmark — Runner (orquestrador).

Executa benchmark contra uma ou múltiplas VLMs, coletando métricas
de OCR, grounding, description e latência.

Uso:
    python -m tests.vision_benchmark.runner --model qwen3.5:4b
    python -m tests.vision_benchmark.runner --all-models
    python -m tests.vision_benchmark.runner --model qwen3-vl:8b --limit 10
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from dataclasses import asdict, field, dataclass
from typing import Optional

from src.skills.vision.vlm_client import VLMClient
from .tasks import BenchmarkTask, TaskCategory, load_dataset, save_results
from .metrics import (
    ocr_exact_match,
    ocr_levenshtein_similarity,
    grounding_iou,
    grounding_center_error,
    json_validity_rate,
    latency_stats,
    is_valid_json,
)

log = logging.getLogger("seeker.vision.benchmark.runner")

REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"
MODELS_TO_BENCHMARK = [
    "qwen3.5:4b",
    "qwen2.5vl:7b",
    "qwen3-vl:8b",
    "minicpm-v",
]


@dataclass
class BenchmarkResult:
    """Resultado de uma task executada."""
    task_id: str
    model: str
    category: str
    predicted: str
    ground_truth: dict
    latency_ms: float
    timestamp: float

    # Métricas preenchidas pós-resultado
    ocr_exact_match: bool = False
    ocr_levenshtein: float = 0.0
    grounding_iou: float = 0.0
    grounding_center_error: float = float("inf")
    json_valid: bool = False
    keywords_coverage: float = 0.0

    def to_dict(self) -> dict:
        """Serializa para JSON."""
        d = asdict(self)
        d["timestamp"] = self.timestamp
        return d


class VLMBenchmarkRunner:
    """Orquestrador de benchmark para múltiplos VLMs."""

    def __init__(self, vlm: VLMClient, model_name: str):
        self.vlm = vlm
        self.model_name = model_name
        self.results: list[BenchmarkResult] = []

    async def run_task(self, task: BenchmarkTask) -> BenchmarkResult:
        """Executa uma task e coleta métricas."""
        start_ms = time.time() * 1000

        # Carrega imagem
        try:
            image_bytes = task.load_image()
        except FileNotFoundError as e:
            log.error(f"[runner] Task {task.task_id}: {e}")
            return BenchmarkResult(
                task_id=task.task_id,
                model=self.model_name,
                category=task.category.value,
                predicted="ERROR: image not found",
                ground_truth=task.ground_truth,
                latency_ms=0.0,
                timestamp=time.time(),
            )

        # Determina prompt
        if task.prompt_override:
            prompt = task.prompt_override
        elif task.category == TaskCategory.OCR:
            prompt = (
                "Extract all the text from this image exactly as written. "
                "Preserve the original language. Do not add explanatory text."
            )
        elif task.category == TaskCategory.GROUNDING:
            description = task.ground_truth.get("description", "element")
            prompt = (
                f"Find the UI element: '{description}'. "
                f"Return ONLY a JSON object with the center coordinates: "
                f'{{"x": <center_x_pixels>, "y": <center_y_pixels>, "confidence": <0.0-1.0>}}'
            )
        elif task.category == TaskCategory.DESCRIPTION:
            prompt = (
                "Describe this webpage screenshot in Portuguese (PT-BR). "
                "List: 1) Page title/header 2) Main content summary "
                "3) Clickable buttons or links visible 4) Any forms or input fields. "
                "Be concise and factual."
            )
        elif task.category == TaskCategory.AFK:
            prompt = (
                "Analyze this desktop screenshot. Return ONLY a JSON object: "
                '{"state": "idle|active|modal|error", "confidence": <0.0-1.0>}'
            )
        else:
            prompt = "Analyze this image."

        # Executa VLM
        try:
            predicted = await self.vlm.analyze_screenshot(image_bytes, prompt)
        except Exception as e:
            log.error(f"[runner] Task {task.task_id}: VLM erro: {e}")
            predicted = f"ERROR: {type(e).__name__}"

        latency_ms = time.time() * 1000 - start_ms

        # Cria resultado
        result = BenchmarkResult(
            task_id=task.task_id,
            model=self.model_name,
            category=task.category.value,
            predicted=predicted,
            ground_truth=task.ground_truth,
            latency_ms=latency_ms,
            timestamp=time.time(),
        )

        # Calcula métricas conforme a categoria
        if task.category == TaskCategory.OCR:
            expected_text = task.ground_truth.get("text", "")
            result.ocr_exact_match = ocr_exact_match(predicted, expected_text)
            result.ocr_levenshtein = ocr_levenshtein_similarity(predicted, expected_text)

        elif task.category == TaskCategory.GROUNDING:
            expected_bbox = task.ground_truth.get("bbox", {})
            try:
                # Parse JSON da resposta
                clean = predicted.strip()
                if clean.startswith("```"):
                    clean = clean.split("```")[1].strip()
                    if clean.startswith("json"):
                        clean = clean[4:].strip()
                predicted_bbox = json.loads(clean)
                result.json_valid = True
            except (json.JSONDecodeError, ValueError, IndexError):
                predicted_bbox = {"x": 0, "y": 0}
                result.json_valid = False

            result.grounding_iou = grounding_iou(predicted_bbox, expected_bbox)
            result.grounding_center_error = grounding_center_error(
                predicted_bbox, expected_bbox
            )

        elif task.category == TaskCategory.DESCRIPTION:
            expected_keywords = task.ground_truth.get("keywords", [])
            # keywords_coverage implementado em metrics.py
            if expected_keywords:
                hits = sum(
                    1
                    for kw in expected_keywords
                    if kw.lower() in predicted.lower()
                )
                result.keywords_coverage = hits / len(expected_keywords)

        elif task.category == TaskCategory.AFK:
            expected_state = task.ground_truth.get("state", "")
            result.json_valid = is_valid_json(predicted)
            # Simples match de string do estado
            result.ocr_exact_match = expected_state.lower() in predicted.lower()

        self.results.append(result)
        return result

    async def run_all_tasks(
        self,
        tasks: list[BenchmarkTask],
        verbose: bool = True,
    ):
        """Executa todas as tasks sequencialmente (lock de GPU)."""
        log.info(
            f"[runner] Iniciando benchmark: modelo={self.model_name}, "
            f"tasks={len(tasks)}"
        )

        for i, task in enumerate(tasks, 1):
            result = await self.run_task(task)
            if verbose:
                log.info(
                    f"[runner] [{i}/{len(tasks)}] {task.task_id} "
                    f"({result.latency_ms:.1f}ms) ✓"
                )

        log.info(f"[runner] Benchmark completo: {len(self.results)} tasks")

    def summarize(self) -> dict:
        """Gera resumo de métricas por categoria."""
        summary = {
            "model": self.model_name,
            "total_tasks": len(self.results),
            "timestamp": time.time(),
            "by_category": {},
        }

        by_cat = {}
        for r in self.results:
            if r.category not in by_cat:
                by_cat[r.category] = []
            by_cat[r.category].append(r)

        for cat, cat_results in by_cat.items():
            cat_summary = {
                "count": len(cat_results),
                "latency_ms": {
                    "mean": sum(r.latency_ms for r in cat_results) / len(cat_results),
                    "min": min(r.latency_ms for r in cat_results),
                    "max": max(r.latency_ms for r in cat_results),
                },
            }

            if cat == "ocr":
                exact = sum(1 for r in cat_results if r.ocr_exact_match)
                cat_summary["ocr_exact_match_%"] = (exact / len(cat_results) * 100)
                levenshtein = [r.ocr_levenshtein for r in cat_results]
                cat_summary["ocr_levenshtein_mean"] = (
                    sum(levenshtein) / len(levenshtein)
                )

            elif cat == "grounding":
                ious = [r.grounding_iou for r in cat_results]
                cat_summary["grounding_iou_mean"] = sum(ious) / len(ious)
                valid = sum(1 for r in cat_results if r.json_valid)
                cat_summary["json_valid_%"] = (valid / len(cat_results) * 100)
                errors = [
                    r.grounding_center_error
                    for r in cat_results
                    if r.grounding_center_error != float("inf")
                ]
                if errors:
                    cat_summary["grounding_center_error_mean_px"] = (
                        sum(errors) / len(errors)
                    )

            elif cat == "description":
                coverage = [r.keywords_coverage for r in cat_results]
                cat_summary["keywords_coverage_mean"] = (
                    sum(coverage) / len(coverage)
                )

            summary["by_category"][cat] = cat_summary

        return summary


async def run_benchmark(
    model: str,
    limit: Optional[int] = None,
    categories: Optional[list[str]] = None,
):
    """Entry point para rodar benchmark em um modelo."""
    # Parse categories
    if categories:
        cats = [TaskCategory[c.upper()] for c in categories if c.upper() in TaskCategory.__members__]
    else:
        cats = list(TaskCategory)

    # Carrega dataset
    tasks = load_dataset(categories=cats, limit=limit)
    if not tasks:
        log.error("[runner] Nenhuma task carregada do dataset")
        return

    log.info(f"[runner] Dataset: {len(tasks)} tasks")

    # Cria runner
    vlm = VLMClient(model=model)
    runner = VLMBenchmarkRunner(vlm, model)

    # Health check
    healthy = await vlm.health_check()
    if not healthy:
        log.error(f"[runner] Modelo {model} indisponível no Ollama")
        await vlm.close()
        return

    try:
        await runner.run_all_tasks(tasks)
        summary = runner.summarize()

        # Salva resultados
        results_path = REPORTS_DIR / f"results_{model.replace(':', '_')}.json"
        results_data = [r.to_dict() for r in runner.results]
        save_results(results_data, results_path)

        # Salva summary
        summary_path = REPORTS_DIR / f"summary_{model.replace(':', '_')}.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with summary_path.open("w") as f:
            json.dump(summary, f, indent=2)

        log.info(f"[runner] Resultados salvos em {results_path}")
        log.info(f"[runner] Summary: {json.dumps(summary, indent=2)}")

    finally:
        await vlm.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    )

    import argparse

    parser = argparse.ArgumentParser(description="Vision 2.0 Benchmark Runner")
    parser.add_argument("--model", type=str, help="VLM model name (ex: qwen3.5:4b)")
    parser.add_argument(
        "--all-models",
        action="store_true",
        help="Run benchmark on all candidate models",
    )
    parser.add_argument(
        "--limit", type=int, help="Max tasks per category (for smoke tests)"
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        choices=["ocr", "grounding", "description", "afk"],
        help="Filter by task categories",
    )

    args = parser.parse_args()

    if args.all_models:
        models = MODELS_TO_BENCHMARK
    elif args.model:
        models = [args.model]
    else:
        parser.print_help()
        sys.exit(1)

    for model in models:
        log.info(f"\n{'=' * 60}")
        log.info(f"Starting benchmark for {model}")
        log.info(f"{'=' * 60}\n")
        asyncio.run(
            run_benchmark(model, limit=args.limit, categories=args.categories)
        )
