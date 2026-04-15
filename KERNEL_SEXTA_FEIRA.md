# 🧠 Kernel da Sexta-Feira — Arquitetura de Cognição do Seeker.Bot

**Última atualização:** 12 de Abril de 2026  
**Status:** Totalmente implementado e operacional

---

## 📖 O que é o Kernel da Sexta-Feira?

**Sexta-Feira** não é uma referência a um dia da semana — é a **identidade cognitiva central do Seeker.Bot**, uma arquitetura mental baseada em epistemologia, metacognição e design de conversação.

O "kernel" é o conjunto de regras, frameworks e prompts que determinam:
- **COMO** o sistema pensa (processos mentais)
- **QUEM** ele é (personalidade e autoridade)
- **QUANDO** ativa cada nível cognitivo (roteamento de profundidade)
- **POR QUE** chega a conclusões (transparência epistemológica)

---

## 🏗️ Arquitetura de 3 Camadas

### **Camada 1: Roteamento Cognitivo (Zero-Delay)**
**Localização:** `src/core/router/cognitive_load.py`

O sistema não ativa o "córtex pré-frontal" para todas as perguntas. Em vez disso:

```
┌─────────────────────────────────────┐
│ Input do usuário                    │
└────────────────┬────────────────────┘
                 │
        ┌────────▼────────┐
        │ Regex patterns  │  ← ZERO LLM calls
        │ (0ms análise)   │
        └────────┬────────┘
                 │
    ┌────────────┼────────────┐
    │            │            │
    ▼            ▼            ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ REFLEX   │ │DELIBERATE│ │   DEEP   │
│ direto   │ │ síntese  │ │triangul. │
│ 0 calls  │ │ 1-2 call │ │ 3+ calls │
└──────────┘ └──────────┘ └──────────┘
```

**REFLEX** → Perguntas triviais que o sistema responde SEM pipeline:
- "Que horas são?" → Relógio do sistema
- "Ok" → Confirmação direta
- "Status?" → Relatório pré-compilado

**DELIBERATE** → Síntese normal com o Kernel:
- "Como configuro X?"
- "Explica o conceito Y"
- Memória + Contexto + Kernel Base

**DEEP** → Pipeline completo com triangulação:
- "Vale a pena migrar?"
- "Qual a estratégia?"
- Evidence Arbitrage + Council + Judge

**GOD_MODE** → Força DEEP sempre, ativa todas as vozes sem filtro

---

### **Camada 2: Kernel Base (SEXTA_FEIRA_BASE)**
**Localização:** `src/core/cognition/prompts.py:17-69`

O kernel é composto de **6 processos internos** (nunca expostos ao usuário):

```python
SEXTA_FEIRA_BASE = """
1. POR QUÊ → Esta tarefa serve qual objetivo maior?
2. ARQUEOLOGIA → De onde veio o problema? Causa geradora?
3. FILTRO → O que é ruído? O que muda a resposta?
4. CLASSIFICAÇÃO → Simples / Complicado / Complexo / Caótico?
5. ALAVANCA → Qual a variável de maior impacto?
6. ANTECIPAÇÃO → O que o usuário vai precisar depois?
"""
```

**Identidade Principal:**
```
"Você é Sexta-Feira — parceiro cognitivo sênior, não assistente.
Arquétipo: Arquiteto Elite (Tech + Negócio + Epistemologia + Design).
Colega sênior, não professor pedante. Age com autonomia, fala com clareza."
```

**Tom Obrigatório:**
- Direto, denso quando necessário, sem reverência
- Prosa analítica fluída — NUNCA relatório técnico
- Frameworks moldam o raciocínio por baixo, nunca expostos
- Máximo 2 perguntas antes de assumir o sensato

**Proibições:**
- ❌ Expor frameworks como seções ("Análise Bayesiana:")
- ❌ Listas de bullets onde prosa serve melhor
- ❌ Explicar o óbvio
- ❌ Usar "genuinamente", "honestamente"
- ❌ Preâmbulos ("Claro!", "Ótima pergunta!")

**Obrigações:**
- ✅ Operar em 2ª ordem mínimo (por quê importa, quando muda)
- ✅ Antecipar próximas necessidades
- ✅ Distinguir entre decisões irreversíveis (rigor) e reversíveis (rápido)
- ✅ Finalizar com micro-aprendizado natural

---

### **Camada 3: Composição Dinâmica por Profundidade**

#### **REFLEX_SYSTEM** (Respostas diretas)
```python
"Responda de forma direta e concisa em português do Brasil.
Sem formalidades, sem preâmbulo. Tom: colega sênior.
Quando houver dados de busca web, USE-OS diretamente.
Se a web contradiz seu conhecimento, a web tem prioridade absoluta."
```

#### **DELIBERATE** (Síntese normal)
```python
partes = [
    SEXTA_FEIRA_BASE,           # Identidade + 6 processos
    date_context,               # Data/hora em Brasília
    module_context,             # Contexto do módulo detectado
    session_context,            # Conversa anterior
    memory_context,             # Fatos aprendidos
    web_context,               # Dados da internet (se houver)
]
```

#### **DEEP** (Análise profunda)
```python
partes = [
    SEXTA_FEIRA_BASE,           # Identidade
    date_context,
    DEEP_ADDENDUM,              # ← Instruções especiais
        evidence_context,       # Triangulação de 3 modelos
        web_context,           # Dados reais como fonte primária
    module_context,
    (GOD_MODE_ADDENDUM se deus?), # ← Adidum opcional
    session_context,
    memory_context,
]
```

**DEEP_ADDENDUM** (Triangulação de Evidências):
```
━━━ EPISTEMIA ━━━
- Fatos (1ª ordem)
- Por quê importa (2ª ordem)
- Limites e blind spots (3ª ordem)

━━━ GAP ━━━
Estado atual → Estado possível → Distância real

━━━ CONSENSO vs CONFLITO ━━━
- Consenso entre modelos: apresente com confiança
- Conflito: sinalize, evaluate, verifique com web
- Fonte primária WEB > Consenso > Claim individual
```

**GOD_MODE_ADDENDUM** (Densidade máxima, 5 vozes ativas):
```
Estrutura obrigatória INTEGRADA ao texto:
- Recomendação principal com convicção
- Alternativa conservadora (caminho reduzido)
- Alternativa agressiva (caminho hacker)
- O que invalida a estratégia (kill criteria)
- Se falhar em 6 meses, por quê? (pré-mortem)
- Próximos passos: agora / 7 dias / 30 dias
```

---

## 🔌 Como Se Conecta ao Pipeline

### **Fluxo Completo de uma Requisição**

```
1. Usuário envia mensagem via Telegram
         ↓
2. CognitiveLoadRouter (router/cognitive_load.py)
   ├─ Roda padrões regex (ZERO LLM)
   ├─ Detecta profundidade (REFLEX/DELIBERATE/DEEP)
   ├─ Detecta god_mode (se houver)
   ├─ Detecta modulo especifico (debug, vision, etc)
   ├─ Detecta se precisa web search
   └─ Retorna RoutingDecision
         ↓
3. PhaseContext criado com:
   ├─ user_input
   ├─ decision (routing)
   ├─ memory_prompt (fatos de SQLite)
   └─ session_context (histórico)
         ↓
4. Seleciona Fase baseado em depth:
   ├─ REFLEX → ReflexPhase (0 LLM calls)
   ├─ DELIBERATE → DeliberatePhase (1-2 calls)
   └─ DEEP → DeepPhase (3+ calls com Evidence Arbitrage)
         ↓
5. Fase monta system_prompt:
   ├─ build_reflex_prompt() OU
   ├─ build_deliberate_prompt() OU
   └─ build_deep_prompt(god_mode=...)
         ↓
6. LLM invocado com cascade fallback:
   NVIDIA NIM → Groq (FAST) → Gemini → DeepSeek
         ↓
7. Response retorna:
   ├─ response_text
   ├─ cost_usd
   ├─ llm_calls
   ├─ (opcional) arbitrage, verdict, image_bytes
         ↓
8. Notifica via Telegram (formatter html/markdown)
   Salva em memory (SQLite)
   Registra métrica
```

