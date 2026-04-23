"""Prometheus Exporter - Export metrics to Prometheus format"""

import logging
from prometheus_client import Counter, Histogram, Gauge

log = logging.getLogger("seeker.exporter")


class PrometheusExporter:
    """Exporta métricas para Prometheus"""

    def __init__(self, namespace: str = "seeker"):
        self.namespace = namespace
        log.info(f"[exporter] Iniciando Prometheus exporter com namespace '{namespace}'")

        # Counters
        self.llm_calls_total = Counter(
            f"{namespace}_llm_calls_total",
            "Total LLM API calls",
            ["provider", "model", "status"]
        )

        self.tokens_total = Counter(
            f"{namespace}_tokens_total",
            "Total tokens consumed",
            ["provider", "model", "type"]  # type = "input" ou "output"
        )

        self.goal_cycles = Counter(
            f"{namespace}_goal_cycles_total",
            "Total goal cycles",
            ["goal_id", "status"]  # status = "success" ou "failure"
        )

        # Histograms (para percentis)
        self.latency = Histogram(
            f"{namespace}_latency_ms",
            "Request latency in milliseconds",
            ["goal_id", "phase", "provider"],
            buckets=[10, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
        )

        self.memory_usage = Histogram(
            f"{namespace}_memory_mb",
            "Memory usage in MB",
            ["goal_id"],
            buckets=[1, 5, 10, 50, 100, 250, 500, 1000]
        )

        self.cost = Histogram(
            f"{namespace}_cost_usd",
            "API cost in USD",
            ["provider", "model"],
            buckets=[0.0001, 0.001, 0.01, 0.1, 1.0]
        )

        # Gauges (snapshot do estado atual)
        self.active_goals = Gauge(
            f"{namespace}_active_goals",
            "Number of active goals"
        )

        self.provider_availability = Gauge(
            f"{namespace}_provider_availability",
            "Provider availability (1=available, 0=down)",
            ["provider"]
        )

        self.goal_success_rate = Gauge(
            f"{namespace}_goal_success_rate",
            "Goal success rate percentage",
            ["goal_id"]
        )

    def record_llm_call(self, provider: str, model: str, tokens_in: int, tokens_out: int, cost: float, success: bool):
        """Registra uma chamada LLM"""
        status = "success" if success else "failure"

        self.llm_calls_total.labels(
            provider=provider,
            model=model,
            status=status
        ).inc()

        self.tokens_total.labels(
            provider=provider,
            model=model,
            type="input"
        ).inc(tokens_in)

        self.tokens_total.labels(
            provider=provider,
            model=model,
            type="output"
        ).inc(tokens_out)

        if cost > 0:
            self.cost.labels(
                provider=provider,
                model=model
            ).observe(cost)

    def record_goal_cycle(self, goal_id: str, success: bool, latency_ms: float, memory_mb: float, phase: str, provider: str):
        """Registra um ciclo de goal"""
        status = "success" if success else "failure"

        self.goal_cycles.labels(
            goal_id=goal_id,
            status=status
        ).inc()

        self.latency.labels(
            goal_id=goal_id,
            phase=phase,
            provider=provider
        ).observe(latency_ms)

        self.memory_usage.labels(
            goal_id=goal_id
        ).observe(memory_mb)

    def set_active_goals(self, count: int):
        """Atualiza número de goals ativos"""
        self.active_goals.set(count)

    def set_provider_status(self, provider: str, available: bool):
        """Atualiza status de um provider (1=ok, 0=down)"""
        self.provider_availability.labels(provider=provider).set(1 if available else 0)

    def set_goal_success_rate(self, goal_id: str, rate: float):
        """Atualiza taxa de sucesso de um goal"""
        self.goal_success_rate.labels(goal_id=goal_id).set(rate)
