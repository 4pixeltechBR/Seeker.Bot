# Baseline Snapshot — 2026-04-21

Baseline pré-refactor v3. Medido no branch `feature/seeker-v3-refactor` antes de qualquer mudança.

## Test Suite

- **Total coletado:** 672 testes
- **Executado:** 663 (2 módulos com ImportError ignorados)
- **Passed:** 594 (89.6%)
- **Failed:** 41
- **Errors:** 28
- **Skipped:** 9
- **Tempo total:** 16.39s
- **Log completo:** [test_baseline_2026-04-21.txt](test_baseline_2026-04-21.txt)

### Coletores quebrados (bloqueiam collection)
- `tests/test_remote_executor_integration_e2e.py` — ImportError: `AutonomyTier` não existe em `src.core.executor`
- `tests/vision_benchmark/test_vlm_benchmark.py` — ImportError: `TaskCategory` não existe em `tests.vision_benchmark.tasks`

### Clusters de falhas
- `test_executor_handlers.py` — 9 failed (bash/fileops/api/remote_trigger)
- `test_executor_orchestrator.py` — 8 failed
- `test_executor_safety.py` — 5 failed (whitelist/budget/afk/policy)
- `test_scheduler_*` — 16 failed (calculator/wizard/e2e)
- `test_cascade_adapter.py` — 11 errors
- `test_pipeline_intent.py` — 17 errors

**Revisão do master plan:** pass rate atual é 89.6%, não 65%. A Fase 0 foi calibrada para uma realidade pior; o trabalho de fix é menor do que o estimado.

## Performance (687 amostras de produção)

Extraído de `logs/seeker.log` + `logs/seeker.log.1` via regex `Tier N (provider) respondeu em Xms`.

| Métrica | Valor |
|---|---|
| Min | 272ms |
| P50 | 1033ms |
| Mean | 4916ms |
| **P95** | **15989ms** |
| P99 | 26064ms |
| Max | 27510ms |

### Distribuição por tier
- `tier2_groq`: 686 (99.9%)
- `tier1_nvidia`: 1 (0.1%)

**Observação:** NVIDIA (tier 1) está praticamente fora do circuito — provavelmente em circuit breaker ou sem API key válida. Investigar na Fase 0.

Log: [perf_baseline_2026-04-21.txt](perf_baseline_2026-04-21.txt)

## Ambiente

- Python: 3.10.11 (EOL Google api_core em 2026-10-04)
- Git head: ver [git_baseline_2026-04-21.txt](git_baseline_2026-04-21.txt)
- Deps: ver [deps_baseline_2026-04-21.txt](deps_baseline_2026-04-21.txt) (308 packages)

## Warnings de deprecation a tratar

- `google.generativeai` deprecated → migrar para `google.genai`
- Python 3.10 EOL para google.api_core em outubro/2026

## Targets do Master Plan (para comparação futura)

| Métrica | Baseline | Target | Delta |
|---|---|---|---|
| P95 latência | 15989ms | 2000ms | −87% |
| Test pass rate | 89.6% | 95% | +5.4pp |
| Tier-1 hit rate | 0.1% | ≥30% | +30pp |
| Custo/ciclo | (não medido) | $0.005 | — |

Custo/ciclo não foi instrumentado; adicionar logger de custo na Semana 2.
