# 🐛 Bug Analyzer — Guia Operacional

**Estado Atual:** Phase 1 Completa (Análise Básica)  
**Atualizado:** 2026-04-16  
**Próximo:** Phase 2 (Aprovação + Aplicação de Patches)

---

## 📋 Resumo Executivo

O **Bug Analyzer** permite que você reporte bugs através do Telegram, e o sistema:
1. Coleta contexto automaticamente (últimas 5 mensagens + 25 linhas de log)
2. Detecta padrões de erro via regex
3. Identifica arquivos afetados
4. Envia para análise com **Coder Agent** (DeepSeek V3.2 via NIM)
5. Retorna análise com causa raiz + sugestões de correção

---

## 🚀 Como Usar

### Iniciando uma Análise

```
/bug
```

**O Bot Responde:**
```
🐛 Bug Analyzer Seeker.Bot

Descreva o bug que você encontrou:

Ex: 'O bot não está reiniciando quando há crash' ou 
'Email monitor retorna caixa vazia mas há emails novos'

Digite sua descrição (próxima mensagem será considerada como contexto).
```

### Fornecendo a Descrição

```
Bot não reinicia após crash no scheduler
```

**O Bot Coleta Contexto:**
```
⏳ Coletando contexto...

Analisando chat, logs e identificando padrões de erro...
```

### Resultados da Análise

```
🔍 Análise de Bug Completa
Modelo: nvidia/llama-3.3-nemotron-super-49b-v1.5
Fase: complete

🎯 Causa Raiz:
watchdog.py está matando bot por timeout > HEARTBEAT_TIMEOUT

📋 Sumário:
O scheduler.py não atualiza o heartbeat regularmente, 
fazendo o watchdog pensar que o bot travou.

🔎 Achados (2):
🔴 timeout_issue: watchdog matando bot por inatividade (scheduler.py)
🟠 heartbeat_missing: Scheduler não escreve em logs/bot_heartbeat.txt

💡 Sugestões de Correção (1):
1. src/core/goals/scheduler.py
   Risco: low
   Explicação: Adicionar _write_heartbeat() no loop principal do scheduler

💰 Custo: $0.0012 | ⏱️ 2341ms

Próximos passos:
/bug_approve — Avaliar e aplicar correções
/bug_cancel — Descartar análise
```

### Cancelando uma Análise

```
/bug_cancel
```

---

## 🔧 Modelo Coder (DEEP Role Cascade)

A análise usa a cascade de modelos **DEEP** configurada em `config/models.py`:

| Ordem | Modelo | RPM Limit | Free? | Fallback |
|-------|--------|-----------|-------|----------|
| 1 | NVIDIA Nemotron Ultra 253B | 40 | ✅ | Sim (principal) |
| 2 | NVIDIA QwQ 32B | 40 | ✅ | Sim |
| 3 | NVIDIA DeepSeek V3.2 via NIM | 40 | ✅ | Sim |
| 4 | DeepSeek Chat API | ∞ | ❌ | Sim ($0.28/$0.42) |
| 5 | Gemini 3 Flash | 5/20 | ✅ | Último recurso |

**A cascata garante:**
- ✅ Análise sempre completa (nunca falha por rate limit em free tier)
- ✅ Modelo melhor disponível sempre selecionado
- ✅ Fallback automático para pago se necessário
- ✅ Budget respeitado (max 0.01 USD/ciclo para bug analysis)

**Temperature:** 0.3 (determinístico para análise de código)  
**Max Tokens:** 2048

---

## 🔍 O Que o Bug Analyzer Detecta

### Padrões de Erro Automaticamente

```
✅ ERROR: [mensagem]
✅ EXCEPTION: [tipo de erro]
✅ FAILED: [operação]
✅ FATAL: [descrição]
✅ WARNING: [alerta]
✅ DEPRECATED: [função]
```

### Stack Traces

Extrai automaticamente arquivos Python de stack traces:
```python
File "src/core/goals/scheduler.py", line 123, in run_cycle
```

### Identificação de Arquivos Afetados

1. Lê as últimas 25 linhas do `logs/seeker.log`
2. Procura por caminhos `.py` em stack traces
3. Detecta padrões de erro
4. Lista arquivos no contexto enviado para análise

---

## 📊 JSON Response do Modelo

O modelo retorna análise estruturada em JSON:

```json
{
  "root_cause": "scheduler.py não atualiza heartbeat",
  "summary": "Watchdog detecta inatividade e mata bot",
  "findings": [
    {
      "category": "timeout_issue",
      "severity": "critical",
      "description": "watchdog matando bot",
      "affected_file": "src/core/goals/scheduler.py",
      "confidence": 0.9
    }
  ],
  "suggestions": [
    {
      "file_path": "src/core/goals/scheduler.py",
      "current_code": "# Missing code",
      "suggested_code": "self._write_heartbeat()",
      "explanation": "Permitir watchdog detectar corretamente",
      "risk_level": "low"
    }
  ]
}
```

