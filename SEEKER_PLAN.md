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

## 🐛 Bug Analyzer — Módulo de Análise Automática

### Objetivo
Analisar bugs relatados pelo usuário coletando contexto (chat + logs), processando com LLM especializado (Coder Agent), e sugerindo correções automáticas com aprovação antes da aplicação.

### Fases de Implementação

#### **Phase 1: Análise Básica** ✅ (Implementada)
- Comando `/bug` coleta descrição do usuário
- Intercepta últimas 5 mensagens do chat
- Coleta últimas 25 linhas do log (seeker.log)
- Detecta padrões de erro via regex
- Identifica arquivos afetados em stack traces
- Envia contexto formatado para modelo Coder (DEEP role)
- Modelo retorna análise JSON com:
  - Root cause (causa raiz)
  - Findings (achados com severity)
  - Suggestions (sugestões de correção com risk level)
- Exibe análise ao usuário em HTML formatado

#### **Phase 2: Aprovação + Aplicação** (Em Roadmap)
- `/bug_approve` revisa sugestões
- Backup automático via Git antes de aplicar
- Aplica patches um-a-um com rollback option
- Valida cada mudança (testa import, etc)
- Registra todas as mudanças em evidence

#### **Phase 3: Auto-Healing Diário** (Em Roadmap)
- Monitoramento passivo de logs
- Detecção de padrões recorrentes
- Auto-correção para bugs conhecidos
- Dashboard de correções aplicadas

### Componentes

| Componente | Responsabilidade |
|-----------|-----------------|
| **ContextCollector** | Coleta chat + logs, detecta padrões de erro |
| **BugAnalyzer** | LLM análise com cascade (DEEP role) |
| **BugReport** | Estrutura para contexto coletado |
| **BugAnalysis** | Estrutura para resultado da análise |
| **Telegram Interface** | Wizard + comandos |
| **Models** | Dataclasses (Report, Analysis, Finding, Suggestion) |

### Fluxo do Usuário (Phase 1)

```
/bug
  ↓
"Descreva o bug..."
  ↓
Usuário: "Bot não reinicia quando há crash"
  ↓
⏳ Coletando contexto...
  ├─ Últimas 5 mensagens
  ├─ Últimas 25 linhas do log
  ├─ Detecção de padrões de erro
  └─ Identificação de arquivos afetados
  ↓
🤖 Analisando com Coder Agent (DeepSeek V3.2 via NIM)...
  ↓
📊 Análise Completa
  ├─ 🎯 Causa Raiz: "watchdog.py timeout > HEARTBEAT_TIMEOUT"
  ├─ 🔎 Achados: 3 findings (critical, high, medium)
  └─ 💡 Sugestões: 1 fix suggestion (arquivo, código, risk)
  ↓
/bug_approve  (Phase 2)
```

### Modelo Coder (DEEP Role Cascade)

Configurado em `config/models.py` CognitiveRole.DEEP:
1. **NVIDIA Nemotron Ultra 253B** (40 RPM, grátis, default)
2. **NVIDIA QwQ 32B** (40 RPM, grátis, fallback reasoning)
3. **NVIDIA DeepSeek V3.2 via NIM** (40 RPM, grátis, especialista em código)
4. **DeepSeek Chat API** ($0.28/$0.42, pago, último fallback)
5. **Gemini 3 Flash** (5 RPM/20 RPD, backup)

Temperature: 0.3 (determinístico para análise)
Max tokens: 2048

### Detecção de Padrões

O ContextCollector identifica automaticamente:
- **Error patterns**: "ERROR:", "EXCEPTION:", "FAILED:", "FATAL:"
- **Stack traces**: Extrai caminhos de arquivos `.py`
- **Warnings**: "WARNING:", "WARN:", "DEPRECATED:"
- **Timestamps**: Sincroniza com log timestamps

### JSON Output do Modelo

```json
{
  "root_cause": "watchdog.py timeout > HEARTBEAT_TIMEOUT",
  "summary": "O bot não escreve heartbeat e watchdog o mata",
  "findings": [
    {
      "category": "timeout_issue",
      "severity": "critical",
      "description": "Scheduler travado, não atualiza heartbeat",
      "affected_file": "src/core/goals/scheduler.py",
      "confidence": 0.9
    }
  ],
  "suggestions": [
    {
      "file_path": "src/core/goals/scheduler.py",
      "current_code": "# Sem heartbeat update no loop",
      "suggested_code": "self._write_heartbeat()  # A cada ciclo",
      "explanation": "Permitir watchdog detectar freezes corretamente",
      "risk_level": "low"
    }
  ]
}
```

### Ações Mínimas (Phase 1)

- `/bug` — Inicia análise
- `/bug_cancel` — Cancela análise em curso
- `/bug_approve` — Aprova sugestões (Phase 2, mostra preview)

### Integração com Cascade

Reutiliza `pipeline.cascade_adapter` com modelo_role=CognitiveRole.DEEP.
Cada análise registra:
- Custo em USD (modelo usado)
- Latência em ms
- Modelo selecionado pela cascade

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
4. **Scheduler Conversacional** — Tarefas agendadas via Telegram
5. **Bug Analyzer** (Phase 1) — Análise automática com Coder Agent

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

