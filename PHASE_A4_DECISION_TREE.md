# Fase A4: Decision Tree — Qual Modelo Vence?

**Baseado em:** Resultados do benchmark Fase A3 (3 candidatos)

---

## Critérios de Aprovação (Hard Thresholds)

```
Para passar na seleção, TODAS estas métricas devem ser atendidas:

✓ OCR exact-match ≥85%
✓ Grounding IoU ≥0.70
✓ Grounding JSON validity ≥95%
✓ Latência P50 grounding ≤5s (GPU mode)
✓ VRAM peak ≤10 GB (margem para outras skills)
```

---

## Decision Logic

### Cenário 1: Um modelo passa em TUDO ✅

**Ação:**
1. Atualizar `.env.example`: `VLM_MODEL=<vencedor>`
2. Atualizar `src/skills/vision/vlm_client.py:24` default
3. Commit: `"Sprint 12 A4: Upgrade to <vencedor> (all thresholds passed)"`
4. Documentar em SPRINT_12_COMPLETE.md
5. E2E smoke test (AFK Protocol)

**Probabilidade:** Alta (Qwen3-VL-8B ou MiniCPM-V 2.6 são maduros)

---

### Cenário 2: Diferentes modelos vencem em diferentes categorias 📊

**Exemplo:**
- OCR: MiniCPM-V vence (96% exact-match)
- Grounding: Qwen3-VL-8B vence (0.72 IoU, 5s latência)
- Description: Qwen2.5-VL vence (89% keywords)

**Ação (Arquitetura Híbrida):**
1. Criar `vlm_client_hybrid.py`:
   ```python
   class HybridVLMClient:
       def __init__(self):
           self.vlm_ocr = VLMClient(model="minicpm-v")      # Especialista OCR
           self.vlm_general = VLMClient(model="qwen3-vl:8b") # Geral + grounding
       
       async def extract_text_from_image(self):
           return await self.vlm_ocr.extract_text_from_image()
       
       async def locate_element(self):
           return await self.vlm_general.locate_element()
   ```

2. Global inference lock (evitar saturar GPU com 2 chamadas simultâneas)
3. Atualizar `vlm_client.py` para detectar e usar hybrid se `VLM_HYBRID=true`
4. Commit: `"Sprint 12 A4: Hybrid VLM architecture (MiniCPM OCR + Qwen3-VL grounding)"`

**Probabilidade:** Moderada (30-40% — modelos têm especializações)

---

### Cenário 3: Nenhum modelo passa em TODOS os thresholds ❌

**Ação Imediata:**
1. Analisar qual categoria falha:
   - Se OCR <85%: abre Track B (pytesseract)
   - Se Grounding IoU <0.70: abre Track B (YOLO)
   - Se latência >5s: **cloud-first (Gemini fallback é mandatório)**

2. Implementar Gemini 2.5 Flash como primary:
   - `src/skills/vision/vlm_cloud_fallback.py` (já existe)
   - Integrar em `src/providers/cascade_advanced.py`
   - Atualizar `.env.example`: `GEMINI_VLM_FALLBACK=true`

3. Fallback local para emergência:
   ```python
   # Se Gemini também falha (API down), volta para qwen3.5:4b
   # com conhecimento de que grounding vai falhar
   ```

4. Commit: `"Sprint 12 A4: Cloud-first with Gemini 2.5 Flash (local models insufficient)"`

**Probabilidade:** Baixa (<10% — Qwen3-VL-8B/MiniCPM-V 2.6 são SOTA)

---

### Cenário 4: Todos os modelos falham completamente 🔥

**Não deve acontecer, mas se acontecer:**
1. Diagnóstico: dataset inadequado ou benchmark quebrado
2. Roll back: manter Qwen3.5-4B com conhecimento de falha em grounding
3. Agendar investigação deep-dive no mês que vem
4. Document bug report em GitHub

---

## Tabela de Decisão Rápida

```
Qwen2.5-VL-7B     | Qwen3-VL-8B       | MiniCPM-V         | Ação
─────────────────────────────────────────────────────────────────
✅ (all pass)     | ❌                | ❌                | → Usar Qwen2.5-VL
❌                | ✅ (all pass)     | ❌                | → Usar Qwen3-VL
❌                | ❌                | ✅ (all pass)     | → Usar MiniCPM-V
✅ (OCR)          | ✅ (Grounding)    | ✅ (Description)  | → Arquitetura Híbrida
❌ (Grounding)    | ⚠️ (Borderline)   | ✅ (Grounding)    | → Usar MiniCPM-V
❌ (all)          | ⚠️ (all)          | ⚠️ (all)          | → Gemini cloud + local fallback
```

---

## Script de Análise

Depois que Fase A3 rodar, executar:

```bash
python << 'EOF'
import json
from pathlib import Path

reports_dir = Path("reports")

# Carrega summaries
summaries = {}
for model in ["qwen2.5vl:7b", "qwen3-vl:8b", "minicpm-v"]:
    summary_file = reports_dir / f"summary_{model.replace(':', '_')}.json"
    if summary_file.exists():
        with summary_file.open() as f:
            summaries[model] = json.load(f)

# Checa critérios
thresholds = {
    "ocr_exact_match_%": 85.0,
    "grounding_iou_mean": 0.70,
    "json_valid_%": 95.0,
    "latency_p50_ms": 5000.0,  # milliseconds
}

print("\n=== ANALISE DE CRITERIOS ===\n")
for model, summary in summaries.items():
    print(f"Modelo: {model}")
    ocr_data = summary.get("by_category", {}).get("ocr", {})
    ground_data = summary.get("by_category", {}).get("grounding", {})
    
    checks = {
        "OCR exact-match": (ocr_data.get("ocr_exact_match_%", 0), 85.0),
        "Grounding IoU": (ground_data.get("grounding_iou_mean", 0), 0.70),
        "JSON validity": (ground_data.get("json_valid_%", 0), 95.0),
    }
    
    for check_name, (actual, threshold) in checks.items():
        status = "✓" if actual >= threshold else "✗"
        print(f"  {status} {check_name}: {actual:.1f}% >= {threshold:.1f}%")
    
    print()
EOF
```

---

## Documentação Final (SPRINT_12_COMPLETE.md)

Depois da decisão, criar documento com:

```markdown
# Sprint 12 — Vision 2.0 COMPLETA

## Resultado Final
- Modelo selecionado: [vencedor]
- Razão: [métricas que passaram]
- Data: [hoje]

## Métricas de Sucesso
- [tabela comparativa final]

## Próximos Passos
- [ ] Deploy em produção (mudar .env)
- [ ] Monitor AFK Protocol para regressões
- [ ] Coletar métricas de produção (latência real, taxa de erro)
```

---

## Timeline Fase A4

- **T+0h:** Fase A3 resultados chegam (aguardando pulls)
- **T+0.5h:** Análise rápida (qual cenário estamos?)
- **T+1h:** Implementação (1-2h conforme o cenário)
- **T+2-3h:** E2E smoke test
- **T+3-4h:** SPRINT_12_COMPLETE.md + commit final

**Total Fase A4:** 2-4h conforme cenário