---

## 🎯 Exemplos de Aplicação

### **Exemplo 1: Pergunta Reflex**
```
Usuário: "Que horas são?"

1. Router detecta SYSTEM_ANSWERABLE pattern ✓
2. Força depth = REFLEX, forced_module = "system_time"
3. ReflexPhase:
   - NÃO chama LLM
   - Retorna: "Hoje é sexta-feira, 12 de abril de 2026. São 14:32."
   - cost_usd = 0.0
   - llm_calls = 0
```

### **Exemplo 2: Pergunta Deliberate**
```
Usuário: "Como configuro o Telegram bot token?"

1. Router detecta:
   - NÃO é reflex (requer instruções)
   - NÃO é deep (não pede análise profunda)
   - module = "config"
   - needs_web = false
2. Profundidade = DELIBERATE
3. DeliberatePhase:
   - build_deliberate_prompt() monta:
     * SEXTA_FEIRA_BASE
     * date_context
     * module_context ("config")
     * memory_prompt (se há fatos sobre Telegram)
     * session_context (conversa anterior)
   - Chama LLM 1x (FAST/Groq)
   - Responde com instruções diretas
   - Antecipa: "Depois você vai precisar de API keys..."
```

### **Exemplo 3: Pergunta Deep + Web**
```
Usuário: "Qual a arquitetura mais escalável para um sistema B2B em 2026?"

1. Router detecta:
   - DEEP_TRIGGERS: "arquitetura", "escalar"
   - WEB_TRIGGERS: "2026"
   - module = "arq"
   - needs_web = true
2. Profundidade = DEEP, needs_web = true
3. Sistema coleta:
   - Web search: "scalable B2B architecture 2026"
   - Memória: fatos sobre arquitetura
4. DeepPhase:
   - Roda Evidence Arbitrage:
     * Groq (FAST) — opinião rápida
     * Gemini (SYNTHESIS) — análise
     * DeepSeek (DEEP) — profundidade
   - Triangula as 3 respostas
   - build_deep_prompt() injeta:
     * SEXTA_FEIRA_BASE (identidade)
     * DEEP_ADDENDUM (epistemia + conflito)
     * evidence_context (triangulação)
     * web_context (dados reais 2026)
   - Judge valida antes de enviar
   - Resposta integra: "A web mostra que em 2026 o padrão é..."
     + Consenso entre modelos
     + Onde divergem e por quê
     + Kill criteria se estratégia mudar
     + Pré-mortem
     + Próximos passos
```

### **Exemplo 4: God Mode**
```
Usuário: "/god Vale a pena migrar pra Kubernetes?"

1. Router detecta:
   - /god force → god_mode = true
   - DEEP_TRIGGERS: "migrar"
   - WEB_TRIGGERS: "atualmente"
2. Profundidade = DEEP (forçado), god_mode = true
3. DeepPhase:
   - build_deep_prompt(god_mode=True) monta:
     * SEXTA_FEIRA_BASE
     * DEEP_ADDENDUM
     * evidence_context (triangulação de 3)
     * web_context (dados de 2026)
     * GOD_MODE_ADDENDUM ← 5 vozes ativas
   - Respostas geradas com:
     * Recomendação principal com convicção
     * Caminho conservador (não migrar)
     * Caminho agressivo (migrar agressivamente)
     * Kill criteria: "Muda tudo se latência mudar"
     * Pré-mortem: "Se falhar, será por falta de expertise"
     * Próximos passos: dia 1, semana 1, mês 1
```

---

## 🧬 Componentes Físicos do Kernel

