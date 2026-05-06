"""
Sprint 11 Metrics Tracker — Monitoramento de otimizações

Rastreia:
- Latência: p50, p95, p99 (percentis)
- Cache: Hit rate por embedding
- Cascade: Fallback frequency
- Batch: Commits consolidados vs individuais
"""

import logging
from dataclasses import dataclass, field
from collections import deque
from statistics import median, quantiles
from datetime import datetime, timedelta

log = logging.getLogger("seeker.sprint11")


@dataclass
class LatencyMetrics:
    """Métricas de latência com percentis"""
    measurements: deque = field(default_factory=lambda: deque(maxlen=1000))

    def record(self, latency_ms: float) -> None:
        """Registra nova medição de latência"""
        self.measurements.append(latency_ms)

    @property
    def p50(self) -> float:
        """Latência mediana (p50)"""
        if len(self.measurements) == 0:
            return 0.0
        if len(self.measurements) == 1:
            return self.measurements[0]
        return median(self.measurements)

    @property
    def p95(self) -> float:
        """Latência p95"""
        if len(self.measurements) < 20:
            return 0.0
        return quantiles(self.measurements, n=20)[18]  # 19º de 20

    @property
    def p99(self) -> float:
        """Latência p99"""
        if len(self.measurements) < 100:
            return 0.0
        return quantiles(self.measurements, n=100)[98]  # 99º de 100

    @property
    def avg(self) -> float:
        """Média de latência"""
        if not self.measurements:
            return 0.0
        return sum(self.measurements) / len(self.measurements)

    @property
    def min(self) -> float:
        """Mínima latência"""
        return min(self.measurements) if self.measurements else 0.0

    @property
    def max(self) -> float:
        """Máxima latência"""
        return max(self.measurements) if self.measurements else 0.0

    def get_stats(self) -> dict:
        """Retorna todas as estatísticas"""
        return {
            "p50": f"{self.p50:.1f}ms",
            "p95": f"{self.p95:.1f}ms",
            "p99": f"{self.p99:.1f}ms",
            "avg": f"{self.avg:.1f}ms",
            "min": f"{self.min:.1f}ms",
            "max": f"{self.max:.1f}ms",
            "samples": len(self.measurements)
        }


@dataclass
class CacheMetrics:
    """Métricas de cache LRU"""
    total_lookups: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_evictions: int = 0

    @property
    def hit_rate(self) -> float:
        """Taxa de acerto em %"""
        if self.total_lookups == 0:
            return 0.0
        return (self.cache_hits / self.total_lookups) * 100

    @property
    def miss_rate(self) -> float:
        """Taxa de erro em %"""
        if self.total_lookups == 0:
            return 0.0
        return 100.0 - self.hit_rate

    def get_stats(self) -> dict:
        """Retorna estatísticas de cache"""
        return {
            "hit_rate": f"{self.hit_rate:.1f}%",
            "miss_rate": f"{self.miss_rate:.1f}%",
            "total_lookups": self.total_lookups,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "total_evictions": self.total_evictions,
        }


@dataclass
class CascadeMetrics:
    """Métricas de cascade fallback"""
    tier1_calls: int = 0  # NVIDIA
    tier1_success: int = 0
    tier2_calls: int = 0  # Groq
    tier2_success: int = 0
    tier3_calls: int = 0  # Gemini
    tier3_success: int = 0
    tier4_calls: int = 0  # DeepSeek
    tier4_success: int = 0
    tier5_calls: int = 0  # Ollama
    tier5_success: int = 0
    tier6_calls: int = 0  # Degraded

    @property
    def tier1_success_rate(self) -> float:
        """Taxa de sucesso da Tier 1"""
        if self.tier1_calls == 0:
            return 0.0
        return (self.tier1_success / self.tier1_calls) * 100

    @property
    def fallback_frequency(self) -> float:
        """% de chamadas que precisou fallback (não Tier 1)"""
        total = sum([self.tier1_calls, self.tier2_calls, self.tier3_calls,
                     self.tier4_calls, self.tier5_calls, self.tier6_calls])
        if total == 0:
            return 0.0
        fallback = sum([self.tier2_calls, self.tier3_calls, self.tier4_calls,
                        self.tier5_calls, self.tier6_calls])
        return (fallback / total) * 100

    def get_stats(self) -> dict:
        """Retorna estatísticas de cascade"""
        return {
            "tier1_success_rate": f"{self.tier1_success_rate:.1f}%",
            "fallback_frequency": f"{self.fallback_frequency:.1f}%",
            "tier1_total": self.tier1_calls,
            "tier2_total": self.tier2_calls,
            "tier3_total": self.tier3_calls,
            "tier4_total": self.tier4_calls,
            "tier5_total": self.tier5_calls,
            "tier6_total": self.tier6_calls,
        }


