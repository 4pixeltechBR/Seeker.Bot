# 📋 Seeker.Bot — Plano Operacional

**Versão:** 1.0  
**Atualizado:** 2026-04-16  
**Status:** Em Operação (Fases 1–3) + Scheduler Conversacional (Novo)

---

## 📊 Fases de Operação

### Phase 1: Scraping + Enrichment
- **Status:** ✅ Produção
- **Ciclo:** Contínuo (5-10 min entre batches)
- **Monitoramento:** Verificar taxa de erro em scraping via logs
- **Alertas:** Se taxa_erro > 15%, pausar provisoriamente

### Phase 2: Discovery Matrix + Account Research
- **Status:** ✅ Produção  
- **Ciclo:** Processamento de descobertas em tempo real
- **Monitoramento:** Pontuação média de Fit Score, tempo de pesquisa
- **Alertas:** Se Fit Score médio cair 20%+, revisar critérios

### Phase 3: Qualification + Copywriting
- **Status:** ✅ Produção (validação visual pendente)
- **Ciclo:** Processamento de contas qualificadas
- **Monitoramento:** Taxa de aprovação BANT, qualidade de copy (viés manual)
- **Alertas:** Se aprovação BANT < 30%, revisar critérios de qualification

### Phase 4: Scheduler Conversacional
- **Status:** ✅ Novo (Sprint 11)
- **Ciclo:** 5 minutos (polling de tarefas vencidas)
- **Monitoramento:** Tarefas executadas, taxa de sucesso, tempo de execução
- **Alertas:** Se falha_rate > 20%, investigar task instruction ou provider

---

## 🎯 Procedimentos Operacionais

### 1. Criar Tarefa Agendada

**Canal:** Telegram (`/agendar`)  
**Fluxo:**
```
1. Usuário: /agendar
2. Bot: "Nome da tarefa?"
3. Usuário: "Backup diário"
4. Bot: "Frequência? (1=Daily, 2=Weekly, 3=Monthly, 4=Annual)"
5. Usuário: "1"
6. Bot: "Hora? (0-23)"
7. Usuário: "14"
8. Bot: "Instrução/Comando?"
9. Usuário: "Executar backup do banco de dados"
10. Bot: "Confirmar? (sim/não)"
11. Usuário: "sim"
12. Bot: "✅ Tarefa agendada! Próxima execução: 14:00"
```

**Validações:**
- Nome: 3–100 caracteres
- Frequência: 1/2/3/4 (válido)
- Hora: 0–23 (inteiro válido)
- Instrução: 5–1000 caracteres

### 2. Listar Tarefas do Chat

**Canal:** Telegram (`/listar`)  
**Saída:**
```
📋 Tarefas ativas:

ID: task_123 | Backup diário
├─ Frequência: Diária (14:00)
├─ Status: ✅ Ativa
├─ Próxima: 2026-04-16 14:00
└─ Última execução: 2026-04-15 14:02 (sucesso)

ID: task_456 | Relatório semanal
├─ Frequência: Semanal (ter 10:00)
├─ Status: ⏸ Pausada
├─ Próxima: 2026-04-22 10:00
└─ Última execução: 2026-04-08 10:05 (sucesso)
```

### 3. Ver Detalhes de Tarefa

**Canal:** Telegram (`/detalhe <ID>`)  
**Exemplo:** `/detalhe task_123`

**Saída:**
```
🔍 Detalhes: Backup diário

ID: task_123
Frequência: Diária às 14:00 (UTC-3 America/Sao_Paulo)
Status: ✅ Ativa
Instrução: Executar backup do banco de dados
Criada em: 2026-04-15 10:30
Última execução: 2026-04-15 14:02
Próxima execução: 2026-04-16 14:00
Sucessos: 5 | Falhas: 0
```

### 4. Pausar Tarefa

**Canal:** Telegram (`/pausar <ID>`)  
**Efeito:** Task marcada como PAUSED; não executará até reativação.  
**Confirmação:** "✅ Tarefa pausada. Use /reativar para reativar."

### 5. Reativar Tarefa

**Canal:** Telegram (`/reativar <ID>`)  
**Efeito:** Task marcada como ENABLED; voltará à fila de execução.  
**Confirmação:** "✅ Tarefa reativada. Próxima execução em: XX:XX"

### 6. Remover Tarefa

**Canal:** Telegram (`/remover <ID>`)  
**Efeito:** Task e todos seus runs deletados; irreversível.  
**Confirmação:** "✅ Tarefa removida (task_123)."

### 7. Executar Agora

