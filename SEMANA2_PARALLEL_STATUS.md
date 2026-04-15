# Semana 2 — Execução em Paralelo (3 Tracks Simultâneos)

**Data:** 2026-04-15  
**Status:** Iniciando paralelização de A3 + B4-B5 + C4-C5  
**Duração:** ~10h distribuído em 3 tracks independentes

---

## 📊 Status Consolidado

```
VISION 2.0 (Track A)
├─ A1 (Config Refactor)         ✅ COMPLETE (1h)
├─ A2 (Benchmark Harness)       ✅ COMPLETE (3h)
├─ A3 (Evaluate 4+ Models)      ⏳ IN PROGRESS (2.5h)
├─ A4 (Deploy + GLM-OCR)        ✅ COMPLETE (9h) ← E2E VALIDATED
│   ├─ A4.1: Qwen3-VL-8B + Gemini fallback  ✅ 
│   ├─ A4.2: GLM-OCR intelligent routing    ✅ (59 tests passing)
│   └─ A4.3: Documentation                  ✅
└─ Status: READY FOR STAGING

REMOTE EXECUTOR (Track B)
├─ B1 (Core Datastructures)     ✅ COMPLETE (2h)
├─ B2 (Action Handlers)         ✅ COMPLETE (3h)
├─ B3 (Orchestrator + Safety)   ✅ COMPLETE (3h)
├─ B4 (Goal Implementation)     ⏳ PENDING (2h)
├─ B5 (Testing)                 ⏳ PENDING (2.5h)
└─ Status: READY TO IMPLEMENT

SCOUT HUNTER 2.0 (Track C)
├─ C1 (Discovery Matrix)        ⏳ PENDING (2h)
├─ C2 (Account Research)        ⏳ PENDING (3h)
├─ C3 (Qualification + Copy)    ⏳ PENDING (2h)
├─ C4 (Metrics)                 ⏳ PENDING (1.5h)
├─ C5 (Testing)                 ⏳ PENDING (1.5h)
└─ Status: READY TO IMPLEMENT
```

---

## 🚀 Timeline Executável (Paralelo)

### **Sessão 1 (Hoje) — 3-4h**
**Executar em paralelo:**

| Track | Task | Time | Output |
|-------|------|------|--------|
| **A3** | Benchmark quick run (mock + ollama pulls) | 2.5h | `reports/vision_2_0_comparison.md` |
| **B4** | Create `src/skills/remote_executor/miner.py` | 2h | Intent detection working |
| **C4** | Create `src/skills/scout_hunter/discovery_matrix.py` | 2h | Fit score evaluation working |

### **Sessão 2 (Amanhã) — 3-4h**
**Executar em paralelo:**

| Track | Task | Time | Output |
|-------|------|------|--------|
| **B5** | Create 4 test files for Remote Executor | 2.5h | 20+ tests passing |
| **C5** | Create tests + Scout Hunter integration | 2h | E2E routing validated |

### **Sessão 3 (Follow-up) — 2-3h**
**Final validation:**

| Track | Task | Time | Output |
|-------|------|------|--------|
| **A3** | Analyze results + decision | 1h | Model selection final |
| **B4-B5** | Full E2E validation | 1.5h | Remote Executor live |
| **C4-C5** | Full E2E validation | 1.5h | Scout Hunter 2.0 live |

**Total Time:** ~10-12h distributed (vs 22h sequential)

---

## 📁 Arquivos a Criar Hoje (Sessão 1)

### Track A3
```
reports/
├─ vision_2_0_comparison.md      ← Benchmark report
└─ *.json                        ← Model results (5 models)
```

### Track B4
```
src/skills/remote_executor/
├─ __init__.py                   ← Package init
├─ config.py                     ← Budget limits, channels
└─ miner.py                      ← RemoteExecutorMiner (intent detection)
```

### Track C4
```
src/skills/scout_hunter/
├─ discovery_matrix.py           ← DiscoveryMatrix + TaskClassifier
└─ account_research.py           ← AccountResearcher + decision makers
```

---

## 🎯 Execution Plan

### **A3 — Vision Benchmark** (Responsável: Claude)

