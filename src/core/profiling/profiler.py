"""System Profiler - Collect and Aggregate Performance Metrics"""

import cProfile
import pstats
import psutil
import asyncio
import logging
from typing import Optional, List
from collections import deque
from datetime import datetime, timedelta

from .metrics import PerformanceMetrics, GoalMetrics

log = logging.getLogger("seeker.profiling")


class SystemProfiler:
    """Profiler para medir performance de goals e fases"""

    def __init__(self, history_size: int = 100):
        self.history: deque = deque(maxlen=history_size)
        self.goal_metrics: dict[str, GoalMetrics] = {}
        self.process = psutil.Process()
        self.active_profiles: dict = {}  # goal_id_phase -> profile data

    def start_profiling(self, goal_id: str, phase_name: str) -> PerformanceMetrics:
        """Inicia profiling de uma fase"""
        try:
            loop = asyncio.get_event_loop()
            start_time = loop.time()
        except RuntimeError:
            start_time = asyncio.get_running_loop().time()

        metric = PerformanceMetrics(
            goal_id=goal_id,
            phase_name=phase_name,
            start_time=start_time
        )

        # Iniciar cProfile
        pr = cProfile.Profile()
        pr.enable()
        self.active_profiles[f"{goal_id}_{phase_name}"] = {
            "profile": pr,
            "metric": metric,
            "memory_start": self.process.memory_info().rss / 1024 / 1024
        }

        return metric

    def end_profiling(
        self,
        goal_id: str,
        phase_name: str,
        llm_calls: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        provider: str = "",
        model: str = "",
        success: bool = True,
        error_msg: str = ""
    ) -> Optional[PerformanceMetrics]:
        """Finaliza profiling e retorna métricas"""

        key = f"{goal_id}_{phase_name}"
        if key not in self.active_profiles:
            log.warning(f"[profiler] Profiling não iniciado para {key}")
            return None

        prof_data = self.active_profiles.pop(key)
        metric = prof_data["metric"]
        pr = prof_data["profile"]

        # Parar profiling
        pr.disable()

        # Preencher métricas
        try:
            loop = asyncio.get_event_loop()
            end_time = loop.time()
        except RuntimeError:
            end_time = asyncio.get_running_loop().time()

        metric.end_time = end_time
        metric.memory_mb = self.process.memory_info().rss / 1024 / 1024 - prof_data["memory_start"]
        try:
            metric.cpu_percent = self.process.cpu_percent(interval=0.01)
        except:
            metric.cpu_percent = 0.0
        metric.llm_calls = llm_calls
        metric.input_tokens = input_tokens
        metric.output_tokens = output_tokens
        metric.cost_usd = cost_usd
        metric.provider = provider
        metric.model = model
        metric.success = success
        metric.error_msg = error_msg

        # Salvar no histórico
        self.history.append(metric)

        # Atualizar goal metrics
        self._update_goal_metrics(metric)

        log.debug(
            f"[profiler] {phase_name} ({goal_id}): "
            f"{metric.latency_ms:.0f}ms | ${metric.cost_usd:.4f} | {metric.llm_calls} calls"
        )

        return metric

    def _update_goal_metrics(self, metric: PerformanceMetrics):
        """Atualiza agregações por goal"""
        goal_id = metric.goal_id

        if goal_id not in self.goal_metrics:
            self.goal_metrics[goal_id] = GoalMetrics(
                goal_id=goal_id,
                goal_name=goal_id
            )

        goal = self.goal_metrics[goal_id]
        goal.cycles_total += 1

        if metric.success:
            goal.cycles_success += 1
        else:
            goal.cycles_failed += 1

        # Atualizar agregações
        goal.total_cost_usd += metric.cost_usd
        goal.total_latency_ms += metric.latency_ms
        goal.avg_latency_ms = goal.total_latency_ms / goal.cycles_total
        goal.max_latency_ms = max(goal.max_latency_ms, metric.latency_ms)
        if metric.latency_ms > 0:
            goal.min_latency_ms = min(goal.min_latency_ms, metric.latency_ms)
        goal.total_tokens += metric.total_tokens
        goal.total_memory_mb += abs(metric.memory_mb)  # Absoluto para evitar negativos

        # Provider breakdown
        if metric.provider:
            goal.provider_costs[metric.provider] = goal.provider_costs.get(metric.provider, 0) + metric.cost_usd
            goal.provider_calls[metric.provider] = goal.provider_calls.get(metric.provider, 0) + 1

        # Phase breakdown
        if metric.phase_name:
            goal.phase_latencies[metric.phase_name] = metric.latency_ms

    def get_worst_offenders(self, limit: int = 10, metric: str = "latency_ms") -> List[PerformanceMetrics]:
        """Retorna as piores métricas (latência mais alta, etc)"""
        sorted_history = sorted(
            self.history,
            key=lambda m: getattr(m, metric, 0),
            reverse=True
        )
        return sorted_history[:limit]

    def get_goal_stats(self, goal_id: str) -> Optional[GoalMetrics]:
        """Retorna estatísticas agregadas de um goal"""
        return self.goal_metrics.get(goal_id)

    def get_all_stats(self) -> dict[str, GoalMetrics]:
        """Retorna todas as estatísticas por goal"""
        return self.goal_metrics

    def get_recent_metrics(self, minutes: int = 5) -> List[PerformanceMetrics]:
        """Retorna métricas dos últimos N minutos"""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        return [m for m in self.history if m.timestamp > cutoff]

    def reset_stats(self, goal_id: str | None = None):
        """Reseta estatísticas de um goal ou todas"""
        if goal_id:
            if goal_id in self.goal_metrics:
                del self.goal_metrics[goal_id]
        else:
            self.goal_metrics.clear()
            self.history.clear()
        log.info(f"[profiler] Stats resetados para {goal_id or 'todos os goals'}")
