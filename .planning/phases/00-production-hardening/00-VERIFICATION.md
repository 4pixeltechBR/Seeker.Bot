---
phase: "00"
name: "production-hardening"
created: 2026-05-11
status: in-progress
---

# Phase 0: production-hardening — Verification

## Goal-Backward Verification

**Phase Goal:** Eliminate open production-impact issues from the 2026-04-25
code review and 2026-05-11 runtime log analysis. Each gap below maps to an
auto-fixable or manual-only finding to be resolved.

## Findings

| F-ID | Severity | Description | File:Line | Classification |
|------|----------|-------------|-----------|----------------|
| F-01 | high | `reset_client()` no Tavily search crasha com `'NoneType' object has no attribute 'aclose'` quando o cliente já é None. Need null-check antes de aclose | `src/core/search/web.py` (função `reset_client`/Tavily search handler) | auto-fixable |
| F-02 | high | Tavily não tem circuit breaker — após 5 falhas 432 consecutivas, próximas chamadas devem ser puladas por X minutos (não retentar 25× seguidas) | `src/core/search/web.py` (classe `WebSearcher` ou wrapper Tavily) | auto-fixable |
| F-03 | medium | `tech_scout` envia 15 queries seriais por ciclo (uma por framework). Batching ou parallelization reduziria latência e custo | `src/skills/tech_scout/goal.py` | manual-only |
| F-04 | medium | `pipeline.py:_post_process` swallow exceptions silenciosamente em entity/triple saves (`except Exception: pass`) — sem logging | `src/core/pipeline.py:833-855` | auto-fixable |
| F-05 | medium | Extractor síncrono no caminho crítico do pipeline adiciona ~500ms ao P95. Já existe `_post_process` em background — extraction pode mover pra lá | `src/core/pipeline.py:470-477` | manual-only |
| F-06 | high | PAT GitHub (`ghp_…`) embutido em texto plano em `D:\Seeker GitHub\.git\config`. Rotação manual necessária + reconfigurar com credential helper | `D:\Seeker GitHub\.git\config` (não no repo) | manual-only |
| F-07 | medium | GCP service account em `Credenciais/service-account.json.json` foi exposta localmente em feature branches de E:. Boa prática: rotacionar mesmo nunca tendo ido pro GitHub | `E:\Seeker.Bot\Credenciais\*.json` | manual-only |
| F-08 | low | Python 3.10 — Google API Core deprecação 2026-10-04. Plan upgrade para 3.12 | `pyproject.toml`, `requirements.txt` | manual-only |
| F-09 | low | NVIDIA NIM tier 0.1% success rate em baseline. Pode ser circuit breaker permanentemente aberto ou key issue | `src/providers/cascade.py` | manual-only |

## Result

9 findings registrados.

Auto-fixable: **3** (F-01, F-02, F-04)
Manual-only: **6** (F-03, F-05, F-06, F-07, F-08, F-09)

Próximo passo: `/gsd-audit-fix --max 5 --severity high` para corrigir
F-01 e F-02 (severity=high, auto-fixable) com testes + commit atômico.
