# 🎯 Plano de Implementação: Prospecção B2B Avançada para Seeker.Bot

## Status Atual

O Seeker possui um `ScoutHunter` goal que faz prospecção básica em 6 fontes com ciclos de 4 horas. 

**Gap identificado:** Falta estrutura de qualificação e segmentação baseada em Discovery Matrix e Account Research.

---

## Visão do Novo Sistema

### 1️⃣ Fase 1: Discovery Matrix (Semana 1)
Implementar matriz de descoberta para classificar prospects por:
- **Fit Score** (0-100): Aderência ao nicho
- **Intent Signals** (0-5): Sinais de intenção de compra
- **Budget Indicator** (0-5): Indício de orçamento

**Output:** Score de qualificação antes do outreach

### 2️⃣ Fase 2: Research Framework (Semana 1)
- Pesquisa de conta (empresa + decisores)
- Mapeamento de estrutura organizacional
- Análise de tecnologias em uso
- Identificação de pain points específicos

**Output:** Account Research Profile (ARP)

### 3️⃣ Fase 3: Conversation Intelligence (Semana 2)
Implementar 3-level conversation strategy:
- **Level 1 (Foundation):** Perguntas de descoberta baseadas em ARP
- **Level 2 (Depth):** Investigação de pain points identificados
- **Level 3 (Commitment):** Propostas customizadas + objeção handling

**Output:** Conversation playbook por niche + customer type

### 4️⃣ Fase 4: Templates & Copy (Semana 2)
- Email sequences por vertical
- LinkedIn messaging templates
- Proposal outlines customizadas
- Objection response library

**Output:** Template library integrada ao workflow

---

## Arquitetura Técnica

```
ScoutHunter (atual)
├── discovery_matrix.py (NOVO)
│   ├── FitScoreCalculator
│   ├── IntentSignalDetector
│   └── BudgetIndicator
│
├── account_research.py (NOVO)
│   ├── CompanyResearcher
│   ├── DecisionMakerFinder
│   └── PainPointAnalyzer
│
├── conversation_intelligence.py (NOVO)
│   ├── DiscoveryQuestions
│   ├── DepthProbe
│   └── ObjectionHandler
│
├── copy_engine.py (NOVO)
│   ├── EmailCopywriter
│   ├── LinkedInMessenger
│   └── ProposalBuilder
│
└── scout.py (refatorado)
    ├── ScoutEngine (integra todos os módulos)
    └── LeadQualificationPipeline
```

---

## Componentes a Implementar

### A. Discovery Matrix (`discovery_matrix.py`) ~150 linhas

```python
@dataclass
class FitScore:
    niche_match: int       # 0-100 (LLM score)
    budget_range: str      # "10k-50k", "50k-100k", etc
    company_size: str      # "startup", "scaleup", "enterprise"
    location_fit: int      # 0-100 based on proximity/timezone

@dataclass
class IntentSignals:
    website_mention: int   # 0-5 (keywords mencionadas)
    hiring_activity: int   # 0-5 (recrutando?)
    funding_recent: int    # 0-5 (levantou capital?)
    technology_adoption: int  # 0-5 (tech stack similar)
```

### B. Account Research (`account_research.py`) ~200 linhas

```python
@dataclass
class AccountResearchProfile:
    company_name: str
    industry: str
    size: str
    decision_makers: List[DecisionMaker]
    current_solution: str
    identified_pain_points: List[str]
    competitive_landscape: List[str]
```

### C. Conversation Intelligence (`conversation_intelligence.py`) ~250 linhas

```python
@dataclass
class ConversationStrategy:
    level_1_questions: List[str]  # Discovery
    level_2_probes: List[str]      # Depth
    level_3_proposals: List[str]   # Commitment
    objection_responses: Dict[str, str]
```

### D. Copy Engine (`copy_engine.py`) ~200 linhas

Gera cópias customizadas para:
- Email de outreach (Subject line + Body)
- LinkedIn message
- Proposta inicial

---

## Fluxo de Execução (Novo)

```
ScoutHunter Cycle (4h)
  ↓
1. Prospecting (6 sources)
  ↓
2. Discovery Matrix
   ├─ Fit Score (qual % do lead é relevante?)
   ├─ Intent Signals (tem sinais de compra?)
   └─ Budget Indicator (tem orçamento?)
  ↓
3. Account Research
   ├─ Pesquisa de empresa (Crunchbase, LinkedIn)
   ├─ Mapeamento de decisores
   └─ Análise de pain points
  ↓
4. Lead Qualification
   └─ Se Fit > 60 E Intent > 2 → Qualified Lead
  ↓
5. Copy Generation
   ├─ Email customizado com pain points
   ├─ LinkedIn message
   └─ Proposta inicial
  ↓
6. Notification
   ├─ Telegram: lead qualificado + cópia
   └─ Store em CRM
```

---

## Métricas & KPIs

Adicionar ao Sprint11Tracker:
```python
scout_hunter_metrics:
  leads_prospected: int
  leads_qualified: int
  qualification_rate: float     # qualified / prospected
  avg_fit_score: float
  avg_intent_signal: float
  emails_sent: int
  response_rate: float
  meeting_booked: int
```

---

## Cronograma de Implementação

| Semana | Fase | Horas | Status |
|--------|------|-------|--------|
| 1      | Discovery Matrix | 3h | TODO |
| 1      | Account Research | 4h | TODO |
| 2      | Conversation Int. | 4h | TODO |
| 2      | Copy Engine | 3h | TODO |
| 2      | Integration & Testes | 3h | TODO |
| **Total** | | **17h** | |

---

## Prioridades (MVP)

**MUST HAVE (Semana 1):**
1. ✅ Discovery Matrix (Fit Score + Intent Signals)
2. ✅ Account Research básica (Company + Pain Points)
3. ✅ Integração com ScoutHunter existente

**NICE TO HAVE (Semana 2):**
4. ⏳ Conversation Intelligence completa
5. ⏳ Copy Engine avançado
6. ⏳ Template library customizável

---

## Decisões Arquiteturais

1. **Manter ScoutHunter como goal principal** 
   - Não quebrar integração existente
   - Estender com novos módulos

2. **LLM para qualificação**
   - Fit Score: Cascade Adapter (tier STRATEGIC)
   - Pain Point Analysis: Cascade Adapter

3. **Cache de ACPs (Account Research Profiles)**
   - TTL: 7 dias (empresa não muda muito)
   - Store em MemoryStore com embedding

4. **Integração com Remote Executor**
   - Se lead qualificado → Gerar email automáticamente
   - Se usuário aprovar → Remote Executor envia via SMTP

---

## Riscos & Mitigação

| Risco | Impacto | Mitigação |
|-------|---------|-----------|
| LLM cost escalation | $$ | Budget cap por lead + cache de profiles |
| False positives (Fit Score) | ❌ leads ruins | Threshold mínimo (60) + human review |
| Information stale | ❌ outreach fails | Cache com TTL + manual refresh |
| Copy quality | ❌ low response | Test A/B copies + feedback loop |

---

## Próximas Ações

1. ✅ Ler ACCOUNT-RESEARCH-SUPREME.md (contexto)
2. ✅ Ler TEMPLATES-PRATICOS.md (copy templates)
3. ⏳ **Começar implementação: Discovery Matrix**
4. ⏳ Integrar com ScoutHunter.run_cycle()
5. ⏳ Testar com nicho "eventos" em "Goiânia"
6. ⏳ Validar metrics & KPIs

---

**Aproval Needed:** Proceder com Fase 1 (Discovery Matrix)?
