# Sprint 12 — Vision 2.0 VLM Upgrade

## Status: Fase A1-A2 ✅ COMPLETA | Fase A3-A4 🔄 EM ANDAMENTO

**Data de início:** 2026-04-10  
**Objetivo:** Avaliar e atualizar motor VLM multimodal (Qwen3.5-4B → candidatos) com benchmark objetivo.  
**Escopo reframeado:** VLM upgrade + benchmark (sem pytesseract/YOLO por enquanto).

---

## Fases Implementadas

### **Fase A1: Config Refactor** ✅ COMPLETA (1h)

**Objetivo:** Tornar modelo VLM configurável via env var sem editar código.

**Arquivos modificados:**
- `src/skills/vision/vlm_client.py:24-27` — modelo agora lê `os.getenv("VLM_MODEL", "qwen3.5:4b")`
- `src/skills/vision/vlm_client.py` — novo método `async set_model(name: str)` para hot-swap
- `.env.example` — adicionado `VLM_MODEL`, `GEMINI_VLM_FALLBACK`, `GEMINI_VLM_MODEL`

**Validação:**
```bash
# Env override funciona
VLM_MODEL=qwen2.5vl:7b python -c "from src.skills.vision.vlm_client import VLMClient; c = VLMClient(); print(c.model)"
# Output: qwen2.5vl:7b

# Hot-swap funciona
asyncio.run(vlm.set_model("qwen3-vl:8b"))  # Sem reinstanciar client
```

**Status:** Backward compatible (código existente continua funcionando).

---

### **Fase A2: Benchmark Harness** ✅ COMPLETA (3h)

**Objetivo:** Criar suite reutilizável de benchmarks para avaliar qualidade VLM.

**Arquivos criados:**

| Arquivo | Linhas | Propósito |
|---------|--------|----------|
| `tests/vision_benchmark/__init__.py` | 30 | Package exports |
| `tests/vision_benchmark/tasks.py` | 180 | `BenchmarkTask`, `TaskCategory`, `load_dataset()` |
| `tests/vision_benchmark/metrics.py` | 250 | Métricas (Levenshtein, IoU, JSON validity, latency) — stdlib only |
| `tests/vision_benchmark/runner.py` | 280 | `VLMBenchmarkRunner`, async orchestrator |
| `tests/vision_benchmark/report.py` | 150 | Gerador de tabelas markdown comparativas |
| `tests/vision_benchmark/test_vlm_benchmark.py` | 200 | Regression tests (pytest async) |
| `tests/vision_benchmark/dataset/` | — | 9 imagens placeholder + 4× labels.json |

**Categorias de tasks:**
- **OCR** (50 planned) — extração de texto exato
- **GROUNDING** (30 planned) — localização de elemento UI com bounding box
- **DESCRIPTION** (50 planned) — descrição geral de cena com palavras-chave
- **AFK** (20 planned) — detecção de estado (idle/active/modal/error)

**Métricas coletadas por modelo:**
- Latência: P50, P95, P99, mean (ms)
- OCR: exact-match %, Levenshtein similarity (0.0-1.0)
- Grounding: IoU médio (0.0-1.0), JSON validity %, center error (px)
- Description: keyword coverage %
- VRAM peak (via nvidia-smi)

**Dataset inicial (placeholder):**
- 9 imagens PNG simples (2 OCR, 2 grounding, 2 description, 3 AFK)
- labels.json por categoria com ground_truth
- **Nota:** Placeholder para validar pipeline. Dados reais (OCRBench, ScreenSpot-Pro) carregam em runtime.

**Status:** Framework pronto, dados mínimos validados.

---

### **Fase A3: Avaliar Candidatos** 🔄 EM ANDAMENTO (2.5h)

**Modelos a testar:**

| # | Modelo | VRAM | Status | Comando |
|-|-|-|-|-|
| 1 | `qwen3.5:4b` | ~4 GB | ✅ Instalado | (baseline) |
| 2 | `qwen2.5vl:7b` | ~7 GB | `ollama pull qwen2.5vl:7b` | Candidato primário |
| 3 | `qwen3-vl:8b` | ~9 GB | `ollama pull qwen3-vl:8b` | Upgrade SOTA |
| 4 | `minicpm-v` | ~6 GB | `ollama pull minicpm-v` | Especialista OCR |

**Como rodar:**

```bash
# Baseline (qwen3.5:4b)
python -m tests.vision_benchmark.runner --model qwen3.5:4b --limit 50

# Candidatos
ollama pull qwen2.5vl:7b
python -m tests.vision_benchmark.runner --model qwen2.5vl:7b --limit 50

ollama pull qwen3-vl:8b
python -m tests.vision_benchmark.runner --model qwen3-vl:8b --limit 50

ollama pull minicpm-v
python -m tests.vision_benchmark.runner --model minicpm-v --limit 50

# Gerar relatório
python -m tests.vision_benchmark.report --models qwen3.5:4b qwen2.5vl:7b qwen3-vl:8b minicpm-v
```

**Critérios de aprovação (thresholds):**
- OCR exact-match ≥85%
- Grounding IoU ≥0.70
- JSON validity ≥95%
- Latency P50 ≤5s (GPU mode)
- VRAM peak ≤10 GB

**Status:** Smoke test iniciado (benchmark com --limit 2). Aguardando resultados.

---

### **Fase A4: Decidir + Gemini Fallback** 📝 ESBOÇADO (2h)

**Arquivo criado:**
- `src/skills/vision/vlm_cloud_fallback.py` — cliente Gemini 2.5 Flash (async-compatible)

**Regras de decisão:**

