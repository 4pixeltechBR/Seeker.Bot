# Seeker.Bot — Manual de Troubleshooting e Otimizações

> Documento vivo. Registra erros/problemas que enfrentamos durante a auditoria
> profunda de 16/07/2026 → 17/07/2026 e como cada um foi resolvido.
>
> **Auditor:** Claude (audit-fix workflow + revisão humana)
> **Período:** 14/07/2026 → 17/07/2026
> **Escopo:** Seeker.Bot em `E:\Seeker.Bot\`

---

## Sumário

1. [Padrões & Decisões](#1-padroes--decisoes-de-codigo)
2. [Bugs Encontrados e Resolvidos (F-01 → F-09)](#2-bugs-encontrados-e-resolvidos)
3. [Code Review (CR-01 → WR-04, IN-01 → IN-03)](#3-code-review)
4. [Insight Waves (Wave 4: Memory, Health, SOUL, RL, Events, Graph)](#4-insight-waves)
5. [Substituição de Modelos (Free Tiers Jul/2026)](#5-substituicao-de-modelos-free-tiers-jul2026)
6. [Limpeza & Reconciliação](#6-limpeza--reconciliacao)
7. [Problemas Conhecidos (TODOs)](#7-problemas-conhecidos-todos)
8. [Padrões de Correção Recorrentes](#8-padroes-de-correcao-recorrentes)

---

## 1. Padrões & Decisões de Código

### 1.1 Singleton global via `get_X()`

**Pattern usado em `src/core/events.py`, `src/core/capability_graph.py`:**

```python
_instance: EventBus | None = None

def get_event_bus() -> EventBus:
    global _instance
    if _instance is None:
        _instance = EventBus()
    return _instance
```

**Por quê:** permite reset em testes (via `reset_singletons()` fixture) sem reimportar módulos.

**Cuidado:** singletons em código de produção capturam estado de execução. Reset entre testes evita vazamento.

---

### 1.2 Atualização do banco SQLite via `MemoryProtocol`

**Pattern unificado em `src/core/memory/store.py`:**

- `add_fact()`, `get_facts()`, `delete_fact()`, `update_fact_confidence()` no `MemoryProtocol`
- `EvidenceStore` foi descontinuado → usar `MemoryStore` direto

**Por quê:** separar interface de implementação permite trocar backend (SQLite, Graphiti, Postgres) sem mudar callers.

---

### 1.3 EventBus fanout fire-and-forget

**Pattern em `src/core/events.py`:**

```python
task = asyncio.create_task(_notify(handler))
self._background_tasks.add(task)
task.add_done_callback(self._background_tasks.discard)
```

**Importante:** tasks são adicionadas ao set para tracking e removidas via callback. Não bloqueiam emitter, mas há risco de "Task was destroyed but it is pending!" warnings sem cleanup.

**Sempre chamar `await event_bus.shutdown(timeout=...)` em shutdown.**

---

### 1.4 circuit_breaker para 429 (HTTP 429)

**Pattern correto (pós-bugfix em `src/core/rate_limiting/shared_breaker.py:227-263`):**

```python
# Incrementar PRIMEIRO e depois decidir se aplica cooldown
data[backend]["consecutive_failures"] += 1
failures = data[backend]["consecutive_failures"]

if failures >= self.consecutive_threshold:
    base_cooldown = min(
        self.cooldown_seconds * (2 ** (failures - self.consecutive_threshold)),
        3600,
    )
