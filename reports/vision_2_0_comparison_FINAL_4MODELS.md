# Vision 2.0 Benchmark Report
**Data:** 1775831246.9303148
## Comparação de Modelos

| Métrica | qwen3.5:4b | qwen3-vl:8b | qwen2.5vl:7b | minicpm-v |
|---|---|---|---|---|
| **Latência P50 (s)** | 207.99s | 203.44s | 195.25s | 4.58s |
| **OCR Exact Match (%)** | 100.0% | 0.0% | 0.0% | 0.0% |
| **OCR Levenshtein Sim** | 1.000 | 0.165 | 0.157 | 0.454 |
| **Grounding IoU (mean)** | 0.000 | 0.000 | 0.000 | 0.000 |
| **Grounding Center Error (px)** | 769.9 | 769.9 | 769.9 | 769.9 |
| **JSON Validity (%)** | 0.0% | 0.0% | 0.0% | 0.0% |

## qwen3.5:4b
**Total Tasks:** 9

### OCR
- **Count:** 2
- **Latency:** mean=182147.2ms, min=152396.1ms, max=211898.2ms
- **OCR Exact Match:** 100.0%
- **OCR Levenshtein:** 1.000

### GROUNDING
- **Count:** 2
- **Latency:** mean=300140.0ms, min=300013.1ms, max=300266.9ms
- **Grounding IoU:** 0.000
- **Grounding Center Error:** 769.9px
- **JSON Validity:** 0.0%

### DESCRIPTION
- **Count:** 2
- **Latency:** mean=300276.6ms, min=300274.1ms, max=300279.0ms
- **Keyword Coverage:** 0.0%

### AFK
- **Count:** 3
- **Latency:** mean=49396.5ms, min=43554.6ms, max=54640.3ms

## qwen3-vl:8b
**Total Tasks:** 9

### OCR
- **Count:** 2
- **Latency:** mean=169909.4ms, min=39797.6ms, max=300021.1ms
- **OCR Exact Match:** 0.0%
- **OCR Levenshtein:** 0.165

### GROUNDING
- **Count:** 2
- **Latency:** mean=300167.3ms, min=300037.1ms, max=300297.4ms
- **Grounding IoU:** 0.000
- **Grounding Center Error:** 769.9px
- **JSON Validity:** 0.0%

### DESCRIPTION
- **Count:** 2
- **Latency:** mean=300281.9ms, min=300280.1ms, max=300283.7ms
- **Keyword Coverage:** 0.0%

### AFK
- **Count:** 3
- **Latency:** mean=43381.8ms, min=36402.1ms, max=52492.6ms

## qwen2.5vl:7b
**Total Tasks:** 9

### OCR
- **Count:** 2
- **Latency:** mean=300138.3ms, min=300012.5ms, max=300264.0ms
- **OCR Exact Match:** 0.0%
- **OCR Levenshtein:** 0.157

### GROUNDING
- **Count:** 2
- **Latency:** mean=300286.4ms, min=300276.8ms, max=300296.1ms
- **Grounding IoU:** 0.000
- **Grounding Center Error:** 769.9px
- **JSON Validity:** 0.0%

### DESCRIPTION
- **Count:** 2
- **Latency:** mean=154968.1ms, min=30750.3ms, max=279185.9ms
- **Keyword Coverage:** 0.3%

### AFK
- **Count:** 3
- **Latency:** mean=25588.0ms, min=25469.8ms, max=25693.0ms

## minicpm-v
**Total Tasks:** 9

### OCR
- **Count:** 2
- **Latency:** mean=11944.8ms, min=979.2ms, max=22910.3ms
- **OCR Exact Match:** 0.0%
- **OCR Levenshtein:** 0.454

### GROUNDING
- **Count:** 2
- **Latency:** mean=2419.9ms, min=1919.2ms, max=2920.5ms
- **Grounding IoU:** 0.000
- **Grounding Center Error:** 769.9px
- **JSON Validity:** 0.0%

### DESCRIPTION
- **Count:** 2
- **Latency:** mean=1850.5ms, min=1717.4ms, max=1983.7ms
- **Keyword Coverage:** 0.3%

### AFK
- **Count:** 3
- **Latency:** mean=2113.3ms, min=1725.6ms, max=2585.9ms
