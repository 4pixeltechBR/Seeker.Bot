# Vision 2.0 — Benchmark Comparison Report

**Data:** 2026-04-15T13:29:41.765953
**Dataset:** 150 tasks (OCR + Grounding + Description + AFK)

## Executive Summary

- Best OCR: Qwen3-VL:8b (87.3%)
- Best Grounding: Qwen3-VL:8b (0.76 IoU)
- Best Latency: Qwen3.5:4b (2450ms P50)

## Detailed Comparison

| Metric | Threshold | Qwen3.5:4b | Qwen2.5-VL:7b | Qwen3-VL:8b | MiniCPM-V:2.6 |
|--------|-----------|-------|-------|-------|-------|-------|
| OCR Exact Match | >= 85% | 72.5% FAIL | 84.2% FAIL | **87.3%** PASS | **85.8%** PASS |
| Grounding IoU | >= 0.7 | 0.68 FAIL | **0.72** PASS | **0.76** PASS | **0.71** PASS |
| JSON Validity | >= 95% | 89% FAIL | 93% FAIL | **95%** PASS | 92% FAIL |
| Latency P50 | <= 5000ms | **2450ms** PASS | **3100ms** PASS | **3800ms** PASS | **2800ms** PASS |
| VRAM Peak | <= 10GB | **4.2GB** PASS | **6.8GB** PASS | **8.5GB** PASS | **6.2GB** PASS |

## Recommendation

[RECOMMENDED] Qwen3-VL:8b (5/5 criteria met)

## Next Steps

1. Deploy Qwen3-VL:8b as primary model
2. Configure Gemini 2.5 Flash as fallback
3. Update .env.example with VLM_MODEL
4. Validate in staging for 1 cycle
