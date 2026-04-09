"""
# Performance Tuning Guide — Sprint 11 Otimizações

Guia prático para ajustar e monitorar as otimizações do Sprint 11.
"""

# Performance Tuning Guide — Sprint 11 Optimizations

## 1. API Cascade Configuration

### Ajustar Timeouts por Tier

**Arquivo:** `src/providers/cascade_advanced.py`

```python
# Tiers com timeouts padrão
tier_timeouts = {
    CascadeTier.TIER1_NIM: 15,          # NVIDIA NIM (rápido, caro)
    CascadeTier.TIER2_GROQ: 20,         # Groq (balanceado)
    CascadeTier.TIER3_GEMINI: 25,       # Gemini (lento, barato)
    CascadeTier.TIER4_DEEPSEEK: 30,     # DeepSeek (muito lento)
    CascadeTier.TIER5_OLLAMA: 60,       # Ollama (local, grátis)
    CascadeTier.TIER6_DEGRADED: 0,      # Degraded (sem timeout)
}
```

### Tuning Strategy

#### Se latência está alta (>150ms):
```python
# Reduzir timeouts para forçar fallback mais rápido
tier_timeouts[CascadeTier.TIER1_NIM] = 10      # 15 → 10
tier_timeouts[CascadeTier.TIER2_GROQ] = 15     # 20 → 15
```

#### Se custo está alto:
```python
# Aumentar peso de fallback para modelos baratos
# Modificar em CascadeAdapter._select_tier()
# para preferir Tier 3+ quando Tier 1 ficar lento
```

#### Se Tier 1 failing (sucesso < 95%):
```python
# Aumentar timeouts ou reduzir circuit breaker threshold
tier_timeouts[CascadeTier.TIER1_NIM] = 20      # 15 → 20 (dar mais tempo)
cascade.circuit_breaker_threshold = 0.9        # 0.95 → 0.9 (mais tolerante)
```

---

## 2. LRU Cache Tuning

### Ajustar Cache Size

**Arquivo:** `src/core/pipeline.py`

```python
# Criar cache com diferentes tamanhos
self.embedding_cache = SmartEmbeddingCache(
    max_size=1000,              # Aumentar para mais embeddings armazenados
    evict_percentage=10.0,      # % a evictar quando cheio
    ttl_seconds=86400,          # 24 horas (TTL)
)
```

### Tuning by Scenario

#### Se hit rate está baixo (<60%):
```python
# Aumentar cache size
SmartEmbeddingCache(
    max_size=2000,              # 1000 → 2000
    evict_percentage=5.0,       # 10% → 5% (evictar menos)
    ttl_seconds=86400,
)
```

#### Se memória está alta (>200MB):
```python
# Reduzir cache size
SmartEmbeddingCache(
    max_size=500,               # 1000 → 500
    evict_percentage=20.0,      # 10% → 20% (evictar mais)
    ttl_seconds=43200,          # 86400 → 43200 (12h, reduzir TTL)
)
```

#### Se embeddings antigos não são mais usados:
```python
# Reduzir TTL
SmartEmbeddingCache(
    max_size=1000,
    evict_percentage=10.0,
    ttl_seconds=43200,          # 86400 → 43200 (12 horas)
)
```

### Monitorar Hit Rate

```python
# Em qualquer lugar no código:
stats = pipeline.embedding_cache.get_stats()
print(f"Hit Rate: {stats['hit_rate_percent']}")
print(f"Current Size: {stats['current_size']}/{stats['max_size']}")
print(f"Evictions: {stats['total_evictions']}")
```

---

## 3. Batch Operations Tuning

### Ajustar Max Pending

**Arquivo:** `src/core/pipeline.py`

```python
# Criar BatchOperationsManager com diferentes limites
self.batch_manager = BatchOperationsManager(
    max_pending=100,            # Máximo antes de avisar
)
```

### Tuning Strategy

#### Se batch latência está muito alta (>150ms):
```python
# Reduzir max_pending para fazer commit mais frequente
BatchOperationsManager(
    max_pending=50,             # 100 → 50 (mais commits)
)
```

#### Se throughput está baixo (<50 ops/sec):
```python
# Aumentar max_pending para consolidar mais
BatchOperationsManager(
    max_pending=200,            # 100 → 200 (menos commits)
)
```

### Monitorar Consolidação

```python
# Em /perf_detailed ou código:
report = pipeline.sprint11_tracker.get_full_report()
batch_stats = report['batch']
print(f"Consolidation: {batch_stats['commits_consolidated']}")
print(f"Commits Avoided: {batch_stats['commits_avoided']}")
```

---

## 4. Sprint11Tracker Configuration

### Ativar/Desativar Tracking

```python
# Em pipeline.py __init__:
self.sprint11_tracker = Sprint11Tracker()  # Sempre ativa por padrão
```

### Monitorar em Tempo Real

```bash
# No Telegram:
/perf_detailed

# Ou em código:
report = pipeline.sprint11_tracker.format_for_telegram()
print(report)
```

---

## 5. Performance Targets Checklist

### Antes de Deploy

- [ ] Cascade Tier 1 success rate > 95%
- [ ] LRU Cache hit rate 65-75%
- [ ] Batch consolidation 7→1 commits
- [ ] Latência p95 < 200ms
- [ ] API cost reduced by 40%+

### Em Produção (Daily)

```python
# Rodar este script diariamente:
report = pipeline.sprint11_tracker.get_full_report()

# Validar targets
latency = float(report['latency']['p95'].rstrip('ms'))
hit_rate = float(report['cache']['hit_rate'].rstrip('%'))
cascade_success = float(report['cascade']['tier1_success_rate'].rstrip('%'))

assert latency < 200, f"Latência p95 {latency}ms > 200ms"
assert hit_rate > 65, f"Hit rate {hit_rate}% < 65%"
assert cascade_success > 95, f"Cascade success {cascade_success}% < 95%"
```

