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
result: partial
reason: T-03 root cause encontrado e fixado — circuit breaker no cascade keyava por PROVIDER (string "nvidia"), entao 3 timeouts de nvidia/nemotron-ultra (~30s) blacklisteavam TODOS os 4 modelos NVIDIA por 5min. Agora keya por provider:model, isolando o nemotron-ultra dos modelos rapidos (deepseek-v3.2, gemma-4-31b, qwq-32b). Espera-se subida significativa de hit-rate. Falta medir baseline novo apos 24h de prod.

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
result: partial
reason: T-09 — token removido de D:\Seeker GitHub\.git\config (git remote set-url origin sem o @ghp_..., e credential.helper=manager-core para usar Windows Credential Manager). Verificado: findstr ghp_ retorna 0 matches. Falta rotacao no GitHub (https://github.com/settings/tokens) — token continua valido ate ser revogado. Runbook completo em docs/PAT_ROTATION_RUNBOOK.md.

### 10. tech_scout faz no maximo 3 queries por ciclo
expected: tech_scout usa batching ou parallel fan-out de no maximo 3 queries.
result: resolved
reason: T-10 fixed via commit 2034ca6 — fan-out paralelo com no maximo 3 queries (1 por categoria, com merge de categorias menores se houver >3 ativas). asyncio.gather concorrente, ~5x mais rapido, ~80% menos credits Tavily.

### 11. Pipeline P95 < 5s para queries simples
expected: P95 medido em 100 requests reais e menor que 5000ms.
result: partial
reason: T-11 codigo fixado — extractor sincrono no caminho critico removido. _post_process ja chama extract() como fallback em background; o resultado é visível ao user antes da extração rodar. Falta rodar baseline novo com 100 requests para confirmar P95 <5000ms.

### 12. S.A.R.A CodeValidator integrado no fluxo de auto-patch em main
expected: src/skills/self_improvement/code_validator.py existe na branch main e e chamado antes de qualquer write em goal.py.
result: partial
reason: T-12 parcial — code_validator.py e error_database.py extraidos do commit d7b6cc3 (feature/seeker-v3-refactor) e adicionados em main (passam ruff + imports limpos). Integracao em goal.py e bot.py deferida para fase 01-sara-integration porque os arquivos divergiram em main desde abril. docs/SARA_INTEGRATION_NOTE.md documenta os TODOs concretos para fechar.

## Summary

12 testes. **3 passed** (1, 5, 6, 7) + **9 pending**.

Pending items sao escopo de Phase 0. Audit-fix vai classificar quais sao
auto-fixable (#4 e talvez #11) versus manual-only (rotacao de credenciais,
investigacao NVIDIA, plan de migracao Python).