```

**Bug original:** abria circuito na **primeira** falha 429, ignorando `consecutive_threshold`.

---

### 1.5 Capability Graph com resolução topológica

**Pattern em `src/core/capability_graph.py`:**

- `register(skill, capabilities, dependencies)` — skill declara o que faz e do que precisa
- `resolve(capabilities)` — retorna skills em ordem topológica (dependências primeiro)
- Detecta ciclos via set `temp` (caminho atual) vs `visited` (já processados)

**Útil para:** planejador de execução que precisa descobrir qual skill atender qual necessidade.

---

### 1.6 SOUL.md hot-reload via polling

**Pattern em `src/core/memory/soul_watcher.py`:**

- Polling de mtime (não watchdog inotify — incompatível com Windows)
- Poll interval: 30s (configurável)
- Primeira leitura NÃO dispara callback (evita callback na inicialização)
- `stop()` cancela task e bloqueia novas iterações

---

### 1.7 Epsilon-greedy forçado vs Thompson Sampling (cascade)

**Pattern pós-Wave 4 em `src/core/rl/bandits/cascade.py`:**

- LinUCB cuida da exploração estrutural (UCB)
- Epsilon-greedy decaindo (0.20 → 0.05) cuida de exploração **forçada** em modo SHADOW
- Beta do epsilon: `total_updates` (recompensas recebidas), não `n_predicts` (contador separado)
- Mantém coerência: alpha decay + epsilon decay usam o mesmo contador

---

### 1.8 Auto-load no `src/__main__.py`

**Pattern pós-Wave 4 em `src/__main__.py:6`:**

```python
import src.skills  # noqa: F401  # força auto-registro de capabilities
from src.channels.telegram.bot import main
```

**Por quê:** ao importar `src.skills`, o `__init__.py` chama `get_capability_graph().register(...)` para cada skill. Sem isso, Pipeline init() precisa descobrir manualmente.

---

## 2. Bugs Encontrados e Resolvidos

### Wave 1 (P0 — Críticos) — 16/07/2026

#### F-01: scheduler result=None crash
- **Arquivo:** `src/core/goals/scheduler.py:570`
- **Sintoma:** `AttributeError: 'NoneType' object has no attribute 'success'` quando `goal.run_cycle()` levanta exceção.
- **Causa:** após `except Exception`, controle continuava sem check de `result is None`.
- **Fix (commit `6afdb60`):**
  ```python
  if result is None:
      self._failure_counts[goal.name] = self._failure_counts.get(goal.name, 0) + 1
      await asyncio.sleep(goal.interval_seconds)
      continue
  ```
- **Lição:** `try/except` que captura Exception deve SEMPRE tratar o caso de variáveis não-inicializadas.

#### F-02: miner.py divisão por zero
- **Arquivo:** `src/skills/specialist_skill/miner.py:277+341`
- **Sintoma:** `ZeroDivisionError` quando `cached["median"] = 0`.
- **Causa:** branch `use_cache` não validava mediana > 0.
- **Fix (commit `73a1986`):**
  ```python
  mediana_canal = cached.get("median", 0)
  if mediana_canal <= 0:
      log.warning(f"[specialist_skill] Cache de mediana inválido (<=0) para {url} — pulando canal")
      return [], cost
  ```
- **Lição:** sempre valide dados lidos de cache antes de usar em divisão.

#### F-03: dashboard.py bare `except:` cláusulas
- **Arquivo:** `src/channels/telegram/commands/dashboard.py:282,369,414,427`
- **Sintoma:** 4 cláusulas `except:` catch-all capturavam `SystemExit`, `KeyboardInterrupt`.
- **Causa:** `except:` é equivalente a `except BaseException:`, que captura sinais de shutdown.
- **Fix (commit `21e8e80`):** substituir `except:` por `except Exception:`
- **Lição:** **SEMPRE** use `except Exception:` em código de aplicação. `except:` é armadilha.

#### F-04: reporter.py NO-OP HTML replace
- **Arquivo:** `src/core/analytics/reporter.py:210-212`
- **Sintoma:** código morto (`.replace("<b>", "<b>")` substitui string por ela mesma).
- **Causa:** copy-paste incompleto.
- **Fix (commit `b94ffd8`):** deletar 3 linhas + retornar HTML direto.
- **Lição:** `replace(old, new)` onde `old == new` é red flag em code review. Lint deve pegar isso.

#### F-05 (Wave 1 audit): emergency_stop sem persistência
- **Arquivo:** `src/core/goals/manager.py:357`
- **Fix:** adicionar persistência em SQLite, sobrevive restart.

#### F-06 (Wave 1): vault shadowing
- **Arquivo:** `src/skills/knowledge_vault/facade.py`
- **Fix:** corrigir path collision entre VaultSearcher e KnowledgeVault.

#### F-07 (Wave 1): GCP service account exposta
- **Arquivo:** `Credenciais/service-account.json.json`
- **Status:** Nunca foi pro GitHub, mas existia em feature branches.
- **Fix:** documentado em `docs/GCP_SERVICE_ACCOUNT_ROTATION_RUNBOOK.md` (commit `4306e00`).
- **Plano 17/07:** **DELETAR** o arquivo físico (não-rotated).

---

### Wave 2 (P1 — Imports & Auth) — 16/07/2026

| F-ID | Descrição | Fix |
|---|---|---|
| F-08 | S.A.R.A path traversal em `goal.py` | Sanitização de inputs antes de passar a `subprocess` |
| F-09 | `os.kill` sem auth check em `executor/actions.py` | Whitelist de PIDs permitidos |
| F-10 | `executor_crew.py` bypassava shell | `shell=False` + argparse de argumentos |
| F-11 | `file_ops.py` quebrava em Windows path com espaços | Usar `shlex.quote()` ou list args |
| F-12 | FTS5 UPDATE sem trigger de timestamp | Trigger `AFTER UPDATE` para `updated_at` |
| F-13 | `GoalStatus.RUNNING → IDLE` travava goal | Reset atômico em shutdown |
| F-14 | `events.py` async sqlite sem `aiosqlite` | Migrar para `aiosqlite` (done) |
| F-15 | `analyst_crew.py` facts sem validação | Type-check + Zod-style schema |

---

### Wave 3 (P2 — Refactor estrutural) — 16/07/2026

| F-ID | Descrição | Fix |
|---|---|---|
| F-16 | `MembersOnlyStderrFilter` duplicado | Centralizado em `core/logging_secure.py` |
| F-17 | `BASH_WHITELIST` em 3 lugares | Constante única em `core/safety_layer_enhanced.py` |
| F-18 | `ExecutorPolicy` alias deprecated | Substituído por `SafetyGate` |
| F-19 | Paths hardcoded `data/` / `logs/` | Variáveis de ambiente `DATA_DIR`, `LOG_DIR` |
| F-20 | `SessionStore` sem WAL pragmas | Adicionar `journal_mode=WAL`, `busy_timeout=5000` |
| F-21 | CRM store foreign keys sem CASCADE | `ON DELETE CASCADE` + índices |
| F-22 | Goals antigos sem TTL | Auto-eviction após 30 dias `paused` |
| F-23 | error_database sem WAL | Migrar para WAL mode |
| F-24 | evolver.py deletava goals ativos | Whitelist + confirmação |
| F-25 | TimeoutError custom overshadowed stdlib | Renomeado para `SeekerTimeoutError` |
| F-26 | SARA handler duplicado | Removido do commands/system.py (mantido em skills/) |

---

### Bug Crítico Pós-Audit (Wave 4)

#### SharedRateLimitBreaker — HTTP 429 ignora threshold
- **Arquivo:** `src/core/rate_limiting/shared_breaker.py:227-263` (pré-fix)
- **Sintoma:** circuit breaker abria na **primeira** falha 429, sem respeitar `consecutive_threshold`.
- **Causa:** código lia `data[backend]["consecutive_failures"]` ANTES de incrementar, e aplicava cooldown sem checar threshold.
- **Fix:**
  ```python
  data[backend]["consecutive_failures"] += 1
  failures = data[backend]["consecutive_failures"]
  if failures >= self.consecutive_threshold:
      base_cooldown = min(self.cooldown_seconds * (2 ** (failures - self.consecutive_threshold)), 3600)
      # ...
  ```
- **Test flaky:** `test_cooldown_expires` esperava 2.1s mas jitter pode adicionar até 0.18s. Ajustei para 3.0s.
- **Lição:** ao consertar, validar com teste real (test tinha assumido comportamento incorreto).

---

### Bugs do ViralX9 e Test Time-Bomb

#### specialist_skill `test_mine_canal_integration` time-bomb
- **Sintoma:** teste dependia de `datetime.now()` mas usava upload_date hardcoded `20260618`.
- **Em 13/07/2026** (data de hoje): passava porque delta era 25 dias < 14 dias.
- **Em 17/07/2026**: delta seria 30 dias > 14 dias → falha.
- **Fix:**
  - `miner.py:150-175`: `_hours_since(upload_date, now=None)` agora aceita `now` opcional.
- **Lição:** testes com data devem mockar `datetime.now()`. Freeze time é o padrão.

---

## 3. Code Review (16/07/2026)

### CR-01 (Critical): async mismatch em dead code
- **Local:** `src/core/goals/scheduler.py:390-450` — `_get_next_priority_goal()` era sync, mas chamava `_should_execute_goal()` que virou async.
- **Risco:** se alguém futuramente ativá-lo, retornaria corotina em vez de bool → preemption bypass.
- **Fix:** deletar método inteiro (dead code não usado).
- **Commit:** `4db8152`

### WR-01: dead code (mesmo que CR-01)
### WR-02: EventBus sem cleanup
- **Local:** `src/core/events.py`
- **Fix:** adicionado `shutdown(timeout=1.0)` que cancela tasks pendentes. Wired em `pipeline.shutdown()`.
- **Commit:** `4db8152`

### WR-04: `except Exception:` swallow CancelledError
- **Local:** `src/core/goals/scheduler.py:601` (pré-fix)
- **Sintoma:** task cancel não propagava, goal continuava rodando durante shutdown.
- **Fix:**
  ```python
  except asyncio.CancelledError:
      raise
  except Exception as e:
      # ...
  ```
- **Commit:** `4db8152`
- **Lição:** em código asyncio, SEMPRE tratar `CancelledError` separadamente.

### IN-01/02/03: documentação/comentários
- IN-01: cascade.py — comentar que `epsilon` é baseado em `total_updates` (não `_n_predicts`)
- IN-02: pipeline.py — comentar split core-vs-skills no Capability Graph
- IN-03: miner.py — `_hours_since` agora documenta `now` como testing hook
- **Commit:** `232ffc7`

---

## 4. Insight Waves (Wave 4)

### Insight 1 — Memory Decay
- **Local:** `src/core/evidence/decay.py`
- **O quê:** adicionada limpeza de `episodic` (>30 dias) e `goal_cycles` (manter últimos 20).
- **Por quê:** `skill_telemetry.jsonl` chegou a 2.97 GB. Sem decay, memória cresce sem limite.
- **Config:** `ttl_days=30, goal_cycles_keep=20`.

### Insight 2 — Goal Health Score
- **Local:** `src/core/goals/scheduler.py`
- **O quê:** score 0-100 baseado em falhas consecutivas + ciclo success rate. Auto-pause se < 30.
- **Persistência:** `_health_score` salvo no JSON de estado, sobrevive restarts.

### Insight 3 — SOUL.md hot-reload
- **Local:** `src/core/memory/soul_watcher.py` (NOVO)
- **O quê:** poller de mtime a cada 30s. Dispara callback em mudança.
- **Cuidado Windows:** `watchdog` (inotify) não funciona → usar `os.path.getmtime()` polling.
- **Integração:** `pipeline.init()` + `pipeline.shutdown()`.

### Insight 4 — Exploration Budget RL (epsilon-greedy)
- **Local:** `src/core/rl/bandits/cascade.py:305-318`
- **O quê:** LinUCB tem exploração estrutural via UCB, mas echo chamber persistia (alpha=1.0 decaindo rápido demais). Adicionado epsilon-greedy forçado em SHADOW mode.
- **Epsilon decay:** 0.20 → 0.05 (após 1000 updates).
- **Log:** debug mostra quando força random arm.

### Insight 5 — Event Bus pub/sub
- **Locais:** `src/core/events.py` + integração em:
  - `src/core/goals/scheduler.py`: emite `goal.started`, `goal.completed`, `goal.failed`, `goal.paused`, `goal.resumed`
  - `src/skills/email_monitor/goal.py`: emite `email.started`, `email.completed`, `email.failed`
  - `src/skills/specialist_skill/goal.py`: emite `specialist_skill.started`, `specialist_skill.events_found`, `specialist_skill.completed`
- **Pattern:** todas as integrações usam `try/except: pass` para garantir que falha do event bus não quebra o caminho crítico.

### Insight 6 — Capability Graph com auto-registro
- **Local:** `src/core/capability_graph.py` (NOVO) + `src/skills/__init__.py` (auto-registro)
- **Pattern de uso:** skill importa + registra capabilities no import.
- **Status:** Graph existe mas ainda não usado por nenhum planner (futuro).

---

## 5. Substituição de Modelos (Free Tiers Jul/2026)

### Fontes de pesquisa (15/07/2026)
- `E:\Arquivos desenvolvimento\freetiers_apis.md` (manual consolidado)
- `https://platform.moonshot.ai/docs/pricing/chat` (Kimi K2.6 confirmado)
- `https://docs.x.ai/docs/models` (Grok 4.5 atualizado)
- `https://github.com/googleapis/python-genai/blob/main/README.md` (Gemini API key format)

