# Sprint 11 — Otimizações de Performance e Eficiência

**Data de Início:** 2026-04-09  
**Duração Estimada:** 4-5 dias (20 horas)  
**Status:** Em Planejamento

---

## Visão Geral

Sprint 11 foca em otimizações de performance, redução de latência e eficiência de custos. Baseado na auditoria do Seeker.ai Project e nas métricas coletadas em Sprint 10, implementaremos:

1. **Otimizações de LLM** - Cascade API 6-tier, local fallback
2. **Otimizações de Cache** - LRU para embeddings, lazy loading
3. **Batch Operations** - Commits consolidados, operações em lote
4. **Monitoramento** - Métricas detalhadas por fase e componente

---

## FASE 1 — API CASCADE INTELIGENTE (Tier 1 — Máxima Prioridade)

### Objetivo
Reduzir custos em 40% implementando fallback de 6 tiers com priorização inteligente.

### O que Será Feito

**Tier 1: NVIDIA NIM** (Fastest, Highest Cost)
- Models: Nemotron-340B, Llama-2-405B
- Use: Deep reasoning, complex analysis
- Fallback: Se 429 ou timeout

**Tier 2: Groq** (Fast, Medium Cost)
- Models: Mixtral-8x7b, Llama-2-70b
- Use: Deliberate phase, web search synthesis
- Fallback: Se erro ou latência > 500ms

**Tier 3: Gemini Pro** (Balanced, Low Cost)
- Models: Gemini Pro, Gemini Pro Vision
- Use: Vision analysis, standard deliberate
- Fallback: Se rate limited

**Tier 4: DeepSeek** (Cheap, Acceptable Quality)
- Models: DeepSeek-V2.5
- Use: Simple reflex, low-stakes tasks
- Fallback: Se erro

**Tier 5: Ollama Local (Qwen)** (Free, CPU)
- Models: Qwen2-7B (quantized)
- Use: Fallback final, offline capability
- Fallback: Se nenhum cloud disponível

**Tier 6: Placeholder Response** (Degraded Mode)
- Respostas estruturadas sem LLM
- Exemplo: "Sistema em modo degradado. Consultando base de conhecimento..."

### Implementação

**Arquivo novo:** `src/providers/cascade.py` (já existe, será aprimorado)

```python
class CascadeAdapter:
    """
    Orquestrador de fallback inteligente com 6 tiers
    """
    
    async def call_with_cascade(
        self,
        prompt: str,
        role: CognitiveRole = CognitiveRole.BALANCED,
        timeout: int = 30,
    ) -> tuple[str, str, float]:
        """
        Tenta providers em cascata até sucesso
        
        Retorna: (response, provider_usado, custo_usd)
        """
        
    async def get_health_status(self) -> dict:
        """
        Status de cada tier: disponível, latência, custo/hora
        """
```

### Benefício
- **Custo:** -40% (média ponderada)
- **Confiabilidade:** +95% (6 fallbacks)
- **Latência:** -20% (local fallback)

### Esforço
2-3 horas

---

## FASE 2 — CACHE DE EMBEDDINGS COM LRU (Tier 1 — Máxima Prioridade)

### Objetivo
Reduzir chamadas de embedding em 60% implementando LRU cache inteligente.

### O que Será Feito

**Problema Atual:**
- Cada query de embedding refaz cálculo
- Cache FIFO evicta embeddings frequentes
- Custos Gemini desnecessários

**Solução:**
```python
class SmartEmbeddingCache:
    """
    LRU cache com análise de hit rate e evição inteligente
    """
    
    def __init__(self, max_size: int = 1000):
        self._cache: OrderedDict[str, CachedEmbedding] = OrderedDict()
        self._hit_rate = deque(maxlen=100)
    
    async def get_embedding(
        self,
        texto: str,
        force_refresh: bool = False
    ) -> np.ndarray:
        """
        Get embedding com LRU hit tracking
        """
        
    def get_hit_rate(self) -> float:
        """Retorna hit rate % dos últimos 100 queries"""
```

**Implementação:**
- Modificar `src/core/memory/embeddings.py`
- Adicionar `OrderedDict` com `move_to_end()`
- Rastrear hit/miss rate
- Evictar os menos acessados (não mais antigos)

