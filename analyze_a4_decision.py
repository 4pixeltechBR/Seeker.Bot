#!/usr/bin/env python3
"""
Vision 2.0 Phase A4: Decision Analysis
Carrega resultados do benchmark e determina qual cenário da árvore de decisão aplicar.
"""

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class Thresholds:
    """Hard thresholds para aprovação de modelo"""
    ocr_exact_match: float = 85.0  # %
    grounding_iou: float = 0.70  # média
    json_validity: float = 95.0  # %
    latency_grounding: float = 5000.0  # ms (P50)


@dataclass
class ModelResult:
    """Resultado agregado de um modelo"""
    model: str
    ocr_exact_match: Optional[float]
    grounding_iou: Optional[float]
    json_validity: Optional[float]
    latency_grounding_ms: Optional[float]
    keywords_coverage: Optional[float]

    def passes_all_thresholds(self, thresholds: Thresholds) -> bool:
        """Verifica se modelo passa em TODOS os critérios"""
        checks = [
            self.ocr_exact_match is not None and self.ocr_exact_match >= thresholds.ocr_exact_match,
            self.grounding_iou is not None and self.grounding_iou >= thresholds.grounding_iou,
            self.json_validity is not None and self.json_validity >= thresholds.json_validity,
            self.latency_grounding_ms is not None and self.latency_grounding_ms <= thresholds.latency_grounding,
        ]
        return all(checks)

    def passes_by_category(self, thresholds: Thresholds) -> Dict[str, bool]:
        """Retorna quais categorias o modelo passa"""
        return {
            "ocr": self.ocr_exact_match is not None and self.ocr_exact_match >= thresholds.ocr_exact_match,
            "grounding_iou": self.grounding_iou is not None and self.grounding_iou >= thresholds.grounding_iou,
            "grounding_json": self.json_validity is not None and self.json_validity >= thresholds.json_validity,
            "grounding_latency": self.latency_grounding_ms is not None and self.latency_grounding_ms <= thresholds.latency_grounding,
        }


def load_summary(model_name: str, reports_dir: Path = Path("reports")) -> Optional[Dict]:
    """Carrega summary JSON de um modelo"""
    # Trata diferentes formatos de nome
    slug1 = model_name.replace(":", "_")
    slug2 = model_name.replace(":", "").replace(".", "").lower()

    for slug in [slug1, slug2]:
        summary_path = reports_dir / f"summary_{slug}.json"
        if summary_path.exists():
            with open(summary_path) as f:
                return json.load(f)

    return None


def extract_model_result(model_name: str, summary: Dict) -> ModelResult:
    """Extrai métricas relevantes do summary JSON"""
    by_cat = summary.get("by_category", {})

    ocr_data = by_cat.get("ocr", {})
    ground_data = by_cat.get("grounding", {})
    desc_data = by_cat.get("description", {})

    return ModelResult(
        model=model_name,
        ocr_exact_match=ocr_data.get("ocr_exact_match_%"),
        grounding_iou=ground_data.get("grounding_iou_mean"),
        json_validity=ground_data.get("json_valid_%"),
        latency_grounding_ms=ground_data.get("latency_ms", {}).get("mean"),
        keywords_coverage=desc_data.get("keywords_coverage_mean"),
    )