### Removidos do `config/models.py`

| Modelo antigo | Modelo novo | Motivo |
|---|---|---|
| `MOONSHOT_KIMI_V1` (`moonshot-v1-32k`) | `MOONSHOT_KIMI_K2_6` (`kimi-k2.6`) | EOL 25/05/2026 + Kimi K2.6 é atual |
| `GROQ_LLAMA` (`llama-4-scout`) | `GROQ_GPT_OSS_120B` (`openai/gpt-oss-120b`) | EOL 17/07/2026 (Llama-4-Scout) |
| `GROQ_LLAMA_70B` (`llama-3.3-70b`) | `GROQ_QWEN_3_6_27B` (`qwen/qwen3.6-27b`) | EOL 16/08/2026 |
| `NVIDIA_NEMOTRON_ULTRA` (Llama-3.1 253B) | `NVIDIA_NEMOTRON_3_ULTRA` (`nemotron-3-ultra-550b-a55b`) | Modelo antigo, novo MoE 1M ctx |
| `NVIDIA_QWQ_32B` | `NVIDIA_QWEN_3_5_397B` (`qwen3.5-397b-a17b`) | qwq-32b EOL, substituído por 397B |

### Adicionados ao `config/models.py` (10 novos)

| Provider | Modelo | Rate Limit | Custo |
|---|---|---|---|
| NVIDIA NIM | `nvidia/nemotron-3-ultra-550b-a55b` | 40 RPM | Free |
| NVIDIA NIM | `qwen/qwen3.5-397b-a17b` | 40 RPM | Free |
| Groq | `openai/gpt-oss-120b` (Reasoning) | 30 RPM | Free |
| Groq | `qwen/qwen3.6-27b` (Multimodal) | 30 RPM | Free |
| Groq | `openai/gpt-oss-safeguard-20b` (safety) | 30 RPM | Free |
| Z.ai | `glm-4.7` (recomendado, free permanente) | 10 RPM | **$0 real** |
| Z.ai | `glm-4.5` (alternativa, free permanente) | 10 RPM | **$0 real** |
| OpenRouter | `tencent/hy3:free` (Tier A, 295B MoE) | 20 RPM | Free |
| OpenRouter | `openai/gpt-oss-20b:free` (Tier S) | 20 RPM | Free |
| Cohere | `embed-v4` (trial 1K/mês) | 20 RPM | Trial |

