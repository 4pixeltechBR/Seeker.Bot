"""
Testes para Sprint11Tracker — Fase 4 (Monitoramento Detalhado)
Validação de rastreamento de otimizações
"""

import pytest
from src.core.metrics.sprint11_tracker import (
    Sprint11Tracker,
    LatencyMetrics,
    CacheMetrics,
    CascadeMetrics,
    BatchMetrics,
)


class TestLatencyMetrics:
    """Testes de métricas de latência"""

    def test_initialization(self):
        """Testa inicialização"""
        metrics = LatencyMetrics()
        assert metrics.p50 == 0.0
        assert metrics.p95 == 0.0
        assert metrics.p99 == 0.0
        assert metrics.avg == 0.0

    def test_record_single_measurement(self):
        """Testa registro de uma medição"""
        metrics = LatencyMetrics()
        metrics.record(100.0)
        assert len(metrics.measurements) == 1
        assert metrics.p50 == 100.0
        assert metrics.avg == 100.0

    def test_percentile_calculations(self):
        """Testa cálculo de percentis"""
        metrics = LatencyMetrics()
        # Registra 100 valores de 10ms até 1010ms
        for i in range(100):
            metrics.record(10.0 + i * 10)

        # p50 deve estar próximo de 510ms (mediana)
        assert 500 < metrics.p50 < 520

        # p95 deve estar próximo de 950ms
        assert 940 < metrics.p95 < 960

        # p99 deve estar próximo de 990ms
        assert 980 < metrics.p99 < 1000

    def test_min_max(self):
        """Testa valores mínimo e máximo"""
        metrics = LatencyMetrics()
        metrics.record(10.0)
        metrics.record(50.0)
        metrics.record(30.0)
        metrics.record(100.0)

        assert metrics.min == 10.0
        assert metrics.max == 100.0

    def test_get_stats(self):
        """Testa retorno de estatísticas"""
        metrics = LatencyMetrics()
        metrics.record(50.0)
        metrics.record(100.0)

        stats = metrics.get_stats()
        assert "p50" in stats
        assert "p95" in stats
        assert "p99" in stats
        assert "avg" in stats
        assert "samples" in stats
        assert stats["samples"] == 2


class TestCacheMetrics:
    """Testes de métricas de cache"""

    def test_initialization(self):
        """Testa inicialização"""
        metrics = CacheMetrics()
        assert metrics.hit_rate == 0.0
        assert metrics.miss_rate == 0.0
        assert metrics.total_lookups == 0

    def test_hit_rate_calculation(self):
        """Testa cálculo de hit rate"""
        metrics = CacheMetrics()
        metrics.total_lookups = 10
        metrics.cache_hits = 7
        metrics.cache_misses = 3

        assert metrics.hit_rate == 70.0
        assert metrics.miss_rate == 30.0

    def test_zero_lookups(self):
        """Testa com zero lookups"""
        metrics = CacheMetrics()
        assert metrics.hit_rate == 0.0
        assert metrics.miss_rate == 0.0

    def test_get_stats(self):
        """Testa retorno de estatísticas"""
        metrics = CacheMetrics()
        metrics.total_lookups = 20
        metrics.cache_hits = 15
        metrics.cache_misses = 5
        metrics.total_evictions = 2

        stats = metrics.get_stats()
        assert stats["hit_rate"] == "75.0%"
        assert stats["miss_rate"] == "25.0%"
        assert stats["total_lookups"] == 20
        assert stats["total_evictions"] == 2


class TestCascadeMetrics:
    """Testes de métricas de cascade"""

    def test_initialization(self):
        """Testa inicialização"""
        metrics = CascadeMetrics()
        assert metrics.tier1_success_rate == 0.0
        assert metrics.fallback_frequency == 0.0

    def test_tier1_success_rate(self):
        """Testa taxa de sucesso da Tier 1"""
        metrics = CascadeMetrics()
        metrics.tier1_calls = 10
        metrics.tier1_success = 9

        assert metrics.tier1_success_rate == 90.0

    def test_fallback_frequency(self):
        """Testa frequência de fallback"""
        metrics = CascadeMetrics()
        # 100 chamadas: 95 na Tier 1, 5 fallback
        metrics.tier1_calls = 95
        metrics.tier1_success = 95
        metrics.tier2_calls = 5

        total = 100
        fallback = 5
        expected_freq = (fallback / total) * 100

        assert metrics.fallback_frequency == expected_freq

    def test_get_stats(self):
        """Testa retorno de estatísticas"""
        metrics = CascadeMetrics()
        metrics.tier1_calls = 100
        metrics.tier1_success = 95
        metrics.tier2_calls = 5

        stats = metrics.get_stats()
        assert "tier1_success_rate" in stats
        assert "fallback_frequency" in stats
        assert stats["tier1_total"] == 100


