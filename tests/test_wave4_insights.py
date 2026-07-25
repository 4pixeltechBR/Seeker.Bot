"""
Smoke tests para Wave 4 insights.
"""

import asyncio
import pytest

from src.core.events import EventBus, get_event_bus
from src.core.capability_graph import CapabilityGraph, get_capability_graph


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singletons between tests."""
    import src.core.events as ev
    import src.core.capability_graph as cg

    ev._event_bus = None
    cg._graph = None
    yield
    ev._event_bus = None
    cg._graph = None


@pytest.mark.asyncio
async def test_event_bus_fanout():
    bus = EventBus()
    received = []

    async def handler(payload):
        received.append(payload)

    bus.subscribe("test.topic", handler)
    await bus.emit("test.topic", {"x": 1})
    await asyncio.sleep(0.05)
    assert len(received) == 1
    assert received[0]["x"] == 1
    assert received[0]["_topic"] == "test.topic"


def test_capability_graph_resolve():
    g = CapabilityGraph()
    g.register("a", ["cap_a"])
    g.register("b", ["cap_b"], dependencies=["cap_a"])
    g.register("c", ["cap_c"], dependencies=["cap_b"])
    assert g.resolve(["cap_c"]) == ["a", "b", "c"]


def test_capability_graph_missing():
    g = CapabilityGraph()
    with pytest.raises(RuntimeError, match="não registrada"):
        g.resolve(["missing"])


def test_capability_graph_cycle():
    g = CapabilityGraph()
    g.register("x", ["cap_x"], dependencies=["cap_y"])
    g.register("y", ["cap_y"], dependencies=["cap_x"])
    with pytest.raises(RuntimeError, match="Ciclo"):
        g.resolve(["cap_x"])


def test_singletons():
    assert get_event_bus() is get_event_bus()
    assert get_capability_graph() is get_capability_graph()