**Benchmark Esperado:**
```
Antes:  1000 embeddings/dia = $0.30
Depois: 400 embeddings/dia = $0.12  (60% reduction)

Hit Rate Target: 65-75%
```

### Esforço
1.5-2 horas

---

## FASE 3 — BATCH COMMITS & LAZY LOADING (Tier 2 — Alto Valor)

### Objetivo
Reduzir latência de escritas em 40% consolidando commits.

### O que Será Feito

**Problema Atual:**
```python
# Antes: 7 commits por resposta
pipeline._post_process():
    await memory.upsert_fact()  # commit 1
    await memory.store_embedding()  # commit 2
    await memory.record_episode()  # commit 3
    await cost_tracker.registrar_custo()  # commit 4
    # etc...
```

**Solução:**
```python
# Depois: 1 commit por resposta
pipeline._post_process():
    memory.queue_upsert_fact()
    memory.queue_store_embedding()
    memory.queue_record_episode()
    await memory.commit_all()  # 1 commit!
```

**Implementação:**
- Modificar `src/core/pipeline.py:_post_process()`
- Adicionar `_pending_ops` queue em MemoryStore
- Batch write para SQLite (BEGIN...COMMIT)
- Lazy load embeddings apenas quando usado

**Benchmark Esperado:**
```
Antes:  ~150ms (_post_process latência)
Depois: ~95ms  (40% reduction)

Memory footprint: -25% (lazy loading)
```

### Esforço
2-3 horas

---

## FASE 4 — MONITORAMENTO DETALHADO (Tier 2 — Alto Valor)

### Objetivo
Visibilidade em tempo real de performance por fase e componente.

### O que Será Feito

**Novo Dashboard:** `/status_detailed`

```python
@dp.message(F.text == "/status_detailed")
async def cmd_status_detailed(message: Message):
    """
    Métricas detalhadas por fase com histórico
    """
    html = format_detailed_status(
        phase_stats=pipeline.profiler.get_phase_stats(),
        cost_breakdown=pipeline.cost_tracker.get_breakdown(),
        latency_histogram=pipeline.profiler.get_latency_percentiles(),
    )
```

**Métricas por Fase:**
```
REFLEX:
  - Calls: 245
  - Avg Latency: 89ms
  - Success Rate: 99.2%
  - Cost: $0.45
  - Most Common: /search (120x)

DELIBERATE:
  - Calls: 127
  - Avg Latency: 320ms
  - Success Rate: 94.1%
  - Cost: $2.10
  - Top Model: Groq (52x)

DEEP:
  - Calls: 23
  - Avg Latency: 1,250ms
  - Success Rate: 91.3%
  - Cost: $3.20
  - Top Model: NIM (18x)

SYSTEM:
  - Total Cost: $5.75
  - Efficiency: 78.2% (cost per byte output)
  - Provider Diversity: 4 providers
  - Cascade Usage: 8x fallbacks triggered
```

**Implementação:**
- Estender `src/core/profiling/profiler.py`
- Adicionar histogramas de latência (percentis)
- Rastrear cascade fallback events
- Adicionar comando `/perf_detailed`

### Esforço
2-2.5 horas

---

## FASE 5 — TESTES DE PERFORMANCE (Tier 2 — Alto Valor)

### Objetivo
Validar que otimizações funcionam sem regressões.

### O que Será Feito

**Testes Novos:**

1. **test_cascade_fallback.py** (8 testes)
   - Test each tier individually
   - Test cascade order
   - Test error handling
   - Test cost tracking

2. **test_embedding_cache_lru.py** (6 testes)
   - Test LRU eviction
   - Test hit rate tracking
   - Test cache invalidation
   - Test concurrent access

3. **test_batch_commits.py** (5 testes)
   - Test pending ops queue
   - Test commit atomicity
   - Test rollback on error
   - Test latency reduction

4. **test_phase_profiling.py** (6 testes)
   - Test profiler metrics collection
   - Test percentile calculations
   - Test cascade event tracking
   - Test phase breakdown accuracy

**Benchmark Suite:**