def print_results_table(results: Dict[str, ModelResult], thresholds: Thresholds):
    """Imprime tabela formatada de resultados"""
    print("\n" + "=" * 100)
    print("ANÁLISE DE CRITERIOS - FASE A4")
    print("=" * 100 + "\n")

    print(f"{'Modelo':<20} {'OCR':<10} {'IoU':<10} {'JSON':<10} {'Latência':<12} {'Passa?':<10}")
    print("-" * 100)

    for model_name, result in results.items():
        ocr_str = f"{result.ocr_exact_match:.1f}%" if result.ocr_exact_match else "N/A"
        iou_str = f"{result.grounding_iou:.2f}" if result.grounding_iou else "N/A"
        json_str = f"{result.json_validity:.1f}%" if result.json_validity else "N/A"
        lat_str = f"{result.latency_grounding_ms/1000:.1f}s" if result.latency_grounding_ms else "N/A"

        passes = "[OK] SIM" if result.passes_all_thresholds(thresholds) else "[FAIL] NAO"

        print(f"{model_name:<20} {ocr_str:<10} {iou_str:<10} {json_str:<10} {lat_str:<12} {passes:<10}")

    print("-" * 100)
    print(f"Thresholds: OCR>={thresholds.ocr_exact_match:.0f}% | IoU>={thresholds.grounding_iou:.2f} | JSON>={thresholds.json_validity:.0f}% | Latencia<={thresholds.latency_grounding/1000:.1f}s\n")


def determine_scenario(results: Dict[str, ModelResult], thresholds: Thresholds) -> str:
    """Determina qual cenário da árvore de decisão estamos"""

    winners = {m: r for m, r in results.items() if r.passes_all_thresholds(thresholds)}

    if len(winners) == 1:
        winner = list(winners.keys())[0]
        return f"CENÁRIO 1: Um modelo vence — {winner}"
    elif len(winners) > 1:
        # Multiple winners - pick fastest
        fastest = min(winners.items(), key=lambda x: x[1].latency_grounding_ms or float('inf'))
        return f"CENÁRIO 1+: Múltiplos vencedores, mais rápido: {fastest[0]}"

    # Nenhum passa em tudo - verifica se há especialistas em categorias diferentes
    category_winners = {cat: {} for cat in ["ocr", "grounding_iou", "grounding_json", "grounding_latency"]}

    for model_name, result in results.items():
        passes = result.passes_by_category(thresholds)
        for cat, passed in passes.items():
            if passed:
                if model_name not in category_winners[cat]:
                    category_winners[cat][model_name] = result

    hybrid_candidates = [cat for cat, winners in category_winners.items() if len(winners) > 0 and len(winners) < len(results)]

    if hybrid_candidates:
        return f"CENÁRIO 2: Arquitetura Híbrida — diferentes modelos vencedores por categoria"
    else:
        return f"CENÁRIO 3: Nenhum modelo passa — Cloud-first com Gemini 2.5 Flash necessário"


def main():
    models = ["qwen3.5:4b", "qwen2.5vl:7b", "qwen3-vl:8b", "minicpm-v"]
    thresholds = Thresholds()
    reports_dir = Path("reports")

    print("\n[CARREGANDO] Summaries...")
    results = {}
    for model in models:
        summary = load_summary(model, reports_dir)
        if summary:
            result = extract_model_result(model, summary)
            results[model] = result
            print(f"  OK {model}")
        else:
            print(f"  WAIT {model} (ainda nao disponivel)")

    if not results:
        print("\n[ERRO] Nenhum resultado disponivel. Aguarde conclusao dos benchmarks.")
        return

    print_results_table(results, thresholds)
    scenario = determine_scenario(results, thresholds)
    print(f"[DECISAO] {scenario}\n")

    # Detalhes por categoria
    print("\n" + "=" * 100)
    print("ANALISE POR CATEGORIA")
    print("=" * 100)

    for model_name, result in results.items():
        passes = result.passes_by_category(thresholds)
        print(f"\n{model_name}:")
        print(f"  OCR >={thresholds.ocr_exact_match:.0f}%: {passes['ocr']} ({result.ocr_exact_match:.1f}%)")
        print(f"  Grounding IoU >={thresholds.grounding_iou:.2f}: {passes['grounding_iou']} ({result.grounding_iou:.2f})")
        print(f"  Grounding JSON >={thresholds.json_validity:.0f}%: {passes['grounding_json']} ({result.json_validity:.1f}%)")
        print(f"  Grounding Latencia <={thresholds.latency_grounding/1000:.1f}s: {passes['grounding_latency']} ({result.latency_grounding_ms/1000:.1f}s)")


if __name__ == "__main__":
    main()
