# Vision 2.0 Benchmark Report
**Data:** 1775817262.058621
## Comparação de Modelos

| Métrica | qwen3.5:4b | qwen3-vl:8b |
|---|---|---|
| **Latência P50 (s)** | 125.75s | 179.88s |
| **OCR Exact Match (%)** | 100.0% | 50.0% |
| **OCR Levenshtein Sim** | 1.000 | 0.981 |
| **Grounding IoU (mean)** | 0.000 | 0.000 |
| **Grounding Center Error (px)** | 769.9 | 769.9 |
| **JSON Validity (%)** | 0.0% | 0.0% |

## qwen3.5:4b
**Total Tasks:** 8

### OCR
- **Count:** 2
- **Latency:** mean=25247.3ms, min=16966.8ms, max=33527.7ms
- **OCR Exact Match:** 100.0%
- **OCR Levenshtein:** 1.000

### GROUNDING
- **Count:** 2
- **Latency:** mean=300206.1ms, min=300139.7ms, max=300272.4ms
- **Grounding IoU:** 0.000
- **Grounding Center Error:** 769.9px
- **JSON Validity:** 0.0%

### DESCRIPTION
- **Count:** 2
- **Latency:** mean=161762.6ms, min=102887.8ms, max=220637.5ms
- **Keyword Coverage:** 0.8%

### AFK
- **Count:** 2
- **Latency:** mean=15777.0ms, min=14079.3ms, max=17474.7ms

## qwen3-vl:8b
**Total Tasks:** 9

### OCR
- **Count:** 2
- **Latency:** mean=189845.0ms, min=93548.9ms, max=286141.1ms
- **OCR Exact Match:** 50.0%
- **OCR Levenshtein:** 0.981

### GROUNDING
- **Count:** 2
- **Latency:** mean=300141.1ms, min=300016.4ms, max=300265.9ms
- **Grounding IoU:** 0.000
- **Grounding Center Error:** 769.9px
- **JSON Validity:** 0.0%

### DESCRIPTION
- **Count:** 2
- **Latency:** mean=198838.9ms, min=169906.5ms, max=227771.4ms
- **Keyword Coverage:** 0.8%

### AFK
- **Count:** 3
- **Latency:** mean=30682.0ms, min=16982.2ms, max=54618.8ms
