"""
Seeker.Bot — Event Bus (in-process pub/sub)

src/core/events.py

In-process event bus para desacoplar skills, goals e crews.
Zero dependencias externas (sem redis/kafka).
"""

import asyncio
import logging
from typing import Callable, Any
from collections import defaultdict

log = logging.getLogger("seeker.events")


class EventBus:
    """In-process pub/sub event bus with async fanout."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable[[dict[str, Any]], Any]]] = defaultdict(list)
        self._background_tasks: set[asyncio.Task] = set()

    def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Register a handler for a topic."""
        if handler not in self._subscribers[topic]:
            self._subscribers[topic].append(handler)
            log.debug(f"[events] Handler subscribed to {topic}")

    def unsubscribe(self, topic: str, handler: Callable[[dict[str, Any]], Any]) -> bool:
        """Remove a handler from a topic."""
        if topic in self._subscribers and handler in self._subscribers[topic]:
            self._subscribers[topic].remove(handler)
            return True
        return False

    async def emit(self, topic: str, payload: dict[str, Any] | None = None) -> None:
        """Emit an event to all subscribers asynchronously."""
        payload = payload or {}
        payload["_topic"] = topic
        handlers = list(self._subscribers.get(topic, []))
        if not handlers:
            return

        async def _notify(handler: Callable) -> None:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(payload)
                else:
                    handler(payload)
            except Exception as e:
                log.warning(f"[events] Handler failed for {topic}: {e}")

        # Fan-out via background tasks (non-blocking for emitter)
        for handler in handlers:
            task = asyncio.create_task(_notify(handler))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        log.debug(f"[events] Emitted {topic} to {len(handlers)} handlers")

    def topics(self) -> list[str]:
        return list(self._subscribers.keys())

    async def shutdown(self, timeout: float = 1.0) -> None:
        """Cancela tasks pendentes e aguarda finalização durante shutdown."""
        pending = list(self._background_tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=timeout)
        log.debug(f"[events] Shutdown completo — {len(pending)} tasks canceladas")


# Singleton global
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
