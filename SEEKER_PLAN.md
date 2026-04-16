# 🎯 Seeker.Bot — Plano Arquitetural Canônico

**Estado Atual:** Operacional (Sprints 1–5 completas, Operations Phases 1–3 em operação)  
**Atualizado:** 2026-04-16  

---

## 📐 Arquitetura do Sistema

### Níveis Implementados

```
┌─────────────────────────────────────────────────────────┐
│         Control Plane (Telegram + Admin UI)              │
│                                                           │
│  ├─ Chat Manager (Input Processing)                      │
│  ├─ Command Router                                       │
│  └─ Output Formatter (Notifications)                     │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│        Orchestration & Goal Dispatch                     │
│                                                           │
│  ├─ Goal Registry (skills)                              │
│  ├─ Budget Manager                                       │
│  ├─ Cycle Scheduler                                      │
│  └─ Result Aggregator                                    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│     Autonomous Goals (Skills & Subsystems)               │
│                                                           │
│  ├─ 🔍 Vision 2.0 (A1–A4)                              │
│  │   └─ VLM Routing (Qwen3-VL:8b + GLM-OCR)            │
│  │                                                       │
│  ├─ 🎯 Scout Hunter 2.0 (C1–C5)                        │
│  │   ├─ Discovery Matrix (Fit Score)                    │
│  │   ├─ Account Research (Company Deep-Dive)            │
│  │   ├─ Qualification (BANT)                            │
│  │   ├─ Copywriting (Contextual)                        │
│  │   └─ Metrics (5-phase pipeline)                      │
│  │                                                       │
│  ├─ ⚙️ Remote Executor (B1–B5)                          │
│  │   ├─ Bash Handler                                    │
│  │   ├─ File Operations Handler                         │
│  │   ├─ API Handler                                     │
│  │   ├─ Orchestrator                                    │
│  │   └─ Safety Gates                                    │
│  │                                                       │
│  └─ 🗓️ Scheduler Conversacional (NEW)                  │
│      ├─ Wizard (State Machine)                          │
│      ├─ Store (SQLite)                                  │
│      ├─ Calculator (Next Run)                           │
│      ├─ Dispatcher (Execution)                          │
│      └─ Telegram Interface                              │
│                                                           │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│    Core Services & Infrastructure                        │
│                                                           │
│  ├─ Execution Plane (Side Effect Gateway)               │
│  ├─ Approval Engine                                      │
│  ├─ Evidence Layer (Audit Logs)                         │
│  ├─ LLM Cascade (6-tier)                                │
│  ├─ Memory Store (SQLite)                               │
│  ├─ Providers (NVIDIA, Groq, Gemini, DeepSeek, Ollama) │
│  └─ Providers Configuration                             │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

---

## 🗓️ Scheduler Conversacional — Módulo Canônico

### Objetivo
Permitir criação, edição, pausa, reativação e execução de tarefas agendadas através de um **wizard conversacional guiado** integrado ao Telegram.

### Componentes

| Componente | Responsabilidade |
|-----------|-----------------|
| **Wizard** | State machine para coleta de dados (título → periodicidade → hora → instrução) |
| **Store** | Persistência SQLite de tarefas, execuções, sessões do wizard |
| **Calculator** | Cálculo de próxima execução respeitando timezone |
| **Dispatcher** | Executa tarefas vencidas, registra resultados, mantém idempotência |
| **Telegram Interface** | Comandos e conversa com usuário |
| **Autonomous Goal** | Polling (5 min) + dispatch automático |

### Periodicidades Suportadas
- **DAILY**: Diária na hora especificada
- **WEEKLY**: Semanal (especificar dia da semana)
- **MONTHLY**: Mensal (especificar dia do mês)
- **ANNUAL**: Anual (especificar dia/mês)

### Fluxo Conversacional
```
/agendar
  ↓
📝 Título?
  ↓
⏰ Frequência? (1=Daily, 2=Weekly, 3=Monthly, 4=Annual)
  ↓
📅 Complemento? (dia semana / dia mês / dia+mês)
  ↓
🕐 Hora? (0-23)
  ↓
📋 Instrução/Comando?
  ↓
✅ Confirmar? (sim/não)
  ↓
💾 Salvo! Próxima em: XX:XX
```

### Ações Mínimas
- `/agendar` — Inicia wizard
- `/listar` — Lista tarefas do chat
- `/detalhe <ID>` — Mostra detalhes
- `/pausar <ID>` — Pausa tarefa
- `/reativar <ID>` — Reativa tarefa
- `/remover <ID>` — Remove tarefa
- `/executar <ID>` — Executa agora
- `voltar`, `cancelar` — No wizard

### Integração com Execution Plane
- ✅ Tarefas agendadas respeitam **Side Effect Gateway**
- ✅ Tarefas mutáveis respeita **Approval Engine**
- ✅ Cada execução registra **evidence** (quando aplicável)
- ✅ **Sem bypass** de políticas de segurança

### Observabilidade
Cada execução registra:
- `task_id`, `scheduled_for`, `started_at`, `finished_at`
- `status` (success/failed/timeout), `error`
- `execution_id` (link para ExecutionRecord)

### Segurança
- ❌ Nenhuma credencial armazenada em tarefa
- ❌ Nenhum bypass de approval/policy
- ✅ Idempotência por `task_id + scheduled_timestamp`
- ✅ Wizard expira em 30 min
- ✅ Um wizard ativo por chat

---

## 📊 Histórico de Implementação

### Sprints Completas
- **Sprint 1–5**: Base do Seeker, skills básicas
- **Sprint 11**: Cascade de 6-tier, otimizações

### Phases Operacionais
- **Phase 1**: Scraping + Enrichment (✅ Prod)
- **Phase 2**: Discovery Matrix + Account Research (✅ Prod)
- **Phase 3**: Qualification + Copy (✅ Prod, validação visual pendente)

### Modules em Operação
1. **Vision 2.0** (A1–A4) — VLM routing + GLM-OCR specialist
2. **Scout Hunter 2.0** (C1–C5) — B2B lead generation completo
3. **Remote Executor** (B1–B5) — Execução com segurança
4. **Scheduler Conversacional** (NEW) — Tarefas agendadas via Telegram

---

## 🚀 Roadmap Futuro

**Não planejado agora**, mas possível:
- Integração com webhooks (triggers externos)
- Recorrência complexa (ex: "3ª segunda do mês")
- Inputs dinâmicos no wizard
- Dashboard visual (além de Telegram)
- Retry automático com backoff

---

## 📝 Notas Arquiteturais

1. **Modularidade**: Cada componente tem responsabilidade clara
2. **Testabilidade**: Sem acoplamento direto, fácil mockar
3. **Persistência**: SQLite, migrations automáticas via schema
4. **Timezone**: `America/Sao_Paulo` default, customizável
5. **Budget**: Tarefas agendadas custam mínimo (0.01 USD/ciclo)

