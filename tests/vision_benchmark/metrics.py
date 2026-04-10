"""
Vision 2.0 Benchmark — Métricas de avaliação.

Implementações simples e dependência-zero (stdlib only) para rodar
o benchmark sem precisar instalar libs pesadas (nltk, scipy, etc).
"""

import json
import re
import statistics
from dataclasses import dataclass


# ── OCR Metrics ───────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    """Normaliza texto para comparação: lowercase, remove espaços extras."""
    return re.sub(r"\s+", " ", text.strip().lower())


def ocr_exact_match(predicted: str, expected: str) -> bool:
    """Exact-match (normalizado) entre texto predito e esperado."""
    return _normalize_text(predicted) == _normalize_text(expected)


def _levenshtein(a: str, b: str) -> int:
    """Distância de Levenshtein (stdlib only, sem deps)."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)
    previous_row = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        current_row = [i + 1]
        for j, cb in enumerate(b):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (ca != cb)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def ocr_levenshtein_similarity(predicted: str, expected: str) -> float:
    """
    Similaridade de Levenshtein normalizada (0.0 a 1.0).
    1.0 = textos idênticos; 0.0 = totalmente diferentes.
    """
    pred = _normalize_text(predicted)
    exp = _normalize_text(expected)
    if not exp and not pred:
        return 1.0
    max_len = max(len(pred), len(exp))
    if max_len == 0:
        return 1.0
    distance = _levenshtein(pred, exp)
    return 1.0 - (distance / max_len)


def ocr_word_overlap(predicted: str, expected: str) -> float:
    """
    Proporção de palavras do expected que aparecem no predicted.
    Útil quando ordem não importa (ex: OCR pode reorder).
    """
    pred_words = set(_normalize_text(predicted).split())
    exp_words = set(_normalize_text(expected).split())
    if not exp_words:
        return 1.0
    return len(pred_words & exp_words) / len(exp_words)


# ── Grounding Metrics ─────────────────────────────────────────

def grounding_iou(
    predicted_bbox: dict,
    expected_bbox: dict,
) -> float:
    """
    IoU entre dois bounding boxes.

    Formato esperado: {"x": cx, "y": cy, "width": w, "height": h}
    OU                {"x1": ..., "y1": ..., "x2": ..., "y2": ...}

    Aceita também pontos (x, y sem width/height) tratados como bbox 20x20.
    """
    def to_xyxy(bbox: dict) -> tuple[float, float, float, float]:
        if "x1" in bbox and "y1" in bbox and "x2" in bbox and "y2" in bbox:
            return bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
        cx = float(bbox.get("x", 0))
        cy = float(bbox.get("y", 0))
        w = float(bbox.get("width", 20))
        h = float(bbox.get("height", 20))
        return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2

    try:
        px1, py1, px2, py2 = to_xyxy(predicted_bbox)
        ex1, ey1, ex2, ey2 = to_xyxy(expected_bbox)
    except (KeyError, TypeError, ValueError):
        return 0.0

    ix1 = max(px1, ex1)
    iy1 = max(py1, ey1)
    ix2 = min(px2, ex2)
    iy2 = min(py2, ey2)

    if ix2 < ix1 or iy2 < iy1:
        return 0.0

    intersection = (ix2 - ix1) * (iy2 - iy1)
    p_area = max(0.0, (px2 - px1) * (py2 - py1))
    e_area = max(0.0, (ex2 - ex1) * (ey2 - ey1))
    union = p_area + e_area - intersection

    if union <= 0:
        return 0.0
    return intersection / union


def grounding_center_error(
    predicted_bbox: dict,
    expected_bbox: dict,
) -> float:
    """
    Erro euclidiano entre centros (em pixels).
    Menor é melhor. Retorna inf se inputs inválidos.
    """
    try:
        px = float(predicted_bbox.get("x", 0))
        py = float(predicted_bbox.get("y", 0))
        ex = float(expected_bbox.get("x", 0))
        ey = float(expected_bbox.get("y", 0))
    except (TypeError, ValueError):
        return float("inf")

    return ((px - ex) ** 2 + (py - ey) ** 2) ** 0.5


# ── Description Metrics ──────────────────────────────────────

def description_keyword_coverage(
    predicted: str,
    expected_keywords: list[str],
) -> float:
    """
    Fração de palavras-chave esperadas presentes na descrição predita.
    """
    if not expected_keywords:
        return 1.0
    pred_lower = _normalize_text(predicted)
    hits = sum(1 for kw in expected_keywords if _normalize_text(kw) in pred_lower)
    return hits / len(expected_keywords)


# ── JSON Validity ────────────────────────────────────────────

def is_valid_json(text: str) -> bool:
    """Verifica se o texto contém um JSON válido (stripando markdown fences)."""
    clean = text.strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    clean = clean.strip()

    try:
        json.loads(clean)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def json_validity_rate(predictions: list[str]) -> float:
    """Fração de respostas que são JSON válido."""
    if not predictions:
        return 0.0
    valid = sum(1 for p in predictions if is_valid_json(p))
    return valid / len(predictions)


# ── Latency Stats ────────────────────────────────────────────

@dataclass
class LatencyStats:
    """Estatísticas de latência em segundos."""
    count: int
    mean: float
    median: float
    p50: float
    p95: float
    p99: float
    min: float
    max: float
    stdev: float


def latency_stats(latencies_ms: list[float]) -> LatencyStats:
    """
    Calcula estatísticas de latência a partir de lista de valores em ms.
    Retorna LatencyStats em segundos.
    """
    if not latencies_ms:
        return LatencyStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    sorted_s = sorted(l / 1000.0 for l in latencies_ms)
    n = len(sorted_s)

    def pct(p: float) -> float:
        idx = max(0, min(n - 1, int(round((p / 100.0) * (n - 1)))))
        return sorted_s[idx]

    return LatencyStats(
        count=n,
        mean=statistics.mean(sorted_s),
        median=statistics.median(sorted_s),
        p50=pct(50),
        p95=pct(95),
        p99=pct(99),
        min=sorted_s[0],
        max=sorted_s[-1],
        stdev=statistics.stdev(sorted_s) if n > 1 else 0.0,
    )