class TestBatchMetrics:
    """Testes de métricas de batch"""

    def test_initialization(self):
        """Testa inicialização"""
        metrics = BatchMetrics()
        assert metrics.success_rate == 0.0
        assert metrics.avg_latency == 0.0
        assert metrics.commits_consolidated == 0

    def test_success_rate(self):
        """Testa taxa de sucesso"""
        metrics = BatchMetrics()
        metrics.total_operations = 10
        metrics.successful_operations = 8
        metrics.failed_operations = 2

        assert metrics.success_rate == 80.0

    def test_consolidation_savings(self):
        """Testa economia de consolidação"""
        metrics = BatchMetrics()
        # 5 operações consolidadas em 1 commit = 4 commits evitados
        metrics.commits_consolidated = 1
        metrics.commits_avoided = 4

        assert metrics.commits_consolidated == 1
        assert metrics.commits_avoided == 4

    def test_avg_latency(self):
        """Testa latência média por batch"""
        metrics = BatchMetrics()
        metrics.total_latency_ms = 100.0
        metrics.commits_consolidated = 2

        assert metrics.avg_latency == 50.0

    def test_get_stats(self):
        """Testa retorno de estatísticas"""
        metrics = BatchMetrics()
        metrics.total_operations = 20
        metrics.successful_operations = 19
        metrics.failed_operations = 1
        metrics.commits_consolidated = 5
        metrics.commits_avoided = 20
        metrics.total_latency_ms = 500.0

        stats = metrics.get_stats()
        assert "success_rate" in stats
        assert "commits_consolidated" in stats
        assert "commits_avoided" in stats
        assert stats["success_rate"] == "95.0%"


class TestSprint11Tracker:
    """Testes do tracker central"""

    def test_initialization(self):
        """Testa inicialização"""
        tracker = Sprint11Tracker()
        assert tracker.latency is not None
        assert tracker.cache is not None
        assert tracker.cascade is not None
        assert tracker.batch is not None

    def test_record_latency(self):
        """Testa registro de latência"""
        tracker = Sprint11Tracker()
        tracker.record_latency(100.0)
        tracker.record_latency(150.0)
        tracker.record_latency(120.0)

        assert len(tracker.latency.measurements) == 3
        assert tracker.latency.avg == pytest.approx(123.33, rel=0.1)

    def test_record_cache_operations(self):
        """Testa registro de operações de cache"""
        tracker = Sprint11Tracker()
        tracker.record_cache_hit()
        tracker.record_cache_hit()
        tracker.record_cache_miss()

        assert tracker.cache.cache_hits == 2
        assert tracker.cache.cache_misses == 1
        assert tracker.cache.total_lookups == 3
        assert tracker.cache.hit_rate == pytest.approx(66.67, rel=0.1)

    def test_record_cascade_calls(self):
        """Testa registro de chamadas cascade"""
        tracker = Sprint11Tracker()
        tracker.record_cascade_call(tier=1, success=True)
        tracker.record_cascade_call(tier=1, success=True)
        tracker.record_cascade_call(tier=2, success=True)

        assert tracker.cascade.tier1_calls == 2
        assert tracker.cascade.tier1_success == 2
        assert tracker.cascade.tier2_calls == 1
        assert tracker.cascade.tier1_success_rate == 100.0
        assert tracker.cascade.fallback_frequency == pytest.approx(33.33, rel=0.1)

    def test_record_batch_operations(self):
        """Testa registro de operações batch"""
        tracker = Sprint11Tracker()
        tracker.record_batch_operation(success=True, latency_ms=50.0)
        tracker.record_batch_operation(success=True, latency_ms=60.0)
        tracker.record_batch_operation(success=False, latency_ms=40.0)

        assert tracker.batch.total_operations == 3
        assert tracker.batch.successful_operations == 2
        assert tracker.batch.failed_operations == 1
        assert tracker.batch.success_rate == pytest.approx(66.67, rel=0.1)
        assert tracker.batch.total_latency_ms == 150.0

    def test_record_batch_consolidation(self):
        """Testa registro de consolidação de batch"""
        tracker = Sprint11Tracker()
        # 5 operações consolidadas em 1 commit = 4 commits evitados
        tracker.record_batch_consolidation(operations=5)
        tracker.record_batch_consolidation(operations=3)

        assert tracker.batch.commits_consolidated == 2
        assert tracker.batch.commits_avoided == 6  # (5-1) + (3-1)

    def test_get_full_report(self):
        """Testa geração de relatório completo"""
        tracker = Sprint11Tracker()
        tracker.record_latency(100.0)
        tracker.record_cache_hit()
        tracker.record_cascade_call(tier=1, success=True)
        tracker.record_batch_operation(success=True, latency_ms=50.0)

        report = tracker.get_full_report()

        assert "timestamp" in report
        assert "uptime_seconds" in report
        assert "latency" in report
        assert "cache" in report
        assert "cascade" in report
        assert "batch" in report

    def test_format_for_telegram(self):
        """Testa formatação para Telegram"""
        tracker = Sprint11Tracker()
        tracker.record_latency(100.0)
        tracker.record_cache_hit()
        tracker.record_cascade_call(tier=1, success=True)
        tracker.record_batch_operation(success=True, latency_ms=50.0)

        formatted = tracker.format_for_telegram()

        assert "SPRINT 11" in formatted
        assert "LATÊNCIA" in formatted
        assert "CACHE" in formatted
        assert "CASCADE" in formatted
        assert "BATCH" in formatted
        assert "<b>" in formatted  # HTML formatting


# Run: pytest tests/test_sprint11_tracker.py -v
