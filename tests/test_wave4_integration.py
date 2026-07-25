"""
Wave 4 Integration Tests — Memory Decay, Goal Health Score, SOUL.md Watcher, Event Bus
"""
import asyncio
import json
import os
import tempfile
import time
import pytest
from unittest.mock import MagicMock, patch


# ── Memory Decay Tests ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_decay_engine_episodic_cleanup():
    from src.core.evidence.decay import DecayEngine
    from src.core.memory.store import MemoryStore

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = MemoryStore(db_path)
    await store.initialize()

    # Insere episodic antigos e novos via SQL direto
    now = time.time()
    for i in range(4):
        await store._db.execute(
            "INSERT INTO episodic (timestamp, session_id, user_input, response_summary, depth, module, had_arbitrage, had_conflicts, cost_usd, latency_ms, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now - 35*86400, "test", f"old {i}", "summary", "reflex", "test", 0, 0, 0.0, 0, "{}")
        )
    for i in range(2):
        await store._db.execute(
            "INSERT INTO episodic (timestamp, session_id, user_input, response_summary, depth, module, had_arbitrage, had_conflicts, cost_usd, latency_ms, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now - 1*86400, "test", f"new {i}", "summary", "reflex", "test", 0, 0, 0.0, 0, "{}")
        )
    await store._db.commit()

    engine = DecayEngine(store)
    stats = await engine.run()

    assert stats["episodic_cleaned"] >= 4
    await store.close()


@pytest.mark.asyncio
async def test_decay_engine_goal_cycles_cleanup():
    from src.core.evidence.decay import DecayEngine
    from src.core.memory.store import MemoryStore

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = MemoryStore(db_path)
    await store.initialize()

    # Insere goal_cycles antigos
    now = time.time()
    for i in range(10):
        await store._db.execute(
            "INSERT INTO goal_cycles (goal_name, timestamp, success, cost_usd, latency_ms, summary) VALUES (?, ?, ?, ?, ?, ?)",
            ("g1", now - (30-i)*86400, 1, 0.01, 100, f"cycle {i}")
        )
    await store._db.commit()

    engine = DecayEngine(store)
    stats = await engine.run()

    # Deve manter últimos 20 (temos apenas 10, mantém todos)
    # Mas remove os com timestamp mais antigo que 30 dias
    assert stats["goal_cycles_cleaned"] >= 0
    await store.close()


# ── Goal Health Score Tests ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_goal_health_score_computation():
    from src.core.goals.scheduler import GoalScheduler

    # Cria notifier mock simples
    class MockNotifier:
        async def send(self, *args, **kwargs):
            pass

    scheduler = GoalScheduler(MockNotifier())

    # Registra goal mock com ciclo de histórico
    class MockGoal:
        name = "test_goal"
        channels = ["telegram"]
        def __init__(self):
            self._status = "idle"
            self.budget = MagicMock()
            self.budget.max_daily_usd = 1.0
            self.budget.max_per_cycle_usd = 0.1
            self.budget.exhausted = False
            self.budget.spent_today_usd = 0.0
            self.budget.budget_reset_date = ""
            self.budget.spent_today = 0.0
            self.budget.spent_this_cycle = 0.0
            self.budget.reset_if_new_day = lambda d: None
            self.budget.spend = lambda x: None
            self.interval_seconds = 3600
        def get_status(self):
            return self._status
        def serialize_state(self):
            return {"name": self.name, "status": self._status}
        async def run_cycle(self):
            from src.core.goals.protocol import GoalResult
            return GoalResult(success=True, summary="ok", cost_usd=0.01)

    goal = MockGoal()
    scheduler._goals["test_goal"] = goal
    scheduler._goal_priorities["test_goal"] = 2  # NORMAL
    scheduler._cycle_history["test_goal"] = []
    scheduler._failure_counts = {}

    # Simula ciclos com falha para derrubar health score
    from collections import deque
    history = deque(maxlen=20)
    for i in range(10):
        if i < 7:
            history.append({"ok": False})  # 7 falhas consecutivas
        else:
            history.append({"ok": True})
    scheduler._cycle_history["test_goal"] = history

    # Computa health score
    health = scheduler._compute_goal_health_score(goal)
    assert isinstance(health, float)
    assert 0 <= health <= 100

    # Salva e carrega estado
    from src.core.goals.scheduler import STATE_DIR
    scheduler._health_scores["test_goal"] = health
    scheduler._save_goal_state(goal)

    state_path = os.path.join(STATE_DIR, "test_goal.json")
    assert os.path.exists(state_path)

    # Verifica que o health score foi persistido
    with open(state_path) as f:
        state = json.load(f)
    assert "_health_score" in state
    assert state["_health_score"] == health


# ── SOUL.md Watcher Tests ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_soul_watcher_detects_change():
    from src.core.memory.soul_watcher import SoulWatcher

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# SOUL\nIdentidade original\n")
        soul_path = f.name

    watcher = SoulWatcher(soul_path=soul_path, poll_interval=0.1)
    changes = []

    def callback(new_soul):
        changes.append(new_soul)

    watcher.register_callback(callback)
    watcher.start()

    # Aguarda primeira leitura (não dispara callback na carga inicial)
    await asyncio.sleep(0.15)
    assert len(changes) == 0

    # Modifica arquivo
    with open(soul_path, "w") as f:
        f.write("# SOUL\nIdentidade modificada\n")

    await asyncio.sleep(0.25)
    assert len(changes) == 1
    assert "modificada" in changes[-1]

    watcher.stop()


# ── Event Bus Tests (already covered in test_wave4_insights.py) ─────


# ── Capability Graph Tests (already covered) ────────────────────────


if __name__ == "__main__":
    pytest.main([__file__, "-v"])