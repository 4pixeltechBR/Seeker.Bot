# Seeker.Bot — Code Review + Pipeline Review
**Data:** 2026-04-25
**Branch:** `feature/seeker-v3-refactor`
**Escopo:** Validação Antigravity (Camada 0) + Hot Path (Camada 1)

---

## Resumo Executivo

- **10 bugs corrigidos** durante o review — 8 introduzidos pelo Antigravity, 2 existentes no pipeline.
- **Cadeia /cofre + /obsidian com imagens estava completamente quebrada** (TypeError em runtime): `analyze_screenshot` recusava o `prompt=` kwarg do `extractors.py`. Corrigido em toda a cadeia (vlm_router → gemini_vlm → extractors).
- **`desktop_controller.py` tinha 4 pontos de quebra simultâneos**: dict-como-string, campo `locate_element` errado, e `unload_model()` inexistente. Todos corrigidos.
- **Pipeline principal** tinha 2 bugs de qualidade: `return result` duplicado (dead code) e `obsidian_exporter.sync_all()` bypassando o sistema de tracking de erros.
- **Estado geral:** Codebase é arquiteturalmente sólido. As regressões foram pontuais e cirúrgicas — fruto da nova abstração Dict da VLMRouter não ter sido propagada para os consumers. Pronto para Day 2 do master plan (CodeValidator) após estes fixes.

---

## Seção 1 — Validação Antigravity (Camada 0)

### 1.1 Bug Crítico — Cadeia knowledge_vault quebrada

**Status: CORRIGIDO**

#### Raiz do problema
O Antigravity introduziu `VLMRouter` com interface unificada (retorno `Dict`) em substituição ao `VLMClient` (retorno `str`). A migração não foi propagada para todos os consumers.

#### Bug 1.A — `vlm_router.py:134` — `analyze_screenshot` recusa `prompt` kwarg
```python
# ANTES (quebrado):
async def analyze_screenshot(self, image_path: str | bytes) -> Dict:
    return await self._execute_with_routing(task_type, image_path, "analyze_screenshot")

# DEPOIS (corrigido):
async def analyze_screenshot(self, image_path: str | bytes, prompt: Optional[str] = None) -> Dict:
    kwargs = {"prompt": prompt} if prompt is not None else {}
    return await self._execute_with_routing(task_type, image_path, "analyze_screenshot", **kwargs)
```
**Impacto em runtime:** `TypeError: analyze_screenshot() got an unexpected keyword argument 'prompt'` — toda operação `/cofre`/`/obsidian` com imagem falha.

#### Bug 1.B — `gemini_vlm.py:71` — prompt hardcoded ignora caller
```python
# ANTES (prompt sempre ignorado):
async def analyze_screenshot(self, image_path: str) -> Dict:
    prompt = "Descreva a interface atual..."

# DEPOIS (prompt do caller respeitado):
async def analyze_screenshot(self, image_path: str | bytes, prompt: Optional[str] = None) -> Dict:
    prompt = prompt or "Descreva a interface atual..."
```

#### Bug 1.C — `extractors.py:30-31` — dict-como-string + tipo incorreto
```python
# ANTES (dois bugs):
analysis = await vlm_client.analyze_screenshot(img_bytes, prompt=prompt)
results.append(f"--- IMAGEM {i+1} ---\n{analysis}")  # analysis é Dict, não str

# DEPOIS (correto + compatível com VLMClient que retorna str):
result = await vlm_client.analyze_screenshot(img_bytes, prompt=prompt)
if isinstance(result, dict):
    analysis_text = result.get("analysis") or result.get("text") or str(result)
else:
    analysis_text = result or ""
results.append(f"--- IMAGEM {i+1} ---\n{analysis_text}")
```

---

### 1.2 Bugs no desktop_controller.py (4 ocorrências)

**Status: TODOS CORRIGIDOS**

| # | Linha | Tipo | Descrição |
|---|-------|------|-----------|
| 1 | 93-95 | Dict-como-string | `describe_page()` → str em f-string sem `.get("description")` |
| 2 | 165-169 | Contrato errado | `locate_element` retorna `found`/`center` mas código acessa `confidence`/`x`/`y` → `KeyError` |
| 3 | 194 | Dict-como-string | Segunda ocorrência de `describe_page()` → str |
| 4 | 232 | AttributeError | `vlm.unload_model()` — `VLMRouter` não tem este método → erro no shutdown |

**Bug 2 (locate_element) em detalhe:**
```python
# ANTES (quebrado):
bbox = await self.vlm.locate_element(screenshot_bytes, element_description)
if not bbox or bbox.get("confidence", 0) < 0.3:  # 'confidence' não existe
target_x, target_y = int(bbox["x"]), int(bbox["y"])  # 'x', 'y' não existem

# DEPOIS (correto — VLMRouter retorna found/center/bbox):
loc_result = await self.vlm.locate_element(screenshot_bytes, element_description)
if not loc_result or not loc_result.get("found") or not loc_result.get("center"):
    ...
target_x, target_y = loc_result["center"]
```

---

### 1.3 desktop_watch/goal.py — dict-como-string em parse

**Status: CORRIGIDO**

```python
# ANTES:
analysis = await self._vlm.analyze_screenshot(screenshot_bytes, WATCH_PROMPT)
result_data = self._parse_vlm_response(analysis)  # _parse_vlm_response espera str, recebe Dict

# DEPOIS:
analysis_dict = await self._vlm.analyze_screenshot(screenshot_bytes, WATCH_PROMPT)
analysis_raw = analysis_dict.get("analysis") or analysis_dict.get("text") or str(analysis_dict)
result_data = self._parse_vlm_response(analysis_raw)
```

---

### 1.4 Arquivos Antigravity — sem problemas encontrados

| Arquivo | Status | Observação |
|---------|--------|-----------|
| `src/core/goals/registry.py` | ✅ OK | PyYAML ausente tratado com try/except; merge de deny_list correto |
| `config/skills.yaml` | ✅ OK | YAML válido; categorias coerentes com discovery |
| `src/providers/cascade.py` | ✅ OK | Stubs `get_health_status()` / `get_cost_analysis()` retornam contratos corretos para `/cascade_status` |
| `src/skills/knowledge_vault/analyzer.py` | ✅ OK | Migração `prompt()` → `call()` correta; `response_dict.get("content")` adequado |
| `src/core/cognition/prompts.py` | ✅ OK | `{{ }}` correto no f-string do REFINEMENT_CRITIQUE_SYSTEM |
| `src/core/router/cognitive_load.py` | ✅ OK | `hierarchy.index(m) if m in hierarchy else 99` previne KeyError |
| `src/channels/telegram/bot.py` | ✅ OK | vault_debouncer race fix correto; `/cofre` alias funciona; `/crm` smart parser OK |

---

## Seção 2 — Pipeline Review (Camada 1 — Hot Path)

### 2.1 Diagrama de Fluxo (crítico)

```
Mensagem Telegram
    │
    ▼
bot.py handler
    │ session_id
    ▼
SeekerPipeline.process()
    │
    ├── [0] session.add_turn("user", input)
    ├── [1] _build_memory_context() → 4-Layer: L1 Essential + L2 Semântico + L3 Fallback + Episodes
    ├── [2] CognitiveLoadRouter.route() → depth (REFLEX/DELIBERATE/DEEP), 0 LLM calls
    ├── [2.5] IntentClassifier.classify() → IntentCard (risk, tier)
    │       └── HIGH RISK? → return bloqueado imediatamente
    ├── [2.7] VaultSearcher.get_context_for_llm() (se needs_vault)
    ├── [3] Dispatch por depth:
    │       ├── REFLEX → ReflexPhase (1 LLM call, <500ms target)
    │       ├── DELIBERATE → DeliberatePhase (1-2 LLM calls, web opcional)
    │       └── DEEP → DeepPhase (3+ LLM calls, arbitrage + judge)
    ├── [4] Monta PipelineResult
    ├── [5] FactExtractor.extract() (síncrono — bloqueia UX ~500ms)
    └── [6] _spawn_background(_post_process()) → session + facts + episódio + Obsidian
```

