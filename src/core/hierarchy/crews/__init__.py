"""
Seeker.Bot v1.0 - Crews

6 specialized hierarchical crews:
1. MONITOR CREW - Always-on sensing
2. HUNTER CREW - Seeking opportunities
3. EXECUTOR CREW - Taking actions
4. ANALYST CREW - Deep reasoning
5. VISION CREW - OCR and visual analysis
6. ADMIN CREW - Meta-skills and governance
"""

from abc import ABC, abstractmethod
from typing import Any

from ..interfaces import CrewRequest, CrewResult, Crew, CrewPriority
import logging

log = logging.getLogger("seeker.crews")


class BaseCrew(ABC, Crew):
    """Base class for all crews"""

    def __init__(self, crew_id: str, priority: CrewPriority = CrewPriority.NORMAL):
        self.crew_id = crew_id
        self.priority = priority
        self._is_healthy = True

    async def execute(self, request: CrewRequest) -> CrewResult:
        """
        Execute crew with error handling wrapper

        Subclasses implement _execute_internal()
        """
        try:
            result = await self._execute_internal(request)
            self._is_healthy = True
            return result
        except Exception as e:
            log.error(f"Crew '{self.crew_id}' error: {e}")
            self._is_healthy = False
            return CrewResult(
                response=f"Crew '{self.crew_id}' error: {str(e)}",
                crew_id=self.crew_id,
                cost_usd=0.0,
                llm_calls=0,
                confidence=0.0,
                latency_ms=0,
                sources=[],
            )

    @abstractmethod
    async def _execute_internal(self, request: CrewRequest) -> CrewResult:
        """Crew-specific execution logic - override in subclasses"""
        pass

    async def health_check(self) -> bool:
        """Check if crew is operational"""
        return self._is_healthy

    def get_status(self) -> dict[str, Any]:
        """Get crew status and metrics"""
        return {
            "crew_id": self.crew_id,
            "priority": self.priority.value,
            "is_healthy": self._is_healthy,
            "status": "operational" if self._is_healthy else "degraded",
        }


# Import crew implementations (will be empty for Phase 0)
from . import monitor_crew
from . import hunter_crew
from . import executor_crew
from . import analyst_crew
from . import vision_crew
from . import admin_crew

__all__ = [
    "BaseCrew",
    "monitor_crew",
    "hunter_crew",
    "executor_crew",
    "analyst_crew",
    "vision_crew",
    "admin_crew",
]
