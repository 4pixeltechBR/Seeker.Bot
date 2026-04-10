# Implementation Decisions — Vision 2.0 + Remote Executor

**Data:** 2026-04-10  
**Status:** ✅ Confirmadas e prontas para implementação  
**Sequência:** Vision 2.0 (Semanas 1-2) → Remote Executor (Semana 3+)

---

## Decision 1: AFK Window Policy

### Configuração
```
L2_SILENT (leitura):      execute 24h/24 (anytime)
L1_LOGGED (escrita):      execute até 12h AFK, depois escalate
L0_MANUAL (perigoso):     pausa, aguarda user approval
```

### Implementação
- **Config file:** `config/.env`
- **Env var:** `AFK_WINDOW_L1_HOURS=12`
- **Default:** 12 horas (ajustável via env)

### Lógica
```python
# Em src/core/executor/afk_protocol.py
if action.tier == "L1_LOGGED":
    afk_time = now() - user_last_seen
    if afk_time > AFK_WINDOW_L1_HOURS:
        escalate_telegram(action)  # notify user
        return  # pause execution
    else:
        execute()  # auto-execute
elif action.tier == "L2_SILENT":
    execute()  # always
elif action.tier == "L0_MANUAL":
    pause_and_await_approval()  # always require approval
```

---

## Decision 2: L0 Approval Timeout + Retry Logic

### Timeline
```
T+0 min   → Action paused, Telegram notification sent
T+5 min   → Timeout 1: auto-reject, log, notify user
T+35 min  → Retry 1: re-ask user in Telegram
T+40 min  → Timeout 2: auto-reject, log, notify user
T+65 min  → Retry 2: final chance, re-ask user
T+70 min  → Timeout 3 FINAL: auto-reject action, cancel
          → Audit log: "Action cancelled after 3 rejections"
```

### Implementação
```python
# Em src/core/executor/afk_protocol.py
APPROVAL_MAX_RETRIES = 3
APPROVAL_TIMEOUT_SEC = 300  # 5 min
APPROVAL_RETRY_DELAY_MIN = 30  # refaz pergunta em 30 min

async def wait_for_approval(action_id, max_retries=3):
    for attempt in range(1, max_retries + 1):
        try:
            approval = await telegram_callback(
                action_id,
                timeout=APPROVAL_TIMEOUT_SEC
            )
            if approval:
                return True  # user approved
            else:
                return False  # user rejected
        except TimeoutError:
            if attempt < max_retries:
                logger.info(f"Retry {attempt}: refazendo pergunta em 30min")
                await sleep(APPROVAL_RETRY_DELAY_MIN * 60)
            else:
                logger.error(f"Final timeout: cancelando action {action_id}")
                return False
    
    return False  # all retries exhausted
```

### Telegram Inline Buttons
```python
buttons = [
    {"text": "✅ Approve", "callback": "approve:{action_id}"},
    {"text": "❌ Reject", "callback": "reject:{action_id}"},
    {"text": "⏰ Snooze 30m", "callback": "snooze:{action_id}"}
]
```

---

## Decision 3: RemoteTrigger Integration

### Status: ZERO existente, criar do zero em Phase B2

Resultado da exploração:
- ❌ Nenhuma implementação de RemoteTrigger encontrada
- ❌ Nenhuma integração com Claude Code API (`/v1/code/triggers`)
- ✅ Seeker já tem robusto local Goal Scheduler (10 goals autônomos)

### Responsabilidade
- **Fase B2:** Implementar novo `RemoteTriggerHandler` 
- **Arquivo:** `src/core/executor/handlers/remote_trigger.py`
- **Funcionalidade:**
  - Health check Claude Code availability (every 30s)
  - Delegação de desktop actions (screenshot, click, type, window control)
  - Timeout 5 min por delegação
  - Fallback to local bash se Claude Code offline

### Arquitetura
```
ActionExecutor (Phase B3)
  ↓
if action.type == "remote_trigger":
  RemoteTriggerHandler.execute(action)
    ├─ Check Claude Code health
    ├─ Call /v1/code/triggers/{id}/run API
    ├─ Poll for completion (5 min timeout)
    └─ Fallback to local bash if offline
```

---

## Decision 4: Logging Pattern

### Decisão: **Usar logging pattern existente**

**Razão:** Gera menos fricção + mantém mesmo padrão

### Pattern Existente (confirmado em codebase)
```python
# Padrão em Seeker.Bot
import logging

logger = logging.getLogger("seeker.{module_name}")

# Uso
logger.info(f"[{self.name}] Status: {status}")
logger.error(f"[{goal_name}] Erro: {error}", exc_info=True)
logger.debug(f"[executor] Planning action: {action}")
```

### Será aplicado em:
- `src/core/executor/models.py` → `logger = logging.getLogger("seeker.executor")`
- `src/core/executor/orchestrator.py` → `logger = logging.getLogger("seeker.executor.orchestrator")`
- `src/core/executor/handlers/*.py` → `logger = logging.getLogger("seeker.executor.handlers")`
- `src/skills/remote_executor/*.py` → `logger = logging.getLogger("seeker.remote_executor")`

### Config
- **Log level:** Lido de `config/.env` (LOG_LEVEL)
- **Format:** Herdado de logger global (sem override)
- **Audit logs:** Separado em `data/executor/audit.jsonl` (JSON para máquina-parsing)

---

## Próximas Etapas

### Immediate (antes de começar Fase A1)
- ✅ Decisões confirmadas
- ✅ Plan file salvo: `C:\Users\Victor\.claude\plans\quiet-gathering-crescent.md`
- ✅ Implementation decisions documentadas aqui
- ⏭️ Próximo: Kickoff Vision 2.0 Fase A1

### Vision 2.0 Roadmap
```
Semana 1:
├─ A1: Config refactor VLM_MODEL (1h)
├─ A2: Benchmark harness (3h)
└─ Dataset collection (2h)

Semana 2:
├─ A3: Run benchmarks 4 models (2.5h)
└─ A4: Decide + deploy + Gemini fallback (2h)
```

### Remote Executor Roadmap
```
Semana 2-3:
├─ B1: Core datastructures (2h)
├─ B2: Action handlers (3h, RemoteTrigger aqui)
└─ B3: Orchestrator + Safety (3h)

Semana 3:
├─ B4: Remote Executor Goal (2h)
└─ B5: Testing + validation (2.5h)
```

---

## Sign-Off

- **Planejador:** Claude (AI)
- **Aprovador:** Victor (usuário)
- **Data aprovação:** 2026-04-10
- **Status:** ✅ PRONTO PARA IMPLEMENTAÇÃO