### 2.2 Pontos de Falha Sem Fallback (antes dos fixes)

| Ponto | Risco | Fix aplicado |
|-------|-------|-------------|
| `obsidian_exporter.sync_all()` em `asyncio.create_task()` | Erros silenciados, não logados via `_on_task_done` | Migrado para `_spawn_background()` |
| `return result` duplicado (L483+484) | Dead code; refactoring artifact | Linha órfã removida |

### 2.3 Pontos de Latência Acumulada

1. **Etapa [5] — FactExtractor síncrono** (`extractor.extract()`): Roda antes de retornar ao usuário. Pode adicionar 300-800ms à P95. O `_post_process` em background existe, mas `extractor.extract()` ainda está no caminho síncrono (L470-477). **Candidato à otimização Day 2.**

2. **Etapa [2] — CognitiveLoadRouter**: 0ms (apenas regex). ✅

3. **Deliberate Phase**: Web search tem timeout de 25s, síntese LLM tem timeout de 180s. O P95 de 15.989ms do baseline é consistente com Groq tier em carga.

4. **DeepPhase**: 3+ LLM calls + arbitrage. O P99 de 26.064ms capturado no baseline reflete este caminho.

### 2.4 Estado Durável vs In-Memory

| Componente | Persistência | Recovery após crash |
|------------|-------------|---------------------|
| Fatos/Episódios | SQLite (`seeker_memory.db`) | Completo |
| Sessão Telegram | SQLite via `MemoryStore` | Completo |
| Background tasks | In-memory `_background_tasks` set | Perdido (flush de até 10s no shutdown) |
| RL Events | In-memory `_open_events` dict | Perdido |
| Cascade Bandit | Salvo em arquivo via `bandit.load()` | Completo |
| Embeddings | Persistidos em disco | Completo |

**Risk:** Background tasks não comitadas perdem até 10s de fatos ao crashar. Shutdown gracioso com `timeout=10.0` mitiga o risco principal.

### 2.5 Back-Pressure

- `MAX_CONCURRENT_GOALS = 3` no GoalScheduler previne contention de VRAM/GPU ✅
- `_is_vram_exhausted()` no VLMRouter (guarda ViralClip) ✅
- Rate limiter por provider em `base.py` (sliding window) ✅
- Circuit breaker por provider no cascade (3 failures → 5min penalty) ✅

---

## Seção 3 — Self-Healing Readiness (Camada 2)

*Avaliação rápida — não bloqueante para Day 2*

| Componente Day 2-5 | Ponto de Inserção | Status |
|--------------------|-------------------|--------|
| **CodeValidator** (ast.parse + compile + pyright) | `src/skills/self_improvement/goal.py` antes do `apply_patch()` | Slot disponível, nenhum bloqueio |
| **ErrorDatabase** (SQLite) | Nova tabela em `seeker_memory.db` ou `seeker_data.db` | OK, padrão já estabelecido |
| **sanitize_traceback** | `src/core/error_recovery.py` wrapping `ErrorRecoveryManager` | Arquivo existe, adicionar método |
| **ApprovalEngine** | Usar `SafetyPolicy.L0_MANUAL` + bot.py inline buttons | InlineKeyboardMarkup já em uso no bot.py |

**Conclusão:** Nenhuma mudança arquitetural bloqueante. Day 2 pode começar imediatamente após este review.

---

## Seção 4 — Test Failure Clusters (Camada 3)

*Diagnóstico rápido dos 4 clusters do baseline (69 failures+errors de 663 total)*

### Cluster 1 — `test_executor_*` (22 failures)
**Root cause suspeita:** `SafetyLayer` foi reescrita (`safety_layer.py` simples vs `safety_layer_enhanced.py`). Testes provavelmente importam `SafetyLayer` da versão simples com API diferente (enum `L1/L2/L3` vs `L0_MANUAL/L1_LOGGED/L2_SILENT`).

