# Sprint 11 Deployment Checklist

Guia passo-a-passo para deploy seguro das otimizações em produção.

## 📋 PRÉ-DEPLOYMENT (48h antes)

### Code Review
- [ ] PR #2 foi revisada
- [ ] Todos os 101 testes passam
- [ ] Nenhum conflito com main branch
- [ ] Commits estão bem documentados

### Teste Local Completo
```bash
# Rodar todos os testes
pytest tests/test_cascade_adapter.py \
        tests/test_embedding_cache.py \
        tests/test_batch_operations.py \
        tests/test_sprint11_tracker.py \
        tests/test_sprint11_performance.py -v

# Esperado: 101 passed in ~4s
```

### Validar Dependências
- [ ] Não há novas dependências externas
- [ ] Versions compatíveis com production
- [ ] Não há breaking changes

### Documentação
- [ ] SPRINT_11_COMPLETE.md ✓
- [ ] PERFORMANCE_TUNING_GUIDE.md ✓
- [ ] DEPLOYMENT_CHECKLIST.md ✓
- [ ] README.md atualizado se necessário

---

## 🚀 DEPLOYMENT (Fase 1: Staging)

### 1. Merge em Main (Sexta-feira à noite)

```bash
# 1. Aprovação final da PR #2
gh pr approve <PR_NUMBER>

# 2. Merge
git checkout main
git pull origin main
git merge --no-ff feature/sprint-11

# 3. Push
git push origin main
```

### 2. Deploy em Staging (Ambiente de Teste)

```bash
# 1. Fazer deploy da versão main em staging
# (Processo depende da infra da empresa)

# 2. Verificar que tudo subiu
curl https://staging.seeker-bot.com/health

# 3. Rodar smoke tests
pytest tests/test_smoke_*.py -v
```

### 3. Monitoramento em Staging (4-6h)

```bash
# Monitorar /perf_detailed
# Esperado:
# - Latência p95 < 200ms
# - Cache hit rate 65-75%
# - Cascade Tier 1 > 95%
# - Batch consolidation ativo
```

### 4. Validar Metricas em Staging

```python
# Rodar script de validação:
python3 scripts/validate_sprint11_metrics.py

# Esperado: todos os targets atingidos
✓ Latência: 95ms (target: <150ms)
✓ Cache: 71% hit rate (target: 65-75%)
✓ Cascade: 96% Tier1 (target: >95%)
✓ Batch: 7→1 consolidation
```

---

## 🎯 DEPLOYMENT (Fase 2: Produção)

### 1. Pre-Production Checklist

- [ ] Backups dos databases principais feitos
- [ ] Plano de rollback documentado
- [ ] Times notificados (Ops, Dev, Support)
- [ ] Janela de maintenance agendada (15-30min)
- [ ] On-call engineer confirmado

### 2. Deploy em Produção

```bash
# 1. Parar responses de novos usuários (graceful shutdown)
# (Depende da infra)

# 2. Deploy do código
# docker pull seeker-bot:latest
# docker compose up -d

# 3. Aguardar containers ficarem healthy
sleep 30
curl https://seeker-bot.com/health

# 4. Reiniciar cache e batch managers se necessário
# (Código já trata inicialização)
```

### 3. Validação Pós-Deploy (Primeira Hora)

```bash
# 1. Verificar health endpoints
curl https://seeker-bot.com/health

# 2. Rodar teste simples
/search "test query"

# 3. Verificar /perf_detailed
/perf_detailed

# 4. Checar logs para erros
docker logs seeker-bot | grep ERROR

# 5. Validar métricas iniciais
# Esperado: tudo iniciando do zero
```

### 4. Monitoramento Ativo (Primeira Semana)

#### Hora 1-2 (Crítico)
```bash
# Check a cada 15 minutos:
- /perf_detailed (latência, cache, cascade)
- Docker logs (erros)
- Database connections (não devem vazar)

# Se problema: ROLLBACK IMEDIATO
```

#### Hora 2-24 (Vigilância)
```bash
# Check a cada hora:
- /perf_detailed
- API error rates
- Database performance
- Cache efficiency
```

#### Dia 1-7 (Monitoramento)
```bash
# Check diário:
- /perf_detailed
- Custo reduzido vs baseline
- Latência consistente
- Sem memory leaks
```

---

## ⚠️ ROLLBACK PLAN

### Cenários de Rollback

| Cenário | Critério | Ação |
|---------|----------|------|
| Latência crítica | p95 > 250ms | Rollback imediato |
| Cache quebrado | Hit rate < 50% | Rollback imediato |
| Cascade falhas | Tier1 success < 90% | Rollback |
| Memory leak | Memory cresce >1GB | Rollback |
| Database locked | Query timeout > 5s | Rollback |

### Executar Rollback