**Canal:** Telegram (`/executar <ID>`)  
**Efeito:** Executa tarefa imediatamente fora do schedule.  
**Comportamento:**
```
1. Encontra tarefa
2. Incrementa idempotency key (timestamp atual)
3. Chama cascade com instruction_text
4. Registra resultado (success/failed)
5. Recalcula próximo run normal (não muda schedule)
```

**Confirmação:** "⏱️ Executando task_123... Resultado: ✅ Sucesso"

### 8. Cancelar Wizard (Mid-Flow)

**Channel:** Telegram (`cancelar` ou `voltar` → último passo)  
**Efeito:** Wizard session deletada, sem task criada.  
**Confirmação:** "❌ Wizard cancelado."

---

## 🔄 Ciclo de Execução Automática

**Frequency:** A cada 5 minutos  
**Executor:** SchedulerConversacional (Autonomous Goal)

### Passo-a-Passo

1. **Cleanup Wizard Sessions** (< 1s)
   - Remove sessões expiradas (30+ min sem atividade)
   - Log: `[scheduler] Cleaned up N expired wizard sessions`

2. **Find Overdue Tasks** (< 100ms)
   - Query: `SELECT * FROM scheduler_tasks WHERE next_run_at <= NOW AND is_enabled = true`
   - Retorna lista de tarefas vencidas

3. **Execute Each Task** (N × avg_instruction_time)
   
   Para cada tarefa:
   ```
   a. Check idempotency (previne duplicação)
   b. Create run record (status=PENDING)
   c. Call cascade adapter with instruction_text
   d. Record result (success/failed/timeout)
   e. Update task.last_run_at, .failure_count, .last_error
   f. Recalculate next_run_at (respeitando periodicidade + timezone)
   g. Save run + updated task
   ```

4. **Return Stats**
   ```json
   {
     "found": 2,
     "executed": 2,
     "skipped": 0,
     "failed": 0,
     "errors": []
   }
   ```

5. **Send Telegram Notification** (se executed > 0)
   ```
   ✅ **Scheduler — Ciclo Completo**
   
   Executadas: 2
   Puladas: 0
   Erros: 0
   ```

---

## ⚠️ Tratamento de Erros

### Scenario 1: Instrução inválida
```
Task: "echo test && rm -rf /"
Resultado: Cascade rejeita (Side Effect Gateway)
Ação: Task marcada com failure_count++, last_error = "Blocked by approval engine"
Próxima exec: Conforme schedule (não pula)
```

### Scenario 2: Timeout de execução
```
Timeout: 30s (configurável)
Ação: Cria run com status=failed, último_erro="Timeout"
failure_count++
Próximo retry: No próximo ciclo (se ativo)
```

### Scenario 3: Cascade indisponível
```
Erro: ConnectionError ao chamar cascade
Ação: failure_count++, last_error armazenado
Retry: Automático no próximo ciclo (sem backoff)
Alerta: Se failure_count > 5, notifica usuário
```

### Scenario 4: Idempotência detectada
```
Situação: Task executada duas vezes no mesmo minuto (por erro de timing)
Proteção: (task_id + scheduled_for_timestamp) é chave única
Resultado: 2ª tentativa falha com "Idempotency violation"
Log: Não incrementa failure_count (é erro de framework, não de tarefa)
```

---

## 📊 Métricas de Monitoramento

### KPIs Diárias

| Métrica | Alvo | Ação se Violar |
|---------|------|--------|
| Task Success Rate | > 95% | Investigar provider/cascade |
| Avg Execution Time | < 5s | Revisar instruction complexity |
| Wizard Completion Rate | > 80% | A/B test prompts |
| Scheduler Availability | > 99.5% | Verificar DB conexão |

### Logs a Monitorar

```bash
# Ver execuções de hoje
grep "scheduler" /var/log/seeker.log | grep "2026-04-16"

# Ver erros
grep "scheduler" /var/log/seeker.log | grep "ERROR"

# Ver estatísticas por goal
grep "scheduler_conversacional" /var/log/seeker.log | tail -100
```

### Queries de Diagnóstico

```sql
-- Tarefas com mais falhas
SELECT task_id, COUNT(*) as failures
FROM scheduler_task_runs
WHERE status = 'failed'
GROUP BY task_id
ORDER BY failures DESC
LIMIT 10;

-- Tempo médio de execução por tarefa
SELECT task_id, AVG(CAST(finished_at - started_at AS FLOAT)) as avg_time_sec
FROM scheduler_task_runs
WHERE finished_at IS NOT NULL
GROUP BY task_id;

-- Tarefas próximas de vencer nos próximos 10 min
SELECT id, title, next_run_at
FROM scheduler_tasks
WHERE is_enabled = true
AND next_run_at BETWEEN NOW AND NOW + INTERVAL '10 minutes'
ORDER BY next_run_at;
```

