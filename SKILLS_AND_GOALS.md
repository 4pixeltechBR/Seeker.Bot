# 🎯 Seeker.Bot — Catálogo Completo de Skills e Goals

**Última atualização:** 12 de Abril de 2026  
**Status:** Sprint 12 (Vision 2.0)

---

## 📋 Índice

1. [Skills Autônomos (Goals)](#-skills-autônomos-goals)
2. [Skills de Suporte](#-skills-de-suporte)
3. [Mapa de Dependências](#-mapa-de-dependências)
4. [Budgets e Intervals](#-budgets-e-intervals)

---

## 🤖 Skills Autônomos (Goals)

### 1. **DailyNews / Briefing** 🔔
**Localização:** `src/skills/briefing/goal.py`

**Propósito:**  
Assistente pessoal diário que lê a caixa de entrada (emails UNSEEN) nos horários estipulados e entrega um resumo formatado em HTML via Telegram.

**Horários:**
- 07:30 AM
- 16:00 (4 PM)

**Fluxo:**
1. Fetch emails não lidos via IMAP
2. Estrutura contexto com até 15 emails
3. Passa pro LLM (CognitiveRole.SYNTHESIS) com sistema "Assistente Executivo"
4. Limpa markdown artifacts do LLM
5. Notifica via Telegram

**Budget:**
- Ciclo: $0.01 USD
- Diário: $0.05 USD

**Notificação:** Telegram (HTML formatado)

---

### 2. **Desktop Watch** 👁️
**Localização:** `src/skills/desktop_watch/goal.py`

**Propósito:**  
Vigilância autônoma da tela (AFK Protocol). Quando ativado via `/watch`, captura screenshots periódicos, analisa com VLM, e notifica quando detecta algo que exige intervenção humana.

**Comportamento:**
- **Desligado por padrão** (ativa com `/watch`, desativa com `/watchoff`)
- Interval: 120 segundos quando ativo, 300 segundos quando inativo
- Detecta: diálogos, erros, updates, permissões, avisos, timeouts
- **Circuit Breaker:** Auto-desativa após 3 falhas consecutivas

**Análise VLM:**
- Classifica `needs_attention: bool`
- Urgência: none | low | medium | high | critical
- Categoria: dialog | error | update | permission | notification | idle | normal
- Dedup: Não alerta 2x a mesma coisa (cooldown 5 min)

**Budget:** $0.00 (depende do Ollama local ou cloud fallback)

**Notificação:** Telegram com emoji de urgência + foto (opcional)

---

### 3. **Health Monitor** 🏥
**Localização:** `src/skills/health_monitor/goal.py`

**Propósito:**  
Monitora saúde física do servidor (CPU, RAM, Disco) e dependências críticas (Ollama).

**Checagens:**
- CPU > 95% → Alerta crítico
- RAM > 95% → Alerta com espaço livre em GB
- Disco C: < 4 GB → Alerta
- Disco (D/E/H): < 15 GB → Alerta
- **Ollama offline** → Auto-heal (máx 1x/4h) ou fallback cloud

**Interval:** A cada 30 minutos (1800 seg)

**Auto-Cura:**
```
Se Ollama cair:
  → Dispara "ollama serve" (one-off por 4h)
  → Registra timestamp do último restart
  → Envia notificação de auto-heal
```

**Budget:** $0.00 (local only)

**Notificação:** Telegram (só se houver alertas)

---

### 4. **Revenue Hunter** 🎯
**Localização:** `src/skills/revenue_hunter/goal.py` + `miner.py`

**Propósito:**  
Mineração B2B/B2G inteligente. Prospección autônoma em 3 fases: Discovery → Enrichment → Dossier com BANT Scoring.

**Campanhas:**
- **Regiões:** Goiânia, Brasília, Anápolis, SP, RJ, BH, Salvador
- **Nichos:** eventos, casamento, corporativo, agro, shows, conferências
- **Limite por ciclo:** 50 leads scraped, 30 processados

**Fases:**
1. **Scrape:** Busca em 6 fontes (Google, LinkedIn, Facebook, Instagram, MapSearch, EventPages)
2. **Enrichment:** Extrai phone, email, website, social
3. **BANT Qualification:** Budget, Authority, Need, Timeline scoring
4. **Copywriting:** Gera propostas customizadas por lead

**Funil:** Novo → Aprovado → Rejeitado

**Budget:**
- Ciclo: $0.15 USD
- Diário: $0.60 USD

**Interval:** A cada 4 horas (14400 seg)

**Output:** Dossiê PDF + notificação com estatísticas + ID da campanha

**Notificação:** Telegram + Console (ambos)

---

### 5. **SenseNews** 📰
**Localização:** `src/skills/sense_news/goal.py`

**Propósito:**  
Curadoria diária inteligente de notícias em nichos escolhidos. Agrupa temas, gera análise cruzada e entrega relatório PDF.

**Horário:** 10:00 AM

**Nichos Padrão:**
- Agro (🌾)
- Startups (🚀)
- Tech (💻)
- Política (🏛️)
- Economia (💰)
- Crypto (₿)

**Fluxo:**
1. Pick 3 queries aleatórias por nicho (injeta ano)
2. Search (max 5 resultados por query)
3. Deduplica por URL
4. LLM analisa (CognitiveRole.FAST) → JSON com título, análise, impacto
5. Mínimo 2 temas por nicho (warning se < 2)
6. LLM gera relatório consolidado (CognitiveRole.SYNTHESIS)
7. Build PDF
8. Atualiza histórico (dedup de títulos)

**Budget:**
- Ciclo: $0.15 USD
- Diário: $0.30 USD

**Output:** PDF em anexo + notificação com contagem por nicho

**Notificação:** Telegram com PDF attached

**Histórico:** Máx 200 temas (evita repetição)

---

### 6. **Scout Hunter** 🔍
**Localização:** `src/skills/scout_hunter/goal.py`

**Propósito:**  
Lead generation B2B avançado. Combina prospecting inteligente com 6 fontes, enrichment com AI, qualification BANT, e copywriting customizado.

**Configuração:**
- **Target Regions:** Goiânia, Brasília, Anápolis, etc.
- **Target Niches:** eventos, casamento, corporativo, agro, shows, conferências
- **Seleção:** Random por ciclo

**Fases:**
1. **Scrape Campaign:** Up to 50 leads por fonte
2. **Full Pipeline:** Enrich + Qualify + Copy (limit 30)
3. **Dashboard:** Funil com contagens

**Budget:**
- Ciclo: $0.15 USD
- Diário: $0.60 USD

**Interval:** A cada 4 horas

**Output:** Notificação com:
- Qualificados (BANT ≥ 7.0)
- Com copywriting pronto
- Rejeitados
- Campaign ID para `/crm`

**Notificação:** Telegram + Console

---

### 7. **Revenue Weekly Report** 📊
**Localização:** `src/skills/revenue_weekly/goal.py`

**Propósito:**  
Agrupa dossiês (PDFs) de leads gerados nos últimos 7 dias em um ZIP compactado e envia via Telegram.

**Horário:** Toda Segunda-feira às 08:00 AM

**Fluxo:**
1. Checa `data/leads/` por PDFs modificados < 7 dias atrás
2. Compacta em `Leads_Semana_YYYY_WW.zip`
3. Envia com notificação "Coletei X dossiês"

**Budget:** $0.00 (sem API calls)

**Output:** ZIP file (anexo)

**Notificação:** Telegram com ZIP attached

---

### 8. **Self Improvement / S.A.R.A** 🛠️
**Localização:** `src/skills/self_improvement/goal.py`

**Propósito:**  
Motor de auto-cura de código (S.A.R.A = Systematic Automatic Retrospective Analysis). Lê logs, detecta tracebacks, propõe correções e aplica patches automáticos.

**Modo de Operação:**
- **Interval:** A cada 12 horas OU após crash
- Lê arquivo de log (`logs/seeker.log`)
- Procura por `Traceback` ou `Exception`
- Extrai arquivo alvo do traceback
- Envia arquivo + traceback pro DeepSeek (CognitiveRole.DEEP)
- Recebe JSON com `rationale` e `full_code` corrigido
- **Aplicação:** Backup (.bak) + Overwrite

**Budget:**
- Ciclo: $0.20 USD
- Diário: $1.00 USD

**Segurança:**
- Valida que traceback aponta para arquivo local (`Seeker.Bot` no path)
- Cria backup automático antes de overwrite
- Envia notificação com raciocínio

**Output:** Arquivo corrigido + relatório de auto-heal via Telegram

**Notificação:** Telegram com raciocínio da correção

---

### 9. **Git Automation / Backup** 🐙
**Localização:** `src/skills/git_automation/goal.py`

**Propósito:**  
Controle de versão autônomo. Monitora mudanças, gera commits via LLM, e faz push automático.

**Horário:** A cada 6 horas (21600 seg)

**Fluxo:**
1. `git status -u --short` → Verifica mudanças
2. `git add .` → Stage todas
3. LLM gera mensagem (Conventional Commits) baseada em `git diff --staged --name-status`
4. `git commit -m "..."` com mensagem gerada
5. Push com:
   - **Primeira opção:** GitHub Token (env var) → `git push --force` com URL inline
   - **Fallback:** Credenciais nativas Windows (GCM)

**Segurança:**
- Token nunca persiste em `.git/config`
- Usa lista de args (sem shell=True) para evitar ps/logs exposure
- Redact token em logs de erro

**Budget:**
- Ciclo: $0.01 USD (só LLM message generation)
- Diário: $0.05 USD

**Output:** Notificação com commit message + status (local/remote)

**Notificação:** Telegram

---

### 10. **Email Monitor** 📬
**Localização:** `src/skills/email_monitor/goal.py`

**Propósito:**  
Monitoramento de inbox com triagem inteligente. Filtra ruído, agrupa informativos, e resuma urgentes.

**Horário:** 08:45 AM

**Triagem (Matriz 3x3):**
- 🔴 **URGENTE:** Requer ação humana (De | Assunto | Resumo | Ação)
- 🟡 **INFORMATIVO:** Útil ler (tópicos curtos)
- ⚪ **RUÍDO:** Marketing/newsletter (apenas COUNT + unsubscribe links)

**Fontes:**
- **Primary:** Gmail API (mais confiável)
- **Fallback:** IMAP Reader (Windows SSL compat)

**Filtros:**
- **Skip subjects:** unsubscribe, noreply, newsletter, alert, invoice, verify, etc.
- **Priority senders:** Configurável via `EMAIL_PRIORITY_SENDERS` env var
- **Dedup:** Rastreia email IDs já vistos (máx 1000)

**Budget:**
- Ciclo: $0.03 USD
- Diário: $0.10 USD

**Output:** Briefing formatado HTML + notificação Telegram

**Notificação:** Telegram

---

### 11. **Remote Executor** 🚀
**Localização:** `src/skills/remote_executor/goal.py`

**Propósito:**  
Executor multi-step autônomo com orquestração, segurança e AFK Protocol. Converte intenções em planos executáveis e monitora aprovações.

**Arquitetura:**
1. **Intent → Plan:** ActionOrchestrator gera ExecutionPlan via LLM
2. **Safety Gates:** Evalua contra SafetyGateEvaluator + ExecutorPolicy
3. **AFK Protocol:** L0_MANUAL actions enfileradas para aprovação
4. **Execution:** ActionExecutor processa L1_LOGGED / L2_SILENT
5. **Audit Trail:** Completo com timestamps e custos

**Tiers de Autonomia:**
- **L0_MANUAL:** Requer aprovação humana (inline buttons Telegram)
- **L1_LOGGED:** Executa com log completo
- **L2_SILENT:** Executa silenciosamente (sem notificação imediata)

**Fluxo de Aprovação:**
- Approval queue com timeout configurável
- Retry automático com escalation
- Notificação com inline buttons
- Tracking de respostas

**Budget:**
- Ciclo: $0.15 USD (configurável)
- Diário: $0.60 USD (configurável)

**Interval:** 300 segundos (configurável)

**Metrics Tracking (Sprint 11):**
- Plans criados
- Execuções bem-sucedidas/falhadas
- Latência total (ms)
- Distribuição de tiers

**Notificação:** Telegram com resumo de execução

---

### 12. **Vision / Desktop Controller** 👁️
**Localização:** `src/skills/vision/`

**Propósito:**  
Monitoramento visual com VLM. Captura screenshots, analisa com Claude Vision ou Ollama, e executa controles (mouse, keyboard, file ops).

**Componentes:**
- **screenshot.py:** Captura de tela via PIL (Windows 11 native)
- **vlm_client.py:** Integração com Ollama + cloud fallback (Claude Vision, Gemini)
- **mouse_engine.py:** Controle de mouse (move, click, drag)
- **keyboard_engine.py:** Controle de teclado (type, press, hotkeys)
- **browser.py:** Automação web
- **afk_protocol.py:** Detecção de presença
- **audit.py:** Log de todas as ações visuais

**Fallback VLM:**
1. Ollama local (1106:11434)
2. Claude Vision (via API)
3. Gemini Vision

**Output:** Contexto visual para decisões, screenshots com anotações

---

### 13. **Skill Creator** 🧬
**Localização:** `src/skills/skill_creator/`

**Propósito:**  
Meta-capacidade de criar novas skills dinamicamente. Programa, testa, e registra Goals autonomamente em linguagem natural.

**Fluxo:**
1. Usuário descreve novo skill em Telegram
2. LLM gera código Python (seguindo padrão AutonomousGoal)
3. Testa com `pytest`
4. Registra no Goal Registry
5. Notifica com resumo e comandos `/use`

**Saída:** Novo diretório em `src/skills/[nome]/` com:
- `goal.py` (AutonomousGoal implementation)
- `__init__.py`
- Opcionalmente: `prompts.py`, `config.py`, etc.

---

### 14. **Briefing Prompts & Utilities** 📝
**Localização:** `src/skills/briefing/prompts.py`

**Propósito:**  
Prompts centralizados para formatação HTML no Telegram. Usado pelo DailyNews e outros goals que enviam briefings.

**Saída:** HTML/Markdown formatado pro Telegram

---

## 🔧 Skills de Suporte

### Vision VLM Client
**Localização:** `src/skills/vision/vlm_client.py`

- Wrapper unificado para múltiplos VLM backends
- Ollama local (fallback prioritário)
- Claude Vision (fallback cloud)
- Health checks automáticos
- Singleton reutilizado entre ciclos

### Screenshot Engine
**Localização:** `src/skills/vision/screenshot.py`

- Captura de tela nativa Windows 11
- Formato: bytes PNG
- Sem permissões de sistema

### Desktop Automators
**Localização:** `src/skills/vision/{mouse,keyboard,browser,file_ops}.py`

- Mouse: move, click, drag, scroll
- Keyboard: type, hotkeys, special keys
- Browser: navegação, form fill, scraping
- File Ops: CRUD de arquivos

### AFK Protocol Coordinator
**Localização:** `src/skills/vision/afk_protocol.py`

- Detecta presença do usuário
- Gerencia approval queue
- Timeout + retry logic
- Escalonamento para human intervention

---

## 📊 Mapa de Dependências

```
Pipeline (SeekerPipeline)
├── GoalScheduler
│   ├── DailyNews (Briefing)
│   ├── Desktop Watch
│   ├── Health Monitor
│   ├── Revenue Hunter
│   ├── SenseNews
│   ├── Scout Hunter
│   ├── Revenue Weekly
│   ├── Self Improvement (S.A.R.A)
│   ├── Git Automation
│   ├── Email Monitor
│   ├── Remote Executor
│   │   └── ActionOrchestrator
│   │       └── LLM Router (Cascade)
│   │   └── ActionExecutor
│   │   └── AFKProtocolCoordinator
│   │   └── SafetyGateEvaluator
│   └── Skill Creator
│
├── Memory System (SQLite)
│   └── Fact Decay Engine
│   └── Reflexive Rules
│
├── Model Router (Cascade)
│   ├── NVIDIA NIM
│   ├── Groq (Fast)
│   ├── Gemini (Synthesis/Vision)
│   ├── DeepSeek (Deep)
│   └── Ollama (Local VLM)
│
└── Channels
    ├── Telegram
    └── Console
```

---

## 💰 Budgets e Intervals

### Budget por Ciclo (USD)

| Skill | Ciclo | Diário | Interval | Dias |
|-------|-------|--------|----------|------|
| **DailyNews** | $0.01 | $0.05 | 2x/dia | - |
| **Desktop Watch** | $0.00 | $0.00 | 2-5 min | ON/OFF |
| **Health Monitor** | $0.00 | $0.00 | 30 min | - |
| **Revenue Hunter** | $0.15 | $0.60 | 4h | - |
| **SenseNews** | $0.15 | $0.30 | 1x/dia | 10:00 |
| **Scout Hunter** | $0.15 | $0.60 | 4h | - |
| **Revenue Weekly** | $0.00 | $0.00 | 1x/semana | Segunda 08:00 |
| **Self Improvement** | $0.20 | $1.00 | 12h+ | - |
| **Git Automation** | $0.01 | $0.05 | 6h | - |
| **Email Monitor** | $0.03 | $0.10 | 1x/dia | 08:45 |
| **Remote Executor** | $0.15 | $0.60 | 5 min | ON-DEMAND |
| **Skill Creator** | Variable | Variable | ON-DEMAND | ON-DEMAND |

### Budget Total Recomendado
- **Mínimo Viável:** $3.00 USD/dia
- **Recomendado:** $5.00 USD/dia
- **Com Auto-scaling:** $10.00 USD/dia (picos de prospectação)

---

## 🎯 Goals Estratégicos (Alto Nível)

### Epistemologia & Cognição
✅ Sistema de memória reflexiva com decay temporal
✅ Multi-LLM cascade com fallbacks inteligentes
✅ AFK Protocol (detecção de presença e auto-pausa)

### Autonomia (Nível 5)
✅ Goals autônomos sem intervenção manual
✅ L0-L2 autonomy tiers com aprovação humana
✅ Auto-healing (S.A.R.A)

### Inteligência B2B/B2G
✅ Scout Hunter + Revenue Hunter (lead generation 24/7)
✅ BANT scoring e qualification automática
✅ Copywriting com persona customizada

### Observabilidade & Resiliência
✅ Health Monitor (recursos + dependências críticas)
✅ Fallback cascade (NVIDIA → Groq → Gemini → Ollama)
✅ Audit trail completo (Remote Executor)
✅ Circuit breakers (Desktop Watch, Health Monitor)

### Produtividade Pessoal
✅ DailyNews (inbox digest 2x/dia)
✅ Email Monitor (triagem inteligente)
✅ SenseNews (curadoria diária de notícias)
✅ Git Automation (versionamento automático)

---

## 📚 Documentação Relacionada

- **SPRINT_7_COMPLETION.md** — TF-IDF Search, Intent Card, OODA Loop
- **SPRINT_12_PROGRESS.md** — Vision 2.0, VLM upgrades
- **PHASE_2_IMPLEMENTATION_SUMMARY.md** — Monitor/Executor/Analyst crews
- **API_KEYS_VALIDATION_REPORT.md** — Provider setup

---

**Desenvolvido com ❤️ por Victor (VSJVB1208)**  
**Framework:** Python 3.12+ | Telegram-First | Self-Hosted