---

## 🎯 Fluxo Detalhado (Internamente)

```
1. /bug command
   └─> BugAnalyzerTelegramInterface.cmd_bug()
       └─> Inicia BugWizardState.ASKING_DESCRIPTION

2. User fornece descrição
   └─> process_bug_input()
       └─> ContextCollector.collect_context()
           ├─> Processa chat history
           ├─> Coleta terminal output (últimas 25 linhas)
           ├─> Detecta error patterns via regex
           ├─> Identifica affected files
           └─> Retorna BugReport

3. Enviando para análise
   └─> BugAnalyzer.analyze_bug()
       ├─> Formata BugReport como texto
       ├─> Cria prompt de análise
       ├─> Chama cascade_adapter.call()
       │   └─> Tenta DEEP role cascade (5 tiers)
       ├─> Parseia resposta JSON
       └─> Retorna BugAnalysis

4. Exibindo resultados
   └─> BugAnalysis.get_summary_text()
       └─> Formata em HTML para Telegram
```

---

## ⚠️ Limitações (Phase 1)

- ❌ **Sem aplicação automática** — Mostra sugestões, não aplica
- ❌ **Sem Git backup** — Phase 2 implementará
- ❌ **Sem validação de patches** — Phase 2 implementará
- ❌ **Sem approvals** — Phase 2 implementará
- ❌ **Sem auto-healing diário** — Phase 3 implementará

---

## 🔐 Segurança

### O Que é Seguro

✅ Contexto coletado é apenas **leitura** (não modifica nada)  
✅ Chat history e logs são **análise apenas**  
✅ Nenhuma credencial ou secret é incluído  
✅ Phase 2 incluirá **approval gate** antes de qualquer mudança

### O Que Precisa de Cuidado (Phase 2+)

⚠️ Patches aplicados devem ter **rollback** preparado  
⚠️ Git deve estar limpo antes de aplicar  
⚠️ Implementar **idempotência** para re-run seguro

---

## 📈 Métricas & Observabilidade

Cada análise registra:

```python
analysis.analysis_cost_usd        # Custo da API
analysis.analysis_latency_ms      # Tempo de resposta
analysis.model_used               # Modelo selecionado (cascata)
analysis.phase                    # Estado (COMPLETE)
len(analysis.findings)            # Número de achados
len(analysis.suggestions)         # Número de sugestões
```

**Como monitorar:**
```python
# No log do Seeker
[bug_analyzer] Análise completa: 3 achados, 1 sugestão
[bug_analyzer] Custo: $0.0012 | Latência: 2341ms | Modelo: nemotron-ultra
```

---

## 🧪 Testando Localmente

```bash
# Teste unitário
python -m pytest tests/test_bug_analyzer_integration.py -v

# Teste manual (sem Telegram)
python3 << 'EOF'
import asyncio
from src.skills.bug_analyzer import ContextCollector

async def test():
    collector = ContextCollector()
    report = await collector.collect_context(
        "Bot não reinicia",
        [{"timestamp": "10:00", "text": "crash", "is_user": True}]
    )
    print(f"Contexto coletado: {len(report.terminal_output)} linhas")

asyncio.run(test())
EOF
```

---

## 🚀 Phase 2 Preview (Roadmap)

Quando implementada, `/bug_approve` fará:

1. **Git Backup**
   ```bash
   git checkout -b bug-fix-{task_id}
   git add -A && git commit -m "Pre-fix backup"
   ```

2. **Aplicar Patches**
   ```python
   for suggestion in analysis.suggestions:
       if suggestion.risk_level == "low":
           apply_patch(suggestion)
       else:
           request_approval(suggestion)
   ```

3. **Validar Mudanças**
   ```bash
   python -m py_compile [arquivo]  # Syntax check
   python -m pytest tests/ -q      # Roda testes
   ```

4. **Reportar Resultados**
   ```
   ✅ 1 patch aplicado com sucesso
   ⚠️ Teste 1 falhou — revertendo...
   🔗 Branch: bug-fix-abc123
   ```

---

## 🛠️ Troubleshooting

### "Email Monitor não foi encontrado"
→ Algum goal não foi inicializado. Execute `/saude` para debug.

### "Erro ao testar email monitor: [error]"
→ Verifique `logs/seeker.log` para détails. Pode ser IMAP connection issue.

### Análise retorna "Erro na análise: timeout"
→ Cascade tentou todos os 5 tiers e todos timed out. Verifique conectividade de rede.

### Logs/seeker.log não existe
→ Crie: `mkdir -p logs && touch logs/seeker.log`

---

## 📞 Suporte

Para mais detalhes, consulte:
- [SEEKER_PLAN.md](SEEKER_PLAN.md) — Arquitetura completa
- [src/skills/bug_analyzer/](src/skills/bug_analyzer/) — Código-fonte
- [tests/test_bug_analyzer_integration.py](tests/test_bug_analyzer_integration.py) — Exemplos de uso