---

## 🔒 Segurança Operacional

### Policies Enforced

1. **No Bypass of Approval Engine**
   - Todos os commands passam por Side Effect Gateway
   - Instruções perigosas (rm -rf, DROP TABLE, etc.) são rejeitadas
   - Não há override manual

2. **Idempotency Protection**
   - Execução duplicada evitada via (task_id + timestamp) unique
   - Mesmo que dispatcher rode 2x, tarefa não roda 2x

3. **Wizard Session Timeout**
   - Sessão expira após 30 minutos de inatividade
   - Auto-cleanup a cada ciclo
   - Previne wizard "pendente" consumindo recursos

4. **Timezone Safety**
   - Default: America/Sao_Paulo (UTC-3)
   - Todas as comparações em UTC (storage)
   - Conversão para timezone usuário apenas na exibição

---

## 🚀 Procedimentos de Deploy

### 1. Registrar Goal no Pipeline

O scheduler é descoberto **automaticamente** via `discover_goals()`:

```python
# Em src/core/pipeline.py ou init_pipeline():
goals = discover_goals(pipeline, deny_list={"revenue_hunter"})
scheduler = [g for g in goals if g.name == "scheduler_conversacional"][0]
```

**Não requer mudança no código** — Auto-discovery cuida disso.

### 2. Ativar Telegram Commands

Adicionar ao command router do chatbot:

```python
# Em telegram_bot.py ou similar:
from src.skills.scheduler_conversacional.telegram_interface import SchedulerTelegramInterface

scheduler_ui = SchedulerTelegramInterface(store)

@bot.message_handler(commands=['agendar', 'listar', 'pausar', 'reativar', 'remover', 'executar'])
async def handle_scheduler_commands(message):
    cmd = message.text.split()[0][1:]  # Remove /
    chat_id = message.chat.id
    user_id = str(message.from_user.id)
    
    if cmd == 'agendar':
        msg = await scheduler_ui.cmd_agendar(chat_id, user_id)
    elif cmd == 'listar':
        msg = await scheduler_ui.cmd_listar(chat_id)
    # ... etc
    
    await bot.send_message(chat_id, msg)
```

### 3. Rodar Testes

```bash
# Todos os testes do scheduler
pytest tests/test_scheduler_wizard.py -v
pytest tests/test_scheduler_calculator.py -v
pytest tests/test_scheduler_integration_e2e.py -v

# Coverage
pytest tests/test_scheduler*.py --cov=src.skills.scheduler_conversacional
```

### 4. Validação Pré-Produção

```python
# Script de smoke test
from src.skills.scheduler_conversacional.store import SchedulerStore
from src.skills.scheduler_conversacional.dispatcher import TaskDispatcher
from src.skills.scheduler_conversacional.wizard import SchedulerWizard

# 1. Schema criado
store = SchedulerStore(db)
await store.init()  # ✅ Deve criar tabelas

# 2. Wizard funciona
wizard = SchedulerWizard(store)
session = await wizard.start_wizard(123, "test")  # ✅ Deve criar sessão

# 3. Dispatcher funciona
dispatcher = TaskDispatcher(store, cascade_mock)
stats = await dispatcher.dispatch_overdue_tasks()  # ✅ Deve retornar stats

print("✅ Scheduler ready for production")
```

---

## 📝 Checklist de Produção

- [ ] Schema SQLite criado (3 tabelas)
- [ ] Auto-discovery funciona (registry descobre scheduler_conversacional)
- [ ] Testes passam (wizard, calculator, E2E)
- [ ] Telegram commands registrados (/agendar, /listar, etc)
- [ ] Goal rodando ciclo a cada 5 min (verificar logs)
- [ ] Notifications funcionando (Telegram)
- [ ] Cascade adapter integrado (mock → real provider)
- [ ] Timezone padrão configurado (America/Sao_Paulo)
- [ ] Approval engine integrado (commands não bypassam)
- [ ] Backup de scheduler_tasks (incluir em rotina de backup diário)

---

## 🔮 Future Enhancements (Fora Escopo)

- Recorrência complexa (ex: "3ª segunda do mês")
- Webhook triggers (externos)
- Retry automático com backoff exponencial
- Dashboard visual (além de Telegram)
- Inputs dinâmicos no wizard
- Multi-timezone em single chat