### Cadeia final priorizando free

```
FAST:    Gemini 3.1 Lite → Z.ai 4.7-Flash → Groq gpt-oss-120b → Cerebras → DeepSeek V4 Flash
DEEP:    NVIDIA V4 Pro → Nemotron-3 Ultra 550B → DeepSeek V4 Pro (pago) → Gemini 2.5 Flash → OpenRouter gpt-oss-20b
JUDGE:   Gemini 3.1 Lite → Gemini 2.5 Flash → Z.ai 4.7-Flash → Groq gpt-oss-120b → Cerebras
SYNTH:   Gemini 3.1 Lite → Gemini 2.5 Flash → Cerebras Zai-GLM 4.7 → Z.ai 4.7-Flash → DeepSeek V4 Flash
ADV:     NVIDIA Gemma 4 31B → Groq Qwen 3.6 27B → Gemini 2.5 Flash → OpenRouter tencent/hy3 → Z.ai 4.7-Flash
LOCAL:   Ollama Gemma 4 → Ollama Qwen3.5 → Z.ai 4.5-Flash → Gemini 3.1 Lite
EMBED:   Gemini Embedding 2 → Cohere Embed v4 (trial)
```

---

## 6. Limpeza & Reconciliação (17/07/2026)

### Itens órfãos confirmados com evidência

