"""
Vision Benchmark Mock Runner — Testa arquitetura sem downloads/LLM reais

Simula execução de benchmark contra múltiplos modelos usando dados mockados.
Útil para validar pipeline antes de rodar benchmarks reais (que levam 2-3h).
"""

import asyncio
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

log = logging.getLogger("vision.benchmark.mock")


@dataclass
class MockModelResult:
    """Resultado simulado para um modelo."""
    model_name: str
    ocr_exact_match_pct: float
    ocr_levenshtein_avg: float
    grounding_iou_avg: float
    grounding_json_validity_pct: float
    description_keyword_coverage_pct: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    vram_peak_gb: float
    overall_confidence: float


class MockBenchmarkRunner:
    """Simula VLMBenchmarkRunner com resultados fake."""

    # Mock results para cada modelo (baseado em research teórico)
    MODEL_MOCK_RESULTS = {
        "qwen3.5:4b": MockModelResult(
            model_name="Qwen3.5:4b",
            ocr_exact_match_pct=72.5,
            ocr_levenshtein_avg=0.78,
            grounding_iou_avg=0.68,
            grounding_json_validity_pct=89.0,
            description_keyword_coverage_pct=81.0,
            latency_p50_ms=2450.0,
            latency_p95_ms=3200.0,
            latency_p99_ms=4100.0,
            vram_peak_gb=4.2,
            overall_confidence=0.75,
        ),
        "qwen2.5vl:7b": MockModelResult(
            model_name="Qwen2.5-VL:7b",
            ocr_exact_match_pct=84.2,
            ocr_levenshtein_avg=0.87,
            grounding_iou_avg=0.72,
            grounding_json_validity_pct=93.0,
            description_keyword_coverage_pct=86.5,
            latency_p50_ms=3100.0,
            latency_p95_ms=4200.0,
            latency_p99_ms=5300.0,
            vram_peak_gb=6.8,
            overall_confidence=0.84,
        ),
        "qwen3-vl:8b": MockModelResult(
            model_name="Qwen3-VL:8b",
            ocr_exact_match_pct=87.3,
            ocr_levenshtein_avg=0.89,
            grounding_iou_avg=0.76,
            grounding_json_validity_pct=95.0,
            description_keyword_coverage_pct=89.0,
            latency_p50_ms=3800.0,
            latency_p95_ms=5100.0,
            latency_p99_ms=6400.0,
            vram_peak_gb=8.5,
            overall_confidence=0.87,
        ),
        "minicpm-v": MockModelResult(
            model_name="MiniCPM-V:2.6",
            ocr_exact_match_pct=85.8,
            ocr_levenshtein_avg=0.88,
            grounding_iou_avg=0.71,
            grounding_json_validity_pct=92.0,
            description_keyword_coverage_pct=85.0,
            latency_p50_ms=2800.0,
            latency_p95_ms=3900.0,
            latency_p99_ms=5000.0,
            vram_peak_gb=6.2,
            overall_confidence=0.85,
        ),
    }

    async def run_benchmark(self, model_names: List[str], output_path: str = "reports/") -> Dict:
        """
        Simula benchmark run contra múltiplos modelos.

        Args:
            model_names: Lista de modelos a testar
            output_path: Diretório para salvar resultados JSON

        Returns:
            Dict com resultados agregados
        """
        log.info(f"[mock_benchmark] Iniciando mock benchmark para {len(model_names)} modelos...")

        results = {}
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        for model_name in model_names:
            log.info(f"[mock_benchmark] Simulando teste para {model_name}...")

            if model_name not in self.MODEL_MOCK_RESULTS:
                log.warning(f"Modelo {model_name} não está em mock results, usando default")
                mock_result = self.MODEL_MOCK_RESULTS["qwen3.5:4b"]
            else:
                mock_result = self.MODEL_MOCK_RESULTS[model_name]

            # Salvar resultado em JSON
            output_file = output_dir / f"{model_name.replace(':', '_')}.json"
            with open(output_file, 'w') as f:
                json.dump(asdict(mock_result), f, indent=2)

            results[model_name] = asdict(mock_result)
            log.info(f"✅ {model_name}: OCR={mock_result.ocr_exact_match_pct:.1f}%, IoU={mock_result.grounding_iou_avg:.2f}, P50={mock_result.latency_p50_ms:.0f}ms")

        return results

    def generate_comparison_report(
        self,
        model_results: Dict,
        output_path: str = "reports/vision_2_0_comparison.md"
    ) -> str:
        """
        Gera relatório markdown comparando modelos.

        Args:
            model_results: Dict com resultados de cada modelo
            output_path: Caminho para salvar relatório

        Returns:
            Markdown report como string
        """
        log.info("[mock_benchmark] Gerando relatório comparativo...")

        # Thresholds de aprovação
        THRESHOLDS = {
            "ocr_exact_match_pct": 85,
            "grounding_iou_avg": 0.70,
            "grounding_json_validity_pct": 95,
            "latency_p50_ms": 5000,
            "vram_peak_gb": 10,
        }

        # Header
        report = """# Vision 2.0 — Benchmark Comparison Report

**Data:** """ + datetime.utcnow().isoformat() + """
**Dataset:** 150 tasks (OCR + Grounding + Description + AFK)

## Executive Summary

"""

        # Resumo rápido
        best_ocr = max(model_results.values(), key=lambda x: x["ocr_exact_match_pct"])
        best_grounding = max(model_results.values(), key=lambda x: x["grounding_iou_avg"])
        best_latency = min(model_results.values(), key=lambda x: x["latency_p50_ms"])

        report += f"- Best OCR: {best_ocr['model_name']} ({best_ocr['ocr_exact_match_pct']:.1f}%)\n"
        report += f"- Best Grounding: {best_grounding['model_name']} ({best_grounding['grounding_iou_avg']:.2f} IoU)\n"
        report += f"- Best Latency: {best_latency['model_name']} ({best_latency['latency_p50_ms']:.0f}ms P50)\n\n"

        # Tabela de comparação
        report += "## Detailed Comparison\n\n"
        report += "| Metric | Threshold | " + " | ".join([m["model_name"] for m in model_results.values()]) + " |\n"
        report += "|--------|-----------|" + "|".join(["-------"] * (len(model_results) + 1)) + "|\n"

        # OCR
        ocr_threshold = THRESHOLDS["ocr_exact_match_pct"]
        report += f"| OCR Exact Match | >= {ocr_threshold}% | " + " | ".join([
            f"**{m['ocr_exact_match_pct']:.1f}%** PASS" if m['ocr_exact_match_pct'] >= ocr_threshold
            else f"{m['ocr_exact_match_pct']:.1f}% FAIL"
            for m in model_results.values()
        ]) + " |\n"

        # Grounding IoU
        iou_threshold = THRESHOLDS["grounding_iou_avg"]
        report += f"| Grounding IoU | >= {iou_threshold} | " + " | ".join([
            f"**{m['grounding_iou_avg']:.2f}** PASS" if m['grounding_iou_avg'] >= iou_threshold
            else f"{m['grounding_iou_avg']:.2f} FAIL"
            for m in model_results.values()
        ]) + " |\n"

        # JSON Validity
        json_threshold = THRESHOLDS["grounding_json_validity_pct"]
        report += f"| JSON Validity | >= {json_threshold}% | " + " | ".join([
            f"**{m['grounding_json_validity_pct']:.0f}%** PASS" if m['grounding_json_validity_pct'] >= json_threshold
            else f"{m['grounding_json_validity_pct']:.0f}% FAIL"
            for m in model_results.values()
        ]) + " |\n"

        # Latency P50
        latency_threshold = THRESHOLDS["latency_p50_ms"]
        report += f"| Latency P50 | <= {latency_threshold}ms | " + " | ".join([
            f"**{m['latency_p50_ms']:.0f}ms** PASS" if m['latency_p50_ms'] <= latency_threshold
            else f"{m['latency_p50_ms']:.0f}ms FAIL"
            for m in model_results.values()
        ]) + " |\n"

        # VRAM
        vram_threshold = THRESHOLDS["vram_peak_gb"]
        report += f"| VRAM Peak | <= {vram_threshold}GB | " + " | ".join([
            f"**{m['vram_peak_gb']:.1f}GB** PASS" if m['vram_peak_gb'] <= vram_threshold
            else f"{m['vram_peak_gb']:.1f}GB FAIL"
            for m in model_results.values()
        ]) + " |\n"

        # Recommendation
        report += "\n## Recommendation\n\n"

        # Count passes
        passes = {}
        for model_name, metrics in model_results.items():
            passes[model_name] = 0
            if metrics['ocr_exact_match_pct'] >= ocr_threshold:
                passes[model_name] += 1
            if metrics['grounding_iou_avg'] >= iou_threshold:
                passes[model_name] += 1
            if metrics['grounding_json_validity_pct'] >= json_threshold:
                passes[model_name] += 1
            if metrics['latency_p50_ms'] <= latency_threshold:
                passes[model_name] += 1
            if metrics['vram_peak_gb'] <= vram_threshold:
                passes[model_name] += 1

        best_model = max(passes, key=passes.get)
        report += f"[RECOMMENDED] {model_results[best_model]['model_name']} ({passes[best_model]}/5 criteria met)\n\n"

        # Actions
        report += "## Next Steps\n\n"
        report += f"1. Deploy {model_results[best_model]['model_name']} as primary model\n"
        report += "2. Configure Gemini 2.5 Flash as fallback\n"
        report += "3. Update .env.example with VLM_MODEL\n"
        report += "4. Validate in staging for 1 cycle\n"

        # Salvar relatório
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)

        log.info(f"✅ Relatório salvo em {output_path}")
        return report


async def main():
    """Entry point para mock benchmark."""
    runner = MockBenchmarkRunner()

    # Simular benchmark
    models = ["qwen3.5:4b", "qwen2.5vl:7b", "qwen3-vl:8b", "minicpm-v"]
    results = await runner.run_benchmark(models, output_path="reports/")

    # Gerar relatório
    report = runner.generate_comparison_report(results, output_path="reports/vision_2_0_comparison.md")
    print(report)

    print("\n[SUCCESS] Mock benchmark completed!")
    print("Results saved in: reports/")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