### Cluster 2 — `test_scheduler_*` (16 failures)
**Root cause suspeita:** `GoalScheduler` adicionou `GoalPriority` enum no Sprint 7.2. Testes que instanciam `register()` sem `priority=` param ou que usam API anterior de `GoalResult`.

### Cluster 3 — `test_cascade_adapter` (11 errors)
**Root cause suspeita:** `CascadeAdapter` simples vs `cascade_advanced.py`. Testes provavelmente instanciam `CascadeAdapter` direto, que requer `ModelRouter` — e o mock não tem o método `get_fallbacks()` que agora é chamado.

### Cluster 4 — `test_pipeline_intent` (17 errors)
**Root cause suspeita:** `IntentClassifier` e `IntentCard` têm campos adicionados (`required_permissions`, `user_id`). Testes podem estar comparando dataclasses com campos diferentes ou usando factories desatualizadas.

*Fix estimado: 1 sessão focada em Day 2-3 do master plan.*

---

## Seção 5 — Findings Completos

### Críticos (🔴) — Todos corrigidos

| # | Arquivo | Linha | Issue | Fix |
|---|---------|-------|-------|-----|
| 1 | `vlm_router.py` | 134 | TypeError: `prompt` kwarg recusado | Assinatura atualizada com `Optional[str]` |
| 2 | `gemini_vlm.py` | 71 | Prompt hardcoded, ignora caller | Aceita `prompt` param com fallback |
| 3 | `extractors.py` | 30-31 | Dict-como-string + compatibilidade dual-client | `isinstance(result, dict)` + `.get("analysis")` |
| 4 | `desktop_controller.py` | 165-169 | `locate_element` campos errados (`x`/`y`/`confidence`) | Usa `found`/`center` do retorno real |
| 5 | `desktop_watch/goal.py` | 186-192 | Dict-como-string em `_parse_vlm_response` | Extrai `.get("analysis")` antes de parsear |

### Altos (🟠) — Todos corrigidos

| # | Arquivo | Linha | Issue | Fix |
|---|---------|-------|-------|-----|
| 6 | `desktop_controller.py` | 93-95 | `describe_page()` Dict-como-string (read_screen) | `.get("description")` |
| 7 | `desktop_controller.py` | 194 | `describe_page()` Dict-como-string (execute_action) | `.get("description")` |
| 8 | `desktop_controller.py` | 232 | `vlm.unload_model()` não existe no VLMRouter | Guarda com `hasattr` |
| 9 | `pipeline.py` | 483-484 | Duplicate `return result` (dead code) | Linha removida |
| 10 | `pipeline.py` | 894 | `create_task()` bypassa tracking de erros | Migrado para `_spawn_background()` |

### Médios (🟡) — Não corrigidos (Day 2 ou aceitável)

| # | Arquivo | Linha | Issue | Recomendação |
|---|---------|-------|-------|-------------|
| 11 | `pipeline.py` | 470-477 | `extractor.extract()` no caminho síncrono (500ms) | Mover para background no Day 2 |
| 12 | `_post_process` | 833-855 | `except Exception: pass` swallows entity/triple errors silenciosamente | Adicionar `log.debug()` |
| 13 | `providers/base.py` | — | NVIDIA tier com 0.1% hit (possível circuit breaker aberto) | Investigar chave/endpoint no Day 2 |

---

## Verdict

**✅ Liberado para Day 2 do master plan.**

Todas as regressões Antigravity estão corrigidas. O pipeline principal está saudável. Os 10 bugs fixados eliminam falhas silenciosas que impediriam o Knowledge Vault de funcionar com imagens e o Desktop Controller de executar qualquer ação.

**Próximo passo imediato:** Day 2 — implementar `CodeValidator` em `src/skills/self_improvement/goal.py` com `ast.parse()` + `compile()` + opcional `pyright --outputjson`. Ponto de inserção: antes de qualquer `apply_patch()` ou `write_file()` no fluxo de auto-healing.

---

*Gerado em: 2026-04-25 | Branch: feature/seeker-v3-refactor*