```python
@pytest.mark.benchmark
class TestPerformanceBenchmarks:
    
    async def test_cascade_latency_vs_direct(self, benchmark):
        """Cascade deve ser <= 5% mais lento que direct"""
        
    async def test_embedding_cache_hit_rate(self, benchmark):
        """Hit rate deve ser >= 65%"""
        
    async def test_batch_commit_throughput(self, benchmark):
        """Batch commits >= 40% mais rápido"""
```

### Esforço
2.5-3 horas

---

## FASE 6 — DOCUMENTAÇÃO & DEPLOYMENT (Tier 3 — Finalização)

### Objetivo
Documentar otimizações e preparar para deployment.

### O que Será Feito

1. **SPRINT_11_OPTIMIZATIONS.md**
   - Resultados de cada otimização
   - Antes/depois comparativo
   - Guia de troubleshooting

2. **PERFORMANCE_TUNING_GUIDE.md**
   - Como ajustar limites
   - Monitoring checklist
   - Cost estimation

3. **Deployment Checklist**
   - [ ] All tests passing
   - [ ] Cascade provider keys validated
   - [ ] Cache policies reviewed
   - [ ] Monitoring alerts configured
   - [ ] Rollback plan documented

### Esforço
1-2 horas

---

## CRONOGRAMA

| Dia | FASE | Duração | Saída |
|-----|------|---------|-------|
| 1 | 1: Cascade API | 2.5h | CascadeAdapter aprimorado |
| 1-2 | 2: LRU Cache | 2h | SmartEmbeddingCache + testes |
| 2 | 3: Batch Commits | 2.5h | Pipeline.commit_all() |
| 2-3 | 4: Monitoramento | 2.5h | /status_detailed + métricas |
| 3-4 | 5: Testes | 3h | 25+ testes passando |
| 4 | 6: Docs + Deploy | 2h | Documentação + checklist |
| **TOTAL** | | **~17h** | **Sprint 11 Completo** |

---

## CRITÉRIOS DE SUCESSO

✅ **Performance**
- Latência -40% (/status_detailed)
- Embeddings cache hit rate >= 65%
- Batch commits -40% latência
- Cascade overhead < 5%

✅ **Confiabilidade**
- 250+ testes passando
- 0 regressões de funcionalidade
- Fallback coverage 100%

✅ **Custo**
- LLM calls -25% em média
- Cascade cost -40% vs direct
- ROI: 2 horas economia/dia em custos

✅ **Qualidade**
- Type hints 100%
- Docstrings completas
- Logging estruturado
- Zero warnings

---

## DEPENDÊNCIAS

- ✅ Sprint 10 completo (Budget, Data, Analytics)
- ✅ Providers base.py funcional
- ✅ Profiler em pipeline
- ⚠️ API keys de providers (NVIDIA, Groq, Gemini, DeepSeek)
- ⚠️ Ollama local instalado (para Tier 5)

---

## RISCOS E MITIGAÇÕES

| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| Cascade fallback muito lento | Baixa | Alto | Cache de resultado, timeout agressivo |
| Cache hit rate baixo | Média | Médio | Aumentar max_size, analytics |
| Batch commits quebram consistency | Baixa | Alto | Transaction locks, rollback |
| NVIDIA NIM rate limit | Média | Médio | Groq como primary, NIM como secondary |

---

## PRÓXIMOS PASSOS

### Se Sprint 11 for Aprovado:
1. Revisar e validar plan com Victor
2. Confirmar API keys dos providers
3. Clonar repositório em worktree
4. Começar FASE 1 (Cascade)

### Alternativa (Se Não Aprovado):
- Sprint 11.5: Bug Fixes & Stabilization
- Sprint 12: Frontend Dashboard Web
- Sprint 13: Advanced ML Features

---

## NOTAS TÉCNICAS

**Compatibilidade:**
- Todas as otimizações são backwards-compatible
- Fallback para comportamento antigo se cascade falhar
- Sem mudanças em interfaces públicas

**Rollback:**
- Cada FASE é independente e pode ser rollback isoladamente
- Feature flags para ativar/desativar otimizações

**Monitoramento:**
- Prometheus metrics para cada tier
- Grafana dashboard (opcional)
- Alertas automáticos se fallback > 50%

---

**Desenvolvido por:** Claude (AI Assistant)  
**Revisado por:** Aguardando Victor  
**Status:** Em Aprovação para Implementação