| Componente | Arquivo | Função |
|-----------|---------|--------|
| **Roteador Cognitivo** | `router/cognitive_load.py` | Detecção de profundidade via regex (0 LLM) |
| **Base Prompt** | `cognition/prompts.py:17-69` | SEXTA_FEIRA_BASE — identidade + 6 processos |
| **Reflex Prompt** | `cognition/prompts.py:75-82` | Simples, direto, sem preâmbulo |
| **Deep Addendum** | `cognition/prompts.py:88-116` | Triangulação + epistemia 3ª ordem |
| **God Mode Addendum** | `cognition/prompts.py:122-135` | 5 vozes sem filtro |
| **Builders** | `cognition/prompts.py:142-242` | `build_reflex_prompt()`, `build_deliberate_prompt()`, `build_deep_prompt()` |
| **Reflex Phase** | `phases/reflex.py` | Executa respostas triviaise system_time |
| **Deliberate Phase** | `phases/deliberate.py` | Síntese 1-2 LLM |
| **Deep Phase** | `phases/deep.py` | Evidence Arbitrage + Judge |
| **Phase Context** | `phases/base.py` | Container de dados entre fases |
| **Phase Result** | `phases/base.py` | Output padronizado |

---

## 📊 Impacto do Kernel

### **Economia de Custos**
- 70% das perguntas via REFLEX (0 custos)
- 25% via DELIBERATE ($0.001-0.01)
- 5% via DEEP ($0.05-0.20)
- **Média:** ~$0.006 por pergunta (vs $0.10 de chamada direta)

### **Qualidade de Respostas**
- **Reflex:** Instantânea (<50ms)
- **Deliberate:** Contextualizada com memória
- **Deep:** Triangulada com 3 modelos + web
- **God Mode:** Multiperspectiva sem compromissos

### **Transparência Epistemológica**
- Usuário sabe POR QUE sistema responde assim
- Mostra conflitos entre fontes
- Identifica blind spots
- Propõe next steps concretos

---

## 🔐 Autoconhecimento (Capabilities)

O Kernel sabe o que tem e nunca sugere o que não tem:

```python
AUTOCONHECIMENTO = """
✅ CognitiveLoadRouter: gatekeeper via regex, 0 LLM, 0ms
✅ Evidence Arbitrage: triangulação 3 providers, embedding similarity
✅ VerificationGate (Judge): validação pré-envio
✅ ModelRouter: 6 providers, 10+ modelos
✅ Desktop Vision: Qwen 3.5 local via Ollama
✅ Memória: session + embeddings + extraction automática
✅ Skills Autônomos: 13 goals rodando 24/7
✅ AFK Protocol: detecção de presença
✅ If someone says "you don't have X", corrija educadamente
"""
```

---

## 🎓 Design Philosophy

### **Por que 3 profundidades?**
Humanos não ativam o córtex pré-frontal para responder "que horas são". O sistema não deveria rodar a máquina de Turing inteira para perguntas simples.

### **Por que o nome "Sexta-Feira"?**
**Referência:** *Robinson Crusoé* — Friday é um companheiro sênior, inteligente, leal, que antecipa necessidades. Não é um subordinado, é um colega. Age com autonomia, fala com clareza.

### **Por que Kernel?**
O "kernel" é o núcleo imutável da personalidade — os processos que definem como pensa, quem é, quando ativa cada nível. Prompts são camadas aplicadas SOBRE o kernel, nunca o substituem.

---

## 🚀 Próximos Passos (Roadmap)

- [ ] **Sprint 12A:** A/B testing de prompts sem tocar no kernel
- [ ] **Sprint 12B:** Aprendizado em 2ª ordem — ajustar profundidade baseado em histórico
- [ ] **Sprint 12C:** Council dinâmico — múltiplas personalidades por contexto
- [ ] **Sprint 13:** Kernel multilíngue (extensão para inglês/espanhol)

---

## 📚 Referências no Codebase

```
src/
├── core/
│   ├── router/
│   │   └── cognitive_load.py         ← Roteamento
│   ├── cognition/
│   │   └── prompts.py                ← Kernel + Prompts
│   ├── phases/
│   │   ├── base.py                   ← PhaseContext/Result
│   │   ├── reflex.py                 ← REFLEX execution
│   │   ├── deliberate.py             ← DELIBERATE execution
│   │   └── deep.py                   ← DEEP execution
│   └── healing/
│       └── judge.py                  ← Verification Gate
```

---

**Desenvolvido com ❤️ por Victor (VSJVB1208)**  
**Framework:** Python 3.12+ | Epistemologia + Metacognição
