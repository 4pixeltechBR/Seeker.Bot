---
phase: "00"
name: "production-hardening"
created: 2026-05-11
status: in-progress
---

# Phase 0: production-hardening — User Acceptance Testing

## Tests

### 1. Bot inicializa e processa 10 ciclos de goals sem erros
expected: Log 06:05:06 mostra 10 goals ativos, todos com Ciclo OK no primeiro round.
result: passed

### 2. Tavily search responde em producao
expected: HTTP 200 em chamada Tavily search; fallback Brave nao deve ser unico provider funcional.
result: resolved
reason: F-02 fixed via commit 8371ffd — circuit breaker apos 3×432 + recovery automatica. Quota issue ainda existe (manual: cheque app.tavily.com), mas o desperdicio de ~25 retries/ciclo foi eliminado.

### 3. NVIDIA NIM tier responde em >=5% das chamadas
expected: NVIDIA tier serve pelo menos 5% das requests no cascade.
result: pending
reason: Baseline mostrou 0.1% hit-rate. Possivel circuit breaker permanentemente aberto. Ref: src/providers/base.py, src/providers/cascade.py

### 4. reset_client do Tavily nao crasha com NoneType
expected: Quando o client esta None, reset_client retorna gracefully sem AttributeError.
result: resolved
reason: F-01 fixed via commit 03cec93 — null-guard + try/except no aclose. Smoke test cobre race condition de coroutines concorrentes.

### 5. Credenciais fora do historico do origin/main
expected: Nenhum branch em origin contem Credenciais/*.json.
result: passed

### 6. D:\Seeker GitHub\Credenciais\ nao existe fisicamente
expected: Pasta deletada, gitignored, e pre-flight do sanitizer bloqueia recriacao.
result: passed

### 7. Sync E: -> D: produz repo publico limpo (0 referencias comerciais)
expected: scripts/sync_to_public.bat completa com sanitizer security scan passando.
result: passed

### 8. Plan de migracao Python 3.10 -> 3.12 documentado
expected: docs/ contem plano com timeline antes de 2026-10-04 (Google API Core EOL).
result: resolved
reason: T-08 fixed — docs/PYTHON_MIGRATION_PLAN.md cobre fases pre-flight/local/prod/cleanup, riscos de compat por lib (numpy, torch, playwright, aiogram, fpdf, psutil), plano de rollback, e tracking de volta para este UAT. Execucao da migracao em si fica para fase separada antes do deadline.

### 9. PAT GitHub fora do .git/config em D:
expected: URL do remote origin em D: nao contem token ghp_ embutido.
result: pending
reason: URL atual contem ghp_XhYYJZ... em texto plano. Rotacao + credential helper necessario. Ref: D:\Seeker GitHub\.git\config

### 10. tech_scout faz no maximo 3 queries por ciclo
expected: tech_scout usa batching ou parallel fan-out de no maximo 3 queries.
result: resolved
reason: T-10 fixed via commit 2034ca6 — fan-out paralelo com no maximo 3 queries (1 por categoria, com merge de categorias menores se houver >3 ativas). asyncio.gather concorrente, ~5x mais rapido, ~80% menos credits Tavily.

### 11. Pipeline P95 < 5s para queries simples
expected: P95 medido em 100 requests reais e menor que 5000ms.
result: pending
reason: Baseline mediu P95 = 15.989ms. Extractor sincrono adiciona ~500ms ao caminho critico. Ref: src/core/pipeline.py:470-477

### 12. S.A.R.A CodeValidator integrado no fluxo de auto-patch em main
expected: src/skills/self_improvement/code_validator.py existe na branch main e e chamado antes de qualquer write em goal.py.
result: pending
reason: Implementado em branch feature/seeker-v3-refactor mas nao mergeado em main. Decisao pendente: merge ou re-implementar.

## Summary

12 testes. **3 passed** (1, 5, 6, 7) + **9 pending**.

Pending items sao escopo de Phase 0. Audit-fix vai classificar quais sao
auto-fixable (#4 e talvez #11) versus manual-only (rotacao de credenciais,
investigacao NVIDIA, plan de migracao Python).