@dataclass
class BatchMetrics:
    """Métricas de batch consolidation"""
    total_operations: int = 0
    successful_operations: int = 0
    failed_operations: int = 0
    total_latency_ms: float = 0.0
    commits_consolidated: int = 0  # Quantos commits foram consolidados em 1
    commits_avoided: int = 0  # Commits que não foram necessários

    @property
    def success_rate(self) -> float:
        """Taxa de sucesso das operações"""
        if self.total_operations == 0:
            return 0.0
        return (self.successful_operations / self.total_operations) * 100

    @property
    def avg_latency(self) -> float:
        """Latência média por batch consolidado"""
        if self.commits_consolidated == 0:
            return 0.0
        return self.total_latency_ms / self.commits_consolidated

    def get_stats(self) -> dict:
        """Retorna estatísticas de batch"""
        return {
            "success_rate": f"{self.success_rate:.1f}%",
            "total_operations": self.total_operations,
            "commits_consolidated": self.commits_consolidated,
            "commits_avoided": self.commits_avoided,
            "latency_ms": f"{self.total_latency_ms:.1f}ms",
            "avg_latency_per_batch": f"{self.avg_latency:.1f}ms",
        }


@dataclass
class RemoteExecutorMetrics:
    """Métricas do Remote Executor — execução de ações autônomas"""
    total_plans: int = 0                    # Planos criados
    successful_executions: int = 0          # Execuções bem-sucedidas
    failed_executions: int = 0              # Execuções falhadas
    rollback_executions: int = 0            # Ações com rollback
    l0_manual_enqueued: int = 0             # Ações L0 enfileiradas
    l0_manual_approved: int = 0             # Ações L0 aprovadas
    l0_manual_rejected: int = 0             # Ações L0 rejeitadas
    l1_logged_executed: int = 0             # Ações L1 auto-executadas
    l2_silent_executed: int = 0             # Ações L2 auto-executadas
    total_cost_usd: float = 0.0             # Custo total acumulado
    execution_latency_ms: deque = field(default_factory=lambda: deque(maxlen=500))

    @property
    def total_executed(self) -> int:
        """Total de ações executadas (sucesso + falha + rollback)"""
        return self.successful_executions + self.failed_executions + self.rollback_executions

    @property
    def execution_success_rate(self) -> float:
        """Taxa de sucesso na execução"""
        if self.total_executed == 0:
            return 0.0
        return (self.successful_executions / self.total_executed) * 100

    @property
    def l0_approval_rate(self) -> float:
        """Taxa de aprovação das ações L0_MANUAL"""
        total_l0_responses = self.l0_manual_approved + self.l0_manual_rejected
        if total_l0_responses == 0:
            return 0.0
        return (self.l0_manual_approved / total_l0_responses) * 100

    @property
    def avg_execution_latency_ms(self) -> float:
        """Latência média de execução"""
        if not self.execution_latency_ms:
            return 0.0
        return sum(self.execution_latency_ms) / len(self.execution_latency_ms)

    def record_execution_latency(self, latency_ms: float) -> None:
        """Registra latência de uma execução"""
        self.execution_latency_ms.append(latency_ms)

    def get_stats(self) -> dict:
        """Retorna estatísticas do Remote Executor"""
        return {
            "total_plans": self.total_plans,
            "total_executed": self.total_executed,
            "successful": self.successful_executions,
            "failed": self.failed_executions,
            "rolled_back": self.rollback_executions,
            "success_rate": f"{self.execution_success_rate:.1f}%",
            "l0_manual_enqueued": self.l0_manual_enqueued,
            "l0_manual_approved": self.l0_manual_approved,
            "l0_manual_rejected": self.l0_manual_rejected,
            "l0_approval_rate": f"{self.l0_approval_rate:.1f}%",
            "l1_executed": self.l1_logged_executed,
            "l2_executed": self.l2_silent_executed,
            "total_cost_usd": f"${self.total_cost_usd:.4f}",
            "avg_latency_ms": f"{self.avg_execution_latency_ms:.1f}ms",
        }