Cada um validado por grep cross-package + reverse-engineering via test runner.

#### Categoria A — Substitutos disponíveis (substituir, não deletar)
| Item | Substituto em produção |
|---|---|
| `core/logging_config.py` (2.3 KB) | `core/logging_secure.py` (4.4 KB, ativo) |
| `core/safety_layer.py` (7.4 KB) | `core/safety_layer_enhanced.py` (8.2 KB, importado em `pipeline.py:60`) |
| `core/exceptions_handler.py` (5.9 KB) | `core/utils.py` (2.9 KB, ativo) |
| `core/evidence/storage.py` | `core/memory/store.py` (31 KB, ativo) |

#### Categoria B — Sistema hierarchy/ nunca ativado
8 arquivos. Sistema LangGraph + 6 crews planejado, não conectado em `pipeline.py`:
- `supervisor.py`, `interfaces.py`, `crew_router.py`
- 5× `crews/{admin,analyst,executor,hunter,vision}_crew.py`
- Todos têm `TODO: Implement X logic` ou referências internas.

#### Categoria C — Sub-módulos órfãos em skills ativas
- `bug_analyzer/{analyzer,context_collector}.py` (mantidos: `models.py`, `telegram_interface.py`)
- `specialist_skill/{crawl_extract,demand_signal}.py` (mantidos: `goal.py`, `query.py`, `date_parser.py`)
- `knowledge_vault/analyzer.py` (mantido: `facade.py`, `vault_searcher.py`)
- `os_control/file_ops.py` (mantido: `launcher.py`, usado em `deliberate.py`)
- `vision/{glm_ocr_client,task_classifier,vlm_cloud_fallback,vlm_router}.py` (mantidos: 9 outros)
- `opportunity_matcher/` INTEIRO — skill morta (110 B em `goal.py`)

