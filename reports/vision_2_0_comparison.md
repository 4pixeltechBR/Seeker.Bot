# Vision 2.0 Benchmark Report
**Data:** 1775831246.9303148
## Comparação de Modelos

| Métrica | qwen3.5:4b | qwen2.5vl:7b | qwen3-vl:8b | minicpm-v |
|---|---|---|---|---|
| **Latência P50 (s)** | 207.99s | 68.27s | 203.44s | 77.05s |
| **OCR Exact Match (%)** | 100.0% | 50.0% | 0.0% | 0.0% |
| **OCR Levenshtein Sim** | 1.000 | 0.574 | 0.165 | 0.232 |
| **Grounding IoU (mean)** | 0.000 | 0.000 | 0.000 | 0.000 |
| **Grounding Center Error (px)** | 769.9 | 637.9 | 769.9 | 769.9 |
| **JSON Validity (%)** | 0.0% | 50.0% | 0.0% | 0.0% |

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

## qwen2.5vl:7b
**Total Tasks:** 9

### OCR
- **Count:** 2
- **Latency:** mean=162154.6ms, min=24294.6ms, max=300014.7ms
- **OCR Exact Match:** 50.0%
- **OCR Levenshtein:** 0.574

### GROUNDING
- **Count:** 2
- **Latency:** mean=37913.7ms, min=32997.0ms, max=42830.5ms
- **Grounding IoU:** 0.000
- **Grounding Center Error:** 637.9px
- **JSON Validity:** 50.0%

### DESCRIPTION
- **Count:** 2
- **Latency:** mean=42721.9ms, min=42487.7ms, max=42956.0ms
- **Keyword Coverage:** 0.3%

### AFK
- **Count:** 3
- **Latency:** mean=30290.1ms, min=29683.4ms, max=30922.9ms

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

## minicpm-v
**Total Tasks:** 9

### OCR
- **Count:** 2
- **Latency:** mean=298681.0ms, min=297351.3ms, max=300010.7ms
- **OCR Exact Match:** 0.0%
- **OCR Levenshtein:** 0.232

### GROUNDING
- **Count:** 2
- **Latency:** mean=3827.8ms, min=3469.4ms, max=4186.1ms
- **Grounding IoU:** 0.000
- **Grounding Center Error:** 769.9px
- **JSON Validity:** 0.0%

### DESCRIPTION
- **Count:** 2
- **Latency:** mean=3148.5ms, min=2571.2ms, max=3725.7ms
- **Keyword Coverage:** 0.3%

### AFK
- **Count:** 3
- **Latency:** mean=2560.6ms, min=2467.1ms, max=2709.4ms
