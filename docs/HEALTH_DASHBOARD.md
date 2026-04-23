# Health Dashboard (4.1) — Monitoring de Goals

Sistema de monitoramento avançado para acompanhar saúde e desempenho dos goals autônomos.

## Recursos

### 1. **Status Report** (`get_status_report()`)
Dashboard simples no Telegram — mostra:
- ✅/❌ Trend bar (últimas 10 execuções)
- Taxa de sucesso (%)
- Latência média (últimas 5)
- Budget por goal
- Falhas consecutivas
- Fricção controlada (rethinks, SARA edits, rate limits)

```python
scheduler = GoalScheduler(notifier)
report = scheduler.get_status_report()
# Retorna HTML formatado para Telegram
```

### 2. **Health Dashboard** (`get_health_dashboard()`)
Retorna JSON estruturado com métricas completas:

```python
dashboard = scheduler.get_health_dashboard()
# {
#   "timestamp": 1234567890.5,
#   "date": "2026-04-08",
#   "global_budget": {"spent": 1.5, "limit": 2.0},
#   "friction_metrics": {"rethinks_blocked": 2, "sara_edits": 1, "rate_limits": 0},
#   "goals": {
#     "revenue_hunter": {...},
#     "sense_news": {...}
#   },
#   "summary": {
#     "total_goals": 2,
#     "avg_success_rate": 85.5,
#     "total_cost_today": 1.5
#   }
# }
```

### 3. **Goal Metrics** (`get_goal_metrics(goal_name)`)
Métricas detalhadas de um goal:

```python
metrics = scheduler.get_goal_metrics("revenue_hunter")
# {
#   "name": "revenue_hunter",
#   "status": "RUNNING",
#   "budget": {"spent_today": 0.5, "limit": 1.0},
#   "metrics": {
#     "success_rate": 85.5,           # % geral
#     "recent_5_success_rate": 100.0, # % últimas 5
#     "trend": "📈",                  # 📈/📉/➡️
#     "total_cycles": 20,
#     "avg_latency": 1.23,
#     "min_latency": 0.5,
#     "max_latency": 2.8,
#     "total_cost": 0.5,
#     "consecutive_failures": 0
#   },
#   "last_run": {
#     "timestamp": 1234567800.0,
#     "age_seconds": 90.5,
#     "success": true,
#     "cost": 0.05,
#     "latency": 1.2,
#     "summary": "Generated 3 leads"
#   },
#   "history": [
#     {"ts": ..., "ok": true, "cost": 0.05, "latency": 1.2},
#     {"ts": ..., "ok": true, "cost": 0.05, "latency": 1.1},
#     ...  # últimas 10 execuções
#   ]
# }
```

## Persistência

Histórico de ciclos é persistido automaticamente em `data/goals/{goal_name}.json`:

```json
{
  "name": "revenue_hunter",
  "_budget": {"spent_today_usd": 0.5, "budget_reset_date": "2026-04-08"},
  "_failures": 0,
  "_cycle_history": [
    {"ts": 1234567890, "ok": true, "cost": 0.05, "latency": 1.2, "summary": "OK"},
    {"ts": 1234567800, "ok": true, "cost": 0.05, "latency": 1.1, "summary": "OK"},
    ...  # últimas 20 execuções
  ]
}
```

Ao reiniciar, o histórico é carregado automaticamente.

## Métricas Rastreadas

| Métrica | Descrição |
|---------|-----------|
| **success_rate** | % de ciclos que completaram com sucesso |
| **recent_5_success_rate** | Taxa de sucesso das últimas 5 execuções (detecção de degradação) |
| **trend** | 📈 melhora, 📉 piora, ➡️ estável |
| **total_cycles** | Ciclos executados (histórico de 20) |
| **avg_latency** | Tempo médio de execução |
| **min/max_latency** | Extremos de latência (detecção de gargalos) |
| **total_cost** | USD gasto nas últimas 20 execuções |
| **consecutive_failures** | Contador para backoff automático |

## Casos de Uso

### 1. Dashboard Web (futuro)
```python
# GET /api/health
dashboard = scheduler.get_health_dashboard()
return jsonify(dashboard)
```

### 2. Alertas Proativos
```python
metrics = scheduler.get_goal_metrics("revenue_hunter")
if metrics["metrics"]["recent_5_success_rate"] < 50:
    # Alerta: degradação detectada
    await notifier.send("admin", "⚠️ Revenue Hunter degradado", ...)
```

### 3. Análise de Custo
```python
# Custo por ciclo em média
dashboard = scheduler.get_health_dashboard()
for goal_name, metrics in dashboard["goals"].items():
    cost_per_cycle = metrics["metrics"]["total_cost"] / metrics["metrics"]["total_cycles"]
    print(f"{goal_name}: ${cost_per_cycle:.4f}/ciclo")
```

### 4. SLA Monitoring
```python
# Verificar cumprimento de SLA (ex: 95% success rate)
if metrics["metrics"]["success_rate"] < 95:
    # Falha no SLA
    incident = create_incident(goal_name, "Low success rate")
```

## Limitações

- Histórico limitado a 20 ciclos por goal (reduz memória)
- Métricas resetam quando o scheduler reinicia (exceto se persistido em JSON)
- Trend analysis requer pelo menos 10 ciclos para ser significativo

## Melhorias Futuras

- [ ] Exportar metrics para Prometheus/Grafana
- [ ] Alertas baseados em limites configuráveis
- [ ] Correlação com custos de LLM por providenci
- [ ] Análise de padrões de falha (ex: "sempre falha entre 15-16h UTC")