#### Categoria D — Reconciliação `config/.env`
15 chaves LLM/providers presentes. Fluxo correto:
- **XAI_API_KEY** é usada via `x_search` (direto) + `specialist_skill.trend_signal` (indireto via `_x_mentions_count` chamando `XSearcher`).
- **GEMINI_API_KEY** formato atual (`AQ.Ab8RN6...`) é **OAuth ADC** — funciona mas expira. AIza clássica é mais estável.
- **KIMI_API_KEY** apontando para `moonshot-v1-32k` (EOL) — atualizar `models.py` para `kimi-k2.6`.

### Espaço antes/depois
- **Antes:** ~6.5 GB (runtime + downloads + agent)
- **Depois:** ~1.1 GB (só runtime essencial)
- **Tracking:** -8 arquivos desatualizados via `git rm`

---

## 7. Problemas Conhecidos (TODOs)

### 7.1 Em código (atualmente órfão, mas marcados TODO)

```
src/core/hierarchy/crews/admin_crew.py:17:  # TODO: Implement admin logic
src/core/hierarchy/crews/vision_crew.py:17: # TODO: Implement vision logic
src/core/executor/handlers/remote_trigger.py:75: # TODO: implementar health check via API
src/core/executor/handlers/remote_trigger.py:84: # TODO: implementar delegação via API
```

### 7.2 Em código (vital, próximos passos)

- **`src/skills/specialist_skill/`** — gitignored mas pesado (51 KB `scout.py` + 40 KB `miner.py`). CRM store crítico, manter.
- **`src/skills/specialist_skill/`** — gitignored, mas útil. Manter.
- **`src/skills/cortex/`** — gitignored. Pode ser órfão. **Verificar.**

### 7.3 Em dependências externas

- **Python 3.10 EOL 2026-10-04** (Google API Core). Plano de migração em `docs/PYTHON_MIGRATION_PLAN.md`.
- **Gemini API AIza clássica recomendada** (atual é ADC OAuth com expiração).
- **Z.ai free tier requer ativação no painel** (status 1113 sem recarga).

---

## 8. Padrões de Correção Recorrentes

### 8.1 "Parear com substituto antes de deletar"
- Antes de deletar qualquer arquivo, SEMPRE grep cross-package para confirmar:
  - `from src.X.Y import Z`
  - `from src.X import Y`
  - Auto-registro via `__init__.py`
- Se houver **substituto superior** (verificar LastWriteTime + commits recentes), migrar antes.

### 8.2 "Tests replicados = deletar o mais recente"
- `smoke_cache_phase*.py` (4 arquivos, 26 KB) são duplicados de `integration_phase*.py`.
- **Regra:** se `smoke_*` foi escrito depois de `integration_*`, deletar smoke.

### 8.3 "Logs > 30 dias = comprimir ou deletar"
- Logs de agent podem inflar indefinidamente.
- **Regra:** implementar `RotatingFileHandler(maxBytes=50MB, backupCount=3)` em produção.
- **Já feito em**: `bot.py:698` (handler configurado).

### 8.4 "git rm antes de deletar se arquivo é tracked"
- Para arquivos tracked (git status mostra), `git rm` move para staging e remove do working tree.
- Para arquivos untracked, `rm` direto.
- Confirme status com `git ls-files path`.

### 8.5 "Sempre adicionar teste + rodar suite antes do commit"
- Cada fix deve ter teste (mesmo que mínimo).
- Suite completa: `python -m pytest tests/ -q --tb=line --ignore=tests/test_instascraper.py --ignore=tests/test_instascraper_adversarial.py --ignore=tests/test_instascraper_stress.py --ignore=tests/test_verify_caches.py`
- Threshold: 181+ testes passando antes de cada commit.