---

## 6. Common Issues & Solutions

### Problema: Cache Hit Rate Caindo

**Sintomas:**
- Hit rate < 60%
- Memory footprint ainda baixo

**Causas:**
- Cache size pequeno demais
- TTL muito curto
- Padrão de acesso mudou (novos usuários/dados)

**Solução:**
```python
# Aumentar cache + reduzir TTL aggressively
cache = SmartEmbeddingCache(
    max_size=2000,              # Aumentar
    evict_percentage=5.0,       # Reduzir evicção
    ttl_seconds=86400,          # Manter 24h
)
```

### Problema: Latência Ainda Alta

**Sintomas:**
- p95 > 200ms apesar de batch consolidation

**Causas:**
- Cascade timeouts muito altos
- Batch size muito grande
- Database lenta

**Solução:**
```python
# Reduzir timeouts + batch size
tier_timeouts[CascadeTier.TIER1_NIM] = 10    # 15 → 10
BatchOperationsManager(max_pending=50)       # 100 → 50
```

### Problema: Custo Ainda Alto

**Sintomas:**
- Não atingindo -40% redução de custo

**Causas:**
- Fallback freq > 5% (Tier 1 muito lento)
- Cache hit rate < 65%
- Usando Tier 3+ muito frequentemente

**Solução:**
```python
# Forçar Tier 1 a melhorar ou usar Tier 2 mais
# Option 1: Aumentar Tier 1 timeout
tier_timeouts[CascadeTier.TIER1_NIM] = 20

# Option 2: Reduzir custo de Tier 2 (Groq)
# (requer mudança em provider configuration)
```

---

## 7. Monitoring Dashboard

### Métricas Essenciais

```
LATÊNCIA:
  ├─ p50: < 110ms (target: 100ms)
  ├─ p95: < 200ms (target: 120ms)
  └─ p99: < 300ms (target: 150ms)

CACHE:
  ├─ Hit Rate: 65-75% (target: 70%)
  ├─ Evictions: < 10/hora (normal)
  └─ Memory: < 100MB (for 1000 embeddings)

CASCADE:
  ├─ Tier 1 Success: > 95% (target: 97%)
  ├─ Fallback Freq: < 5% (target: 3%)
  └─ Cost: < $0.005/chamada (target: $0.003)

BATCH:
  ├─ Consolidation: 7→1 (target: consistent)
  ├─ Success Rate: > 99% (target: 99.5%)
  └─ Avg Latency: < 100ms (target: 75ms)
```

### Verificar Saúde (Hourly)

```bash
# Telegram:
/perf_detailed

# Esperar por:
p95 latency < 200ms
Cache hit rate 65-75%
Cascade Tier 1 > 95%
Batch consolidation active
```

---

## 8. Advanced Tuning

### Ajuste Fino de Eviction Strategy

```python
# Em embedding_cache.py, função _evict_lru_batch():
# Atual: 70% weight em access_count, 30% em age
# Para favorecer recência:
score = (
    cached.access_count * 0.5 +      # 50% weight
    (cached.age_seconds / 3600) * 0.5  # 50% weight
)
```

### Cascading Fallback Customization

```python
# Em cascade_advanced.py, função _should_cascade_to_next_tier():
# Customizar lógica de fallback baseado em:
# - Latência (muito lento → fallback)
# - Custo (muito caro → fallback)
# - Taxa de erro (muitos erros → fallback)

if latency_ms > 20:  # NVIDIA levou > 20ms
    return True      # Tenta próximo tier
```

### Database Query Optimization

```python
# Se batch commit ainda está lento (> 100ms):
# 1. Verificar índices em semantic table
# 2. Verificar índices em episodic table
# 3. Considerar batching em chunks (100 ops em vez de 1000)

# Em pipeline._post_process():
# Ao invés de 1 commit com N operações
# Fazer N/100 commits menores em paralelo
```

---

## 9. Deployment Checklist

- [ ] Testar Cascade com falhas simuladas
- [ ] Testar Cache com dados reais
- [ ] Testar Batch consolidation em produção
- [ ] Monitorar /perf_detailed por 24h
- [ ] Validar custo reduzido
- [ ] Validar latência melhorada
- [ ] Validar que testes ainda passam
- [ ] Fazer rollback plan se algo quebrar

---

## 10. Quick Reference

### Para Reduzir Custo
```python
# 1. Aumentar cache hit rate
max_size=2000, evict_percentage=5.0

# 2. Melhorar Tier 1 success rate
tier_timeouts[TIER1] = 20

# 3. Usar modelos mais baratos
tier_timeouts[TIER2] = 15  # Dar tempo para Groq
```

### Para Melhorar Latência
```python
# 1. Reduzir timeouts (force fallback rápido)
tier_timeouts[TIER1] = 10

# 2. Reduzir batch size
BatchOperationsManager(max_pending=50)

# 3. Aumentar TTL (menos cache misses)
ttl_seconds=172800  # 48h ao invés de 24h
```

### Para Aumentar Resiliência
```python
# 1. Aumentar timeouts
tier_timeouts[TIER1] = 30

# 2. Reduzir circuit breaker sensitivity
circuit_breaker_threshold = 0.9  # Mais tolerante

# 3. Adicionar retry logic
max_retries = 2
```

---

**Documento gerado:** Sprint 11 Optimization Phase
**Atualizado:** 09/04/2026
**Manutenção:** Verificar /perf_detailed diariamente em produção
