"""Report Generation for Vision 2.0 Benchmark — Phase A2-A3"""
import json
from typing import Dict, List

def generate_markdown_report(results: Dict[str, Dict]) -> str:
    """
    Gera relatório markdown comparando modelos.
    
    Args:
        results: {model_name: {metrics}}
    
    Returns:
        Markdown string com tabela comparativa
    """
    report = """# Vision 2.0 — Benchmark Comparativo

## Resumo de Modelos Testados

| Modelo | OCR Acc | IoU Grounding | Latency P50 | VRAM Peak | Score Overall |
|--------|---------|---------------|-------------|-----------|---------------|
"""
    
    for model, metrics in sorted(results.items()):
        report += f"| {model} | {metrics.get('ocr_acc', 0):.1f}% | {metrics.get('iou', 0):.2f} | {metrics.get('latency_p50', 0):.0f}ms | {metrics.get('vram', 0):.1f}GB | {metrics.get('overall', 0):.2f} |\n"
    
    report += "\n## Detalhes por Modelo\n"
    for model, metrics in sorted(results.items()):
        report += f"\n### {model}\n"
        report += f"- OCR: {metrics.get('ocr_acc', 0):.1f}% exact match\n"
        report += f"- Grounding: IoU {metrics.get('iou', 0):.2f}\n"
        report += f"- Latency: {metrics.get('latency_p50', 0):.0f}ms (P50)\n"
        report += f"- VRAM Peak: {metrics.get('vram', 0):.1f}GB\n"
    
    return report

def save_report(report: str, path: str = "reports/vision_2_0_comparison.md"):
    """Salva relatório em arquivo markdown"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Relatório salvo em {path}")