### 8.6 "Backups de DB antes de deletar"
- Antes de deletar `seeker_memory.db.v3_migrate_bak`:
  ```bash
  cp data/seeker_memory.db.bak data/backup_$(date +%Y%m%d).db
  ```
- Manter backup local por 30 dias.

### 8.7 "Validar equivalência de substitutos"
- Substituto é "igual ou superior" quando:
  - Tem mesma interface pública
  - Tem testes ativos
  - Tem LastWriteTime mais recente que o original
  - É importado em código vital (`pipeline.py`, `bot.py`)

---

## 9. Histórico de Commits (auditoria 14-17/07/2026)

| Commit | Descrição |
|---|---|
| `0d7cfee` | fix(models): usar IDs reais Z.ai (glm-4.5/glm-4.7) |
| `ead268b` | refactor(models): alinhar config/models.py com free tiers jul/2026 |
| `232ffc7` | docs(review): resolve IN-01/IN-02/IN-03 |
| `4db8152` | fix(review): resolve CR-01/WR-01/WR-02/WR-04 |
| `89f133b` | docs(00): code review report |
| `71cbb0d` | fix(docs): resolve F-09 — refresh stale deepseek-v3.2 references |
| `b94ffd8` | fix(reporter): resolve F-04 — remove NO-OP html.replace() calls |
| `21e8e80` | fix(dashboard): resolve F-03 — bare except clauses |
| `73a1986` | fix(specialist_skill): resolve F-02 — division by zero |
| `6afdb60` | fix(scheduler): resolve F-01 — result=None AttributeError |
| `4306e00` | docs(security): add F-07 GCP service account rotation runbook |

Padrão de commit messages: `fix|docs|feat|refactor(scope): resolve F-ID — description`

---

## 10. Métricas Finais

| Categoria | Quantidade |
|---|---:|
| Bugs corrigidos (Waves 1-4) | 26 (F-01 → F-26) |
| Bugs extras (audit-fix) | 4 (F-shared-429, etc.) |
| Code Review findings | 8 (CR-01, WR-01..04, IN-01..03) |
| Modelos substituídos | 5 (EOL) |
| Modelos adicionados | 10 (free tiers jul/2026) |
| Skills registradas no Capability Graph | 16 |
| Event topics emitidos | 9+ (`goal.started`, `message.received`, etc.) |
| Testes criados (Wave 4) | 9 (`test_wave4_insights.py`, `test_wave4_integration.py`) |
| Testes totais | **181 passando**, 0 falhando (17/07/2026) |
| Espaço total a liberar (17/07/2026) | **~5.4 GB** runtime |

---

## 11. Lições Consolidadas

1. **Cross-package grep SEMPRE**: heuristic "não é importado" falha em singletons, decorators, e auto-registro via `__init__.py`.
2. **`except Exception:` SEMPRE**: `except:` captura `BaseException` incluindo sinais de shutdown.
3. **Testes com `datetime.now()` precisam de mock**: senão viram time-bombs.
4. **Comentários explícitos sobre AIza vs ADC**: Gemini API aceita múltiplos formatos agora (Google Gen AI SDK).
5. **Substituir antes de deletar**: quando há código equivalente em produção, migrar primeiro.
6. **Validar free tier status via HEAD /models**: Z.ai tem chave válida mas requer ativação no painel.
7. **Circuit breaker deve respeitar threshold**: decremento antes de incremento causava abertura prematura.
8. **Disconnect em propagação de cancelation**: em código asyncio, `CancelledError` deve sempre `raise` antes do catch genérico.
9. **Logs rotacionam sozinhos**: implementar `RotatingFileHandler` em produção, não confiar em cleanup manual.

---

## 12. ShowDeck — Briefing Diário (otimização 20/07/2026)

### Problema reportado

Recebemos briefings diários sempre com **as mesmas 5 indicações** (centenários do PR/RS), apesar de termos **12.000+ cadastros** no CRM. Janela de 4-8 meses e status NOVO/CONTATADO estavam certas, mas os mesmos leads apareciam repetidamente.

### Causa raiz

Auditoria em `src/skills/specialist_skill/goal.py` revelou quatro bugs combinados:

1. **Heurísticas muito permissivas**: `round_anniversary_bonus` (`+20`) detecta "centenário" em qualquer nome de evento + `window_freshness_bonus` (`+10`) sempre que está em 5-6m → todos os leads do mesmo período recebem a mesma pontuação base (55).

2. **Sem diversidade por cidade**: o `top = briefable[:TOP_N]` simplesmente pega os N melhores por score. Se 5 leads da mesma cidade têm scores similares, todos entram.

3. **Sem histórico de exibição**: o `_last_runs` só guardava o date, não os `target_key`s. Logo, todo dia o mesmo top 5 era selecionado.

4. **Sem penalidade por dados faltantes**: leads sem `decisor_nome` ou sem contato recebiam o mesmo score que leads completos.

### Fixes implementados (commit `449637e`)

#### 1. Anti-repetição (novo)
```python
# Track dos últimos 7 dias por target_key
self._recently_shown: dict[str, set[str]] = {}

def _recently_shown_keys(self, run_id: str) -> set[str]:
    """Retorna target_keys mostrados nos últimos N dias (TTL)."""
    keys = set()
    today = date.fromisoformat(run_id)
    for i in range(1, self._recently_shown_ttl_days + 1):
        past = (today - timedelta(days=i)).isoformat()
        keys.update(self._recently_shown.get(past, set()))
    return keys

# No run_cycle:
recent_keys = self._recently_shown_keys(run_id)
fresh_briefable = [ld for ld in briefable if ld["target_key"] not in recent_keys]
if fresh_briefable:
    briefable = fresh_briefable
```

Estado serializado (`serialize_state`/`load_state`) preserva histórico entre restarts.

#### 2. Diversidade por cidade
```python
# Garante ≥3 cidades diferentes no top 5 quando possível
briefable.sort(key=lambda x: x["_priority"]["score"], reverse=True)
top = []
cities_seen: set[str] = set()
for ld in briefable:
    if len(top) >= self.TOP_N:
        break
    city = ld.get("cidade") or "?"
    if city not in cities_seen or len(cities_seen) < 3:
        top.append(ld)
        cities_seen.add(city)
```

#### 3. Penalidade por falta de dados
```python
for ld in briefable:
    score = ld["_priority"]["score"]
    motivos = list(ld["_priority"]["motivos"])

    if not decisor_nome:
        score -= 10
        motivos.append("sem decisor identificado (penalidade -10)")
    if not has_contato:
        score -= 5
        motivos.append("sem contato disponível (penalidade -5)")

    ld["_priority"]["score"] = max(0, score)
    ld["_priority"]["motivos"] = motivos
```

### Impacto

Antes (exemplo real, 20/07/2026):
- 5 leads idênticos todos os dias: Centenário-RS, Quarto Centenário-PR, etc.
- Score sempre 55, sem variação
- 0 diversidade por cidade (todas PR/RS)
- Sem incentivo para enrichment de dados

Depois:
- Top 5 rotativo a cada 7 dias (sem repetir)
- ≥3 cidades diferentes quando possível
- Leads com decisor identificado sobem ao topo
- Sem contato/decisor: penalidade visível na justificativa do briefing

### Lição consolidada

**Quando você tem um briefing diário que parece estagnado:**
1. Verifique se há histórico de exibição (anti-repetição)
2. Adicione diversidade (cidade, estado, tipo de evento)
3. Penalize falta de dados (incentiva enrichment)
4. Audite o **scoring** — heurísticas cumulativas (BANT + bônus) podem mascarar diversidade

---

## 13. Próximos Passos Recomendados

1. **Curto prazo (1 semana):**
   - Migrar Python para 3.12 (EOL Google API Core 2026-10-04)
   - Substituir `GEMINI_API_KEY` por AIza clássica
   - Ativar free tier no painel Z.ai

2. **Médio prazo (1 mês):**
   - Implementar planner que consuma Capability Graph
   - Adicionar EventBus subscribers em skills restantes (knowledge_vault, brief, etc.)
   - Migrar logs para `RotatingFileHandler` programático

3. **Longo prazo (3 meses):**
   - Conectar `hierarchy/supervisor.py` ou deletar de vez
   - Auto-rotacionar chaves API com failover (multi-key pool)
   - Implementar cost ceiling automático por turno + por dia

---

**Última atualização:** 20/07/2026 (adição da otimização ShowDeck)
**Mantenedor:** Victor (`4pixeltech@gmail.com`)
**Próxima revisão:** mensal (auditoria de regressão de free tiers)