```bash
# Quick option (5 min):
python -m tests.vision_benchmark.benchmark_mock --all-models --output reports/

# Real option (if time permits):
ollama pull qwen3-vl:8b &  # Background
ollama pull minicpm-v &     # Background
# Wait for pulls, then run benchmark
```

**Output:** `reports/vision_2_0_comparison.md` com tabela dos 5 modelos

**Decision Criteria:**
- Qwen3-VL-8B ≥ 85% OCR, ≥0.70 IoU, ≥95% JSON, ≤5s latency, ≤10GB VRAM
- If passes ALL → deploy (você escolheu isso em A4)
- If fails some → reopen scope for pytesseract/YOLO

---

### **B4 — Remote Executor Miner** (Responsável: Claude)

**Objetivo:** Detect ACTION intent + classify autonomy tier (L2_SILENT, L1_LOGGED, L0_MANUAL)

**Files to Create:**
1. `src/skills/remote_executor/__init__.py` — package init
2. `src/skills/remote_executor/config.py` — budget limits, approval windows
3. `src/skills/remote_executor/miner.py` — RemoteExecutorMiner class (300 linhas)

**Key Class:**
```python
class RemoteExecutorMiner:
    """Detects ACTION intent and classifies autonomy tier"""
    
    def classify(self, intent: str) -> Dict:
        # Returns: {action: bash|file|desktop|delegation, tier: L2|L1|L0, ...}
        pass
```

**Output:** Miner class working, ready for orchestrator

---

### **C4 — Scout Hunter Discovery Matrix** (Responsável: Claude)

**Objetivo:** Add Discovery Matrix module + Account Research for lead qualification

**Files to Create:**
1. `src/skills/scout_hunter/discovery_matrix.py` (200 linhas)
2. `src/skills/scout_hunter/account_research.py` (350 linhas)

**Key Classes:**
```python
class DiscoveryMatrix:
    """Detects fit score + intent signals + budget indicator"""
    
    async def evaluate_lead(self, lead: Dict) -> DiscoveryMatrixResult:
        # Returns: {fit_score: 0-100, intent_level: 0-5, budget_indicator: str}
        pass

class AccountResearcher:
    """Deep research on company + decision makers"""
    
    async def research_account(self, company: str) -> AccountResearchResult:
        # Returns: {company_desc, tech_stack[], pain_points[], decision_makers[]}
        pass
```

**Output:** Both modules working, ready for integration

---

## ⚡ Kickoff Commands (Run These Now)

### **Terminal 1: Vision Benchmark (Quick)**
```bash
cd E:\Seeker.Bot
python -m tests.vision_benchmark.benchmark_mock --all-models --output reports/
# Or real benchmark if Ollama available:
# ollama pull qwen3-vl:8b  (background)
# python -m tests.vision_benchmark.runner --all-models
```

### **Terminal 2: Remote Executor** (Start creating miner.py)
- Files: `config.py`, `miner.py` in `src/skills/remote_executor/`
- Parallel with A3 and C4

### **Terminal 3: Scout Hunter** (Start creating discovery modules)
- Files: `discovery_matrix.py`, `account_research.py` in `src/skills/scout_hunter/`
- Parallel with A3 and B4

---

## 📋 Quality Gates (Before Commit)

Each track must pass:

**Track A3:**
- ✅ Benchmark runs without error
- ✅ `reports/vision_2_0_comparison.md` generated
- ✅ 5 models compared
- ✅ Qwen3-VL-8B meets all 5 thresholds

**Track B4:**
- ✅ `RemoteExecutorMiner.classify()` returns valid tier
- ✅ BASH_WHITELIST enforced
- ✅ L2_SILENT, L1_LOGGED, L0_MANUAL all detected

**Track C4:**
- ✅ `DiscoveryMatrix.evaluate_lead()` returns fit_score
- ✅ `AccountResearcher.research_account()` returns company context
- ✅ No blocking errors on missing research data

---

## 🎬 Next: Start Parallel Work

All 3 tracks ready to start simultaneously. Each track is independent:
- **A3** depends only on Ollama
- **B4** has no dependencies (new feature)
- **C4** depends only on Scout Hunter existing structure

**Estimated completion:** 4-5 hours for first round of all 3

Ready to begin? 🚀

---

**Managed by:** Claude Code  
**Session:** Semana 2 Kickoff  
**Parallelization:** Full (3 concurrent tracks)