1. **Se Qwen3-VL-8B passar todos os critérios:**
   - Atualizar `.env.example`: `VLM_MODEL=qwen3-vl:8b`
   - Atualizar `src/skills/vision/vlm_client.py:24` default
   - Documentar em SPRINT_12_COMPLETE.md
   - Manter Qwen3.5-4B como fallback

2. **Se Qwen3-VL-8B passar em UI/descrição mas MiniCPM-V vencer OCR:**
   - Arquitetura híbrida: `VLMClient` com 2 clientes (`vlm_general`, `vlm_ocr`)
   - `extract_text_from_image()` → MiniCPM-V
   - Outros métodos → Qwen3-VL-8B
   - Inference lock global (não saturar GPU)

3. **Integrar Gemini 2.5 Flash como tier cloud:**
   - Trigger: Ollama offline, GPU semaphore >30s, confidence <0.5
   - Integração via `src/providers/cascade_advanced.py` (novo tier VLM)
   - Audit via `SafetyLayer.audit_log` (Sprint 7.3)
   - Env: `GEMINI_API_KEY`, `GEMINI_VLM_FALLBACK=true`

**Status:** Esboço pronto, integração pending.

---

## Verificação E2E (Fase A5)

Após decisão de modelo (A4):

1. **Regression tests:**
   ```bash
   pytest tests/vision_benchmark/test_vlm_benchmark.py -v
   ```
   Garante que modelo em produção mantém baseline.

2. **AFK Protocol smoke test:**
   ```bash
   # No Telegram: /watch
   # Validar que describe_page() retorna JSON válido em PT-BR
   ```

3. **Desktop watch integração:**
   ```bash
   # Rodar 5 min, validar logs, checar VRAM peak <10 GB
   python -m src
   ```

4. **Cascade regression:**
   ```bash
   pytest tests/test_cascade_advanced.py -v
   # Todos 22 tests devem passar
   ```

---

## Recursos Locais Inventariados

**`E:\Downloads ViralClipOS\LLM Models\`:**
- `qwen2.5-vl-7b-instruct-q4_k_m.gguf` (4.68 GB) — **falta mmproj** (~600 MB)
  - Opção A: `ollama pull qwen2.5vl:7b` (simples, re-download ~5 GB)
  - Opção B: baixar mmproj + llama-server (reusa GGUF, +1h código)
- `Qwen3.5-9B.Q4_K_M.gguf` (5.6 GB) — validar se é VL-capable

**`E:\Downloads ViralClipOS\Models_AI\models--xlangai--OpenCUA-7B\`:**
- **OpenCUA-7B** (14 GB alocado, download incompleto) — especialista GUI
- Potencial game-changer para AFK Protocol se completado
- Roda via Transformers (fora do Ollama)
- Fase A3.5 opcional: testar se IoU grounding supera Qwen3-VL-8B

---

## Timeline Estimada

| Fase | Horas | Status |
|------|-------|--------|
| A1 — Config | 1h | ✅ Completa |
| A2 — Harness | 3h | ✅ Completa |
| A3 — Benchmark | 2.5h | 🔄 20% (smoke test) |
| A4 — Decidir + Gemini | 2h | 📝 30% (esboço) |
| E2E + Docs | 1h | ⏳ Pendente |
| **Total** | **9.5h** | |

**Alinhado com 10-12h reservadas para Sprint 12 no roadmap.**

---

## Fora de Escopo (Track B — Condicional)

Só abrir se benchmarks mostrarem gaps:
- **pytesseract/EasyOCR** — APENAS se OCR exact-match <90% em todos os candidatos
- **YOLO v8** — APENAS se UI grounding IoU <0.6 em todos os candidatos
- **PDF parsing** — independente, pode ser Sprint 13
- **Annotated screenshots** — polish, baixa prioridade

**Racional:** VLMs de 8B modernos capturam 80-90% do valor que CV clássico entregava, com 1/3 do código e zero deps extras.

---

## Notas de Implementação

### Como testar hot-swap:
```python
import asyncio
from src.skills.vision.vlm_client import VLMClient

async def test():
    vlm = VLMClient()  # inicia com qwen3.5:4b (ou env override)
    await vlm.set_model("qwen3-vl:8b")  # swap sem reinit
    # ... usa vlm normalmente com novo modelo
    await vlm.close()

asyncio.run(test())
```

### Como inspecionar benchmark resultados:
```bash
# Localizados em E:\Seeker.Bot\reports\
ls -la reports/
# summary_qwen3.5_4b.json
# summary_qwen2.5vl_7b.json
# ... etc

# Relatório markdown
cat reports/vision_2_0_comparison.md
```

### Como adicionar dados reais ao benchmark:
1. Colecionar screenshots reais (AFK, chat, browser, task manager)
2. Rotular em `tests/vision_benchmark/dataset/{categoria}/labels.json`
3. `load_dataset()` carrega automaticamente

---

## Decision Log

**2026-04-10 — Sprint 12 Kickoff**
- Reframe Vision 2.0: VLM upgrade (moderno) vs CV clássico (antigo)
- Razão: VLMs de 8B ja fazem OCR+grounding SOTA; Qwen3.5-4B é desconhecido (zero benchmark)
- User confirmed: GPU 12GB, misto (AFK+OCR+desc), cloud fallback SIM, escopo VLM only
- Decisão de implementação: framework + benchmark + hot-swap infra (Fases A1-A2)

---

## Next Session

1. Monitorar conclusão do benchmark (Fase A3)
2. Gerar relatório comparativo
3. Implementar decisão (Fase A4)
4. E2E validation
5. Criar SPRINT_12_COMPLETE.md final

**Commit atual:** `bdbbda1` (Vision 2.0 Fase A1-A2)
