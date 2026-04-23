"""
Crew Router - Map cognitive depth + user intent to crews

Takes CognitiveDepth from CognitiveLoadRouter and determines:
- Which crews to invoke
- Whether they run in parallel
- Execution order
"""

import logging
from typing import Optional

from ..router.cognitive_load import CognitiveDepth as CognitiveDepthRouter
from .interfaces import SupervisorDecision

log = logging.getLogger("seeker.crew_router")


class CrewRouter:
    """Routes user input to appropriate crews based on cognitive depth"""

    def __init__(self):
        # Crew execution templates by cognitive depth
        self.templates = {
            CognitiveDepthRouter.REFLEX: {
                "crews": ["monitor"],  # Fast response, no heavy lifting
                "parallel": False,
                "estimated_latency_ms": 500,
                "estimated_cost": 0.001,
            },
            CognitiveDepthRouter.DELIBERATE: {
                "crews": ["monitor", "hunter"],  # Sensing + seeking
                "parallel": True,
                "estimated_latency_ms": 5000,
                "estimated_cost": 0.05,
            },
            CognitiveDepthRouter.DEEP: {
                "crews": ["monitor", "hunter", "analyst"],  # Full analysis
                "parallel": True,
                "estimated_latency_ms": 15000,
                "estimated_cost": 0.20,
            },
        }

    def route(
        self,
        user_input: str,
        cognitive_depth: CognitiveDepthRouter,
        include_vision: bool = False,
        include_admin: bool = False,
    ) -> SupervisorDecision:
        """
        Route user input to crews based on cognitive depth

        Args:
            user_input: User's request
            cognitive_depth: Depth level (reflex/deliberate/deep from CognitiveDepthRouter)
            include_vision: Add vision crew for image/screenshot analysis
            include_admin: Add admin crew for governance tasks

        Returns:
            SupervisorDecision with crew targets and metadata
        """
        # Get base template
        template = self.templates.get(
            cognitive_depth, self.templates[CognitiveDepthRouter.DELIBERATE]
        )

        crews = list(template["crews"])
        cost = template["estimated_cost"]
        latency = template["estimated_latency_ms"]
        parallelizable = template["parallel"]

        # Add optional crews
        if include_vision:
            crews.append("vision")
            cost += 0.05
            latency += 5000
            # Vision can run in parallel if already parallelizable
            if parallelizable:
                latency = max(latency, template["estimated_latency_ms"] + 5000)

        if include_admin:
            crews.append("admin")
            cost += 0.02
            latency += 1000

        # Always include executor if user is requesting actions
        # Executor may require sequential execution for REFLEX/DELIBERATE
        if self._detect_action_intent(user_input) and "executor" not in crews:
            crews.append("executor")
            cost += 0.03
            if parallelizable:
                latency += 3000
            else:
                latency = max(latency, 1000) + 3000  # Sequential for simple requests

        reason = self._generate_routing_reason(cognitive_depth, crews)

        decision = SupervisorDecision(
            target_crews=crews,
            parallelizable=parallelizable,
            cognitive_depth=cognitive_depth,
            estimated_cost=cost,
            estimated_latency_ms=latency,
            reasoning=reason,
        )

        log.info(
            f"Routed to crews: {crews} (depth={cognitive_depth.value}, cost=${cost:.3f})"
        )
        return decision

    def _detect_action_intent(self, text: str) -> bool:
        """Detect if user wants something executed/done"""
        action_keywords = [
            "execute",
            "execute",
            "faça",
            "faz",
            "fazer",
            "envie",
            "enviem",
            "crie",
            "criem",
            "delete",
            "deleta",
            "update",
            "atualiza",
            "backup",
            "commit",
            "deploy",
            "rodar",
            "executar",
            "dispara",
            "dispare",
        ]
        text_lower = text.lower()
        return any(kw in text_lower for kw in action_keywords)

    def _generate_routing_reason(
        self, depth: CognitiveDepthRouter, crews: list[str]
    ) -> str:
        """Generate human-readable reason for routing"""
        depth_reasons = {
            CognitiveDepthRouter.REFLEX: "Simple response",
            CognitiveDepthRouter.DELIBERATE: "Moderate complexity",
            CognitiveDepthRouter.DEEP: "Complex analysis required",
        }
        crew_names = ", ".join(crews)
        return f"{depth_reasons.get(depth, 'Unknown')} -> {crew_names}"


# Singleton instance
crew_router = CrewRouter()
