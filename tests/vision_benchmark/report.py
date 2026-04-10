"""
Vision 2.0 Benchmark — Report generator.

Lê resultados de benchmark salvos (.json) e gera relatório
comparativo em markdown.

Uso:
    python -m tests.vision_benchmark.report
    python -m tests.vision_benchmark.report --models qwen3.5:4b qwen3-vl:8b
"""

import json
import logging
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger("seeker.vision.benchmark.report")

REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"


def load_summary(model: str, reports_dir: Path = REPORTS_DIR) -> Optional[dict]:
    """Carrega summary de um modelo salvo."""
    summary_path = reports_dir / f"summary_{model.replace(':', '_')}.json"
    if not summary_path.exists():
        log.warning(f"Summary não encontrado: {summary_path}")
        return None

    with summary_path.open("r") as f:
        return json.load(f)


def generate_comparison_table(models: list[str]) -> str:
    """Gera tabela markdown comparativa de modelos."""
    summaries = {}
    for model in models:
        s = load_summary(model)
        if s:
            summaries[model] = s

    if not summaries:
        return "Nenhum resultado encontrado."

    lines = [
        "## Comparação de Modelos\n",
        "| Métrica | " + " | ".join(summaries.keys()) + " |",
        "|---|" + "|".join(["---"] * len(summaries)) + "|",
    ]

    # Latência geral
    lines.append("| **Latência P50 (s)** |", )
    for model in summaries.keys():
        s = summaries[model]
        latencies = []
        for cat, cat_data in s.get("by_category", {}).items():
            if "latency_ms" in cat_data:
                latencies.append(cat_data["latency_ms"].get("mean", 0))
        avg_lat = sum(latencies) / len(latencies) / 1000 if latencies else 0
        lines[-1] += f" {avg_lat:.2f}s |"

    # OCR Exact Match %
    lines.append("| **OCR Exact Match (%)** |", )
    for model in summaries.keys():
        s = summaries[model]
        ocr_data = s.get("by_category", {}).get("ocr", {})
        exact = ocr_data.get("ocr_exact_match_%", 0)
        lines[-1] += f" {exact:.1f}% |"

    # OCR Levenshtein
    lines.append("| **OCR Levenshtein Sim** |", )
    for model in summaries.keys():
        s = summaries[model]
        ocr_data = s.get("by_category", {}).get("ocr", {})
        lev = ocr_data.get("ocr_levenshtein_mean", 0)
        lines[-1] += f" {lev:.3f} |"

    # Grounding IoU
    lines.append("| **Grounding IoU (mean)** |", )
    for model in summaries.keys():
        s = summaries[model]
        ground_data = s.get("by_category", {}).get("grounding", {})
        iou = ground_data.get("grounding_iou_mean", 0)
        lines[-1] += f" {iou:.3f} |"

    # Grounding Center Error
    lines.append("| **Grounding Center Error (px)** |", )
    for model in summaries.keys():
        s = summaries[model]
        ground_data = s.get("by_category", {}).get("grounding", {})
        err = ground_data.get("grounding_center_error_mean_px", 0)
        lines[-1] += f" {err:.1f} |"

    # JSON Validity
    lines.append("| **JSON Validity (%)** |", )
    for model in summaries.keys():
        s = summaries[model]
        ground_data = s.get("by_category", {}).get("grounding", {})
        valid = ground_data.get("json_valid_%", 0)
        lines[-1] += f" {valid:.1f}% |"

    return "\n".join(lines) + "\n"


def generate_full_report(models: list[str]) -> str:
    """Gera relatório completo em markdown."""
    report = [
        "# Vision 2.0 Benchmark Report\n",
        f"**Data:** {list(load_summary(models[0]).values())[0].get('timestamp', 'N/A')}\n",
    ]

    # Tabela comparativa
    report.append(generate_comparison_table(models))

    # Detalhes por modelo
    for model in models:
        s = load_summary(model)
        if not s:
            continue

        report.append(f"\n## {model}\n")
        report.append(f"**Total Tasks:** {s.get('total_tasks', 0)}\n")

        for cat, cat_data in s.get("by_category", {}).items():
            report.append(f"\n### {cat.upper()}\n")
            report.append(f"- **Count:** {cat_data.get('count', 0)}\n")

            if "latency_ms" in cat_data:
                lat = cat_data["latency_ms"]
                report.append(
                    f"- **Latency:** mean={lat.get('mean', 0):.1f}ms, "
                    f"min={lat.get('min', 0):.1f}ms, max={lat.get('max', 0):.1f}ms\n"
                )

            if "ocr_exact_match_%" in cat_data:
                report.append(
                    f"- **OCR Exact Match:** {cat_data['ocr_exact_match_%']:.1f}%\n"
                )
            if "ocr_levenshtein_mean" in cat_data:
                report.append(
                    f"- **OCR Levenshtein:** {cat_data['ocr_levenshtein_mean']:.3f}\n"
                )

            if "grounding_iou_mean" in cat_data:
                report.append(
                    f"- **Grounding IoU:** {cat_data['grounding_iou_mean']:.3f}\n"
                )
            if "grounding_center_error_mean_px" in cat_data:
                report.append(
                    f"- **Grounding Center Error:** {cat_data['grounding_center_error_mean_px']:.1f}px\n"
                )
            if "json_valid_%" in cat_data:
                report.append(f"- **JSON Validity:** {cat_data['json_valid_%']:.1f}%\n")

            if "keywords_coverage_mean" in cat_data:
                report.append(
                    f"- **Keyword Coverage:** {cat_data['keywords_coverage_mean']:.1f}%\n"
                )

    return "".join(report)


def save_report(models: list[str], output_path: Path = REPORTS_DIR / "vision_2_0_comparison.md"):
    """Gera e salva relatório em markdown."""
    report = generate_full_report(models)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(report)
    log.info(f"Relatório salvo em {output_path}")
    print(report)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    )

    import argparse

    parser = argparse.ArgumentParser(description="Vision 2.0 Benchmark Report Generator")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["qwen3.5:4b", "qwen2.5vl:7b", "qwen3-vl:8b", "minicpm-v"],
        help="Models to compare",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPORTS_DIR / "vision_2_0_comparison.md",
        help="Output markdown file",
    )

    args = parser.parse_args()
    save_report(args.models, args.output)