```bash
# 1. Verificar commit anterior
git log --oneline -5

# 2. Revert para versão anterior
git revert <COMMIT_HASH>
git push origin main

# 3. Aguardar CI passar
# (4-5 minutos)

# 4. Deploy versão anterior
docker pull seeker-bot:previous
docker compose up -d

# 5. Validar saúde
curl https://seeker-bot.com/health
/perf_detailed
```

---

## 📊 MÉTRICAS CRÍTICAS

### Antes do Deploy

```
Baseline (sem Sprint 11):
  - Latência p95: 150-200ms
  - API cost: $1.00/dia (100 chamadas)
  - Cache: N/A (sem LRU)
  - Batch: 7 commits por resposta
```

### Depois do Deploy (Esperado)

```
Com Sprint 11:
  - Latência p95: 100-150ms (40% melhoria)
  - API cost: $0.30/dia (70% redução)
  - Cache: 70% hit rate
  - Batch: 1 commit consolidado
```

### Validação Pós-Deploy

```python
# Rodar após 1h, 6h, 24h, 7 dias

report = pipeline.sprint11_tracker.get_full_report()

# Latência
p95 = float(report['latency']['p95'].rstrip('ms'))
assert 100 < p95 < 250, f"Latência anômala: {p95}ms"

# Cache
hit_rate = float(report['cache']['hit_rate'].rstrip('%'))
assert hit_rate > 60, f"Cache hit rate baixo: {hit_rate}%"

# Cascade
tier1 = float(report['cascade']['tier1_success_rate'].rstrip('%'))
assert tier1 > 90, f"Cascade Tier1 falhas: {tier1}%"
```

---

## 📋 CHECKLIST FINAL

### 24h Antes
- [ ] Todos os testes passando (101/101)
- [ ] Staging validado por 4-6h
- [ ] Backups feitos
- [ ] Equipe notificada
- [ ] Rollback plan documentado
- [ ] On-call engineer confirmado

### Dia do Deploy
- [ ] Última verificação no staging
- [ ] Health checks passando
- [ ] Logs limpos de warnings
- [ ] Janela de maintenance clara para users
- [ ] Engineer responsável presente

### Primeira Hora Pós-Deploy
- [ ] /perf_detailed funciona
- [ ] Sem erros críticos no log
- [ ] Latência dentro do esperado
- [ ] Cache iniciando corretamente
- [ ] Batch consolidation funcionando

### Primeira Semana
- [ ] Latência estável
- [ ] Cache hit rate convergindo (60-75%)
- [ ] Cascade fallback <5%
- [ ] Custo reduzido validado
- [ ] Nenhuma regressão detectada

---

## 🔔 COMUNICAÇÃO

### Notificação em Andamento

```
[DEPLOYMENT STARTED] Sprint 11 Otimizações
ETA: 30 minutos
  - -40% latência
  - -70% custo
  - +70% cache hit rate
  - Testes offline por ~10 minutos
```

### Notificação Sucesso

```
[DEPLOYMENT COMPLETE] Sprint 11 Otimizações
Status: OK
  ✓ Latência: 95ms (p95: 120ms)
  ✓ Cache: 71% hit rate
  ✓ Cascade: 96% Tier1 success
  ✓ Batch: 7→1 consolidation

Próximos passos:
  - Monitorar /perf_detailed
  - Validar custo reduzido
  - Reportar anomalias
```

### Notificação Rollback (Se Necessário)

```
[DEPLOYMENT ROLLED BACK] Sprint 11 Otimizações
Motivo: <REASON>
Status: Anterior restaurado
ETA: 10 minutos para estabilizar

Aguardando análise da causa...
```

---

## 📞 CONTATOS DE EMERGÊNCIA

- **On-Call Engineer**: [Name] - [Phone]
- **DevOps Lead**: [Name] - [Phone]
- **Database Admin**: [Name] - [Phone]
- **Escalation**: [Manager] - [Phone]

---

## 📝 POST-DEPLOYMENT REPORT

### Template

```markdown
# Sprint 11 Deployment Report

**Data:** 09/04/2026
**Versão:** feature/sprint-11 (commit: 5a68e2a)
**Status:** SUCESSO / ROLLBACK

## Métricas Pré-Deploy
- Latência p95: 150ms
- API Cost: $1.00/dia
- Batch Commits: 7

## Métricas Pós-Deploy
- Latência p95: 120ms (-20%)
- API Cost: $0.30/dia (-70%)
- Batch Commits: 1

## Incidentes
- [ ] Nenhum
- [ ] Cache hit rate baixo (< 60%)
- [ ] Latência alta (> 200ms)
- [ ] Cascade failures (< 90%)

## Observações

[Adicionar notes aqui]

## Próximos Passos

- [ ] Monitorar por mais 7 dias
- [ ] Publicar relatório final
- [ ] Iniciar Sprint 12
```

---

**Documento Versão:** 1.0
**Atualizado:** 09/04/2026
**Responsável:** DevOps / Release Engineering