class Sprint11Tracker:
    """Rastreador central de métricas do Sprint 11"""

    def __init__(self):
        """Inicializa tracker"""
        self.latency = LatencyMetrics()
        self.cache = CacheMetrics()
        self.cascade = CascadeMetrics()
        self.batch = BatchMetrics()
        self.remote_executor = RemoteExecutorMetrics()
        self.start_time = datetime.utcnow()

        log.info("[sprint11] Tracker inicializado")

    def record_latency(self, latency_ms: float) -> None:
        """Registra latência de uma operação"""
        self.latency.record(latency_ms)

    def record_cache_hit(self) -> None:
        """Registra um cache hit"""
        self.cache.total_lookups += 1
        self.cache.cache_hits += 1

    def record_cache_miss(self) -> None:
        """Registra um cache miss"""
        self.cache.total_lookups += 1
        self.cache.cache_misses += 1

    def record_cascade_call(self, tier: int, success: bool) -> None:
        """Registra chamada de cascade"""
        if tier == 1:
            self.cascade.tier1_calls += 1
            if success:
                self.cascade.tier1_success += 1
        elif tier == 2:
            self.cascade.tier2_calls += 1
            if success:
                self.cascade.tier2_success += 1
        elif tier == 3:
            self.cascade.tier3_calls += 1
            if success:
                self.cascade.tier3_success += 1
        elif tier == 4:
            self.cascade.tier4_calls += 1
            if success:
                self.cascade.tier4_success += 1
        elif tier == 5:
            self.cascade.tier5_calls += 1
            if success:
                self.cascade.tier5_success += 1
        elif tier == 6:
            self.cascade.tier6_calls += 1

    def record_batch_operation(self, success: bool, latency_ms: float) -> None:
        """Registra operação em batch"""
        self.batch.total_operations += 1
        if success:
            self.batch.successful_operations += 1
        else:
            self.batch.failed_operations += 1
        self.batch.total_latency_ms += latency_ms

    def record_batch_consolidation(self, operations: int) -> None:
        """Registra consolidação de N operações em 1 commit"""
        self.batch.commits_consolidated += 1
        self.batch.commits_avoided += max(0, operations - 1)

    # ────────────────────────────────────────────────────────
    # Remote Executor Metrics
    # ────────────────────────────────────────────────────────

    def record_remote_executor_plan(self) -> None:
        """Registra um novo plano criado"""
        self.remote_executor.total_plans += 1

    def record_remote_executor_execution(self, success: bool, execution_status: str, latency_ms: float, cost_usd: float) -> None:
        """
        Registra execução de ação.

        Args:
            success: True se executou sem erros
            execution_status: "SUCCESS" | "FAILED" | "ROLLED_BACK" | "CANCELLED"
            latency_ms: Tempo de execução em ms
            cost_usd: Custo da ação
        """
        if execution_status == "SUCCESS":
            self.remote_executor.successful_executions += 1
        elif execution_status == "FAILED":
            self.remote_executor.failed_executions += 1
        elif execution_status == "ROLLED_BACK":
            self.remote_executor.rollback_executions += 1

        self.remote_executor.record_execution_latency(latency_ms)
        self.remote_executor.total_cost_usd += cost_usd

    def record_remote_executor_autonomy_tier(self, tier: str) -> None:
        """Registra ação por tier de autonomia"""
        if tier == "L2_SILENT":
            self.remote_executor.l2_silent_executed += 1
        elif tier == "L1_LOGGED":
            self.remote_executor.l1_logged_executed += 1
        elif tier == "L0_MANUAL":
            self.remote_executor.l0_manual_enqueued += 1

    def record_remote_executor_approval(self, approved: bool) -> None:
        """Registra resposta a aprovação L0_MANUAL"""
        if approved:
            self.remote_executor.l0_manual_approved += 1
        else:
            self.remote_executor.l0_manual_rejected += 1

    def get_full_report(self) -> dict:
        """Retorna relatório completo de todas as métricas"""
        uptime = datetime.utcnow() - self.start_time

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": uptime.total_seconds(),
            "latency": self.latency.get_stats(),
            "cache": self.cache.get_stats(),
            "cascade": self.cascade.get_stats(),
            "batch": self.batch.get_stats(),
            "remote_executor": self.remote_executor.get_stats(),
        }

    def format_for_telegram(self) -> str:
        """Formata relatório para exibição em Telegram"""
        report = self.get_full_report()
        uptime = int(report["uptime_seconds"])

        lines = [
            "🚀 <b>SPRINT 11 OPTIMIZATION METRICS</b>\n",
            f"⏱️ Uptime: {uptime//3600}h {(uptime%3600)//60}m\n",

            "<b>📊 LATÊNCIA (Percentis):</b>",
            f"  p50: {report['latency']['p50']} | p95: {report['latency']['p95']} | p99: {report['latency']['p99']}",
            f"  avg: {report['latency']['avg']} (samples: {report['latency']['samples']})\n",

            "<b>💾 CACHE (LRU):</b>",
            f"  Hit Rate: {report['cache']['hit_rate']}",
            f"  Hits: {report['cache']['cache_hits']} | Misses: {report['cache']['cache_misses']}",
            f"  Evictions: {report['cache']['total_evictions']}\n",

            "<b>🎯 CASCADE FALLBACK:</b>",
            f"  Tier 1 Success: {report['cascade']['tier1_success_rate']}",
            f"  Fallback Frequency: {report['cascade']['fallback_frequency']}",
            f"  Tier1: {report['cascade']['tier1_total']} | T2: {report['cascade']['tier2_total']} | T3: {report['cascade']['tier3_total']}\n",

            "<b>⚡ BATCH CONSOLIDATION:</b>",
            f"  Success Rate: {report['batch']['success_rate']}",
            f"  Consolidated: {report['batch']['commits_consolidated']} commits",
            f"  Commits Avoided: {report['batch']['commits_avoided']}",
            f"  Avg Latency: {report['batch']['avg_latency_per_batch']}\n",

            "<b>🤖 REMOTE EXECUTOR:</b>",
            f"  Plans: {report['remote_executor']['total_plans']}",
            f"  Executed: {report['remote_executor']['total_executed']} (Success: {report['remote_executor']['success_rate']})",
            f"  L0 Manual: {report['remote_executor']['l0_manual_enqueued']} enqueued | "
            f"✅ {report['remote_executor']['l0_manual_approved']} | ❌ {report['remote_executor']['l0_manual_rejected']}",
            f"  L1 Auto: {report['remote_executor']['l1_executed']} | L2 Silent: {report['remote_executor']['l2_executed']}",
            f"  Cost: {report['remote_executor']['total_cost_usd']} | "
            f"Latency: {report['remote_executor']['avg_latency_ms']}\n",
        ]

        return "".join(lines)
