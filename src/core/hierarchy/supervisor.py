"""
Seeker.Bot v1.0 - Supervisor Agent

LangGraph hierarchical supervisor that coordinates 6 specialized crews.
"""

import asyncio
import logging
import time
from typing import Optional, Any
from datetime import datetime

from langgraph.graph import StateGraph, START, END

from ..router.cognitive_load import CognitiveLoadRouter, CognitiveDepth
from .interfaces import (
    CrewRequest,
    CrewResult,
    SupervisorDecision,
    Crew,
)
from .memory.events import GoalEventLog, GoalEventType
from .crew_router import crew_router

log = logging.getLogger("seeker.supervisor")


class SupervisorState:
    """State machine for supervisor execution"""

    def __init__(self):
        self.user_input: str = ""
        self.user_id: int = 0
        self.session_id: str = ""
        self.cognitive_depth: CognitiveDepth = CognitiveDepth.DELIBERATE
        self.memory_context: list[str] = []
        self.decision: Optional[SupervisorDecision] = None
        self.crew_results: dict[str, CrewResult] = {}
        self.final_response: str = ""
        self.cost_total: float = 0.0
        self.latency_ms: int = 0


class Supervisor:
    """Hierarchical supervisor coordinating crews"""

    def __init__(self, crews: dict[str, Crew]):
        """
        Initialize supervisor with crews

        Args:
            crews: Dict mapping crew_id -> Crew instance
        """
        self.crews = crews
        self.event_log = GoalEventLog()
        self.cognitive_router = CognitiveLoadRouter()
        self.crew_router = crew_router
        self.graph = self._build_graph()

    def _build_graph(self):
        """Build LangGraph state machine"""

        # Note: For Phase 1, we're using a simplified async coordination
        # Full LangGraph state management will be refined in Phase 2
        # For now, we manage state directly and use graph for visualization/future
        return None  # Will implement full LangGraph in Phase 2

    async def _node_router(self, state_dict: dict) -> dict[str, Any]:
        """
        Router node: Determine which crews to invoke

        Uses CognitiveLoadRouter to detect depth + CrewRouter to select crews
        """
        user_input = state_dict.get("user_input", "")
        user_id = state_dict.get("user_id", 0)

        log.debug(f"Router: Processing input from user {user_id}")

        # Step 1: Use CognitiveLoadRouter to determine cognitive depth
        routing_decision = self.cognitive_router.route(user_input)
        cognitive_depth = routing_decision.depth

        # Step 2: Use CrewRouter to select crews
        crew_decision = self.crew_router.route(
            user_input=user_input,
            cognitive_depth=cognitive_depth,
            include_vision=self._should_use_vision(user_input),
            include_admin=self._should_use_admin(user_input),
        )

        log.info(
            f"Router decision: depth={cognitive_depth.value}, "
            f"crews={crew_decision.target_crews}, "
            f"cost=${crew_decision.estimated_cost:.3f}"
        )

        return {"decision": crew_decision}

    def _should_use_vision(self, text: str) -> bool:
        """Detect if vision crew is needed"""
        vision_keywords = ["screenshot", "tela", "imagem", "image", "ocr", "read screen", "visual"]
        return any(kw in text.lower() for kw in vision_keywords)

    def _should_use_admin(self, text: str) -> bool:
        """Detect if admin crew is needed"""
        admin_keywords = ["config", "configuração", "optimize", "otimiza", "skill", "criar agent"]
        return any(kw in text.lower() for kw in admin_keywords)

    async def _node_execute_crews(self, state_dict: dict) -> dict[str, Any]:
        """
        Execute node: Invoke selected crews

        Handles parallel execution, error recovery, timeout.
        """
        decision = state_dict.get("decision")
        if not decision:
            return {"crew_results": {}}

        log.info(f"Executing crews: {decision.target_crews}")

        crew_results = {}
        tasks = []

        for crew_id in decision.target_crews:
            if crew_id not in self.crews:
                log.warning(f"Crew '{crew_id}' not found")
                continue

            crew = self.crews[crew_id]

            # Create request
            request = CrewRequest(
                user_input=state_dict.get("user_input", ""),
                cognitive_depth=decision.cognitive_depth,
                memory_context=state_dict.get("memory_context", []),
                user_id=state_dict.get("user_id", 0),
                session_id=state_dict.get("session_id", ""),
                timeout_sec=30.0,
            )

            # Create task
            if decision.parallelizable:
                tasks.append(self._execute_crew(crew_id, crew, request))
            else:
                # Sequential execution
                result = await self._execute_crew(crew_id, crew, request)
                crew_results[crew_id] = result

        # Wait for parallel tasks
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for crew_id, result in zip(decision.target_crews, results):
                if isinstance(result, Exception):
                    log.error(f"Crew '{crew_id}' failed: {result}")
                else:
                    crew_results[crew_id] = result

        return {"crew_results": crew_results}

    async def _execute_crew(
        self, crew_id: str, crew: Crew, request: CrewRequest
    ) -> CrewResult:
        """Execute single crew with error handling and latency tracking"""
        start_time = time.time()

        try:
            log.debug(f"Executing crew: {crew_id}")

            # Log event: crew started
            await self.event_log.append_event(
                goal_id=request.session_id,
                crew_id=crew_id,
                event_type=GoalEventType.STARTED,
                payload={"user_input": request.user_input[:100]},
            )

            # Execute crew with timeout
            try:
                result = await asyncio.wait_for(
                    crew.execute(request), timeout=request.timeout_sec
                )
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Crew '{crew_id}' exceeded timeout of {request.timeout_sec}s"
                )

            # Calculate actual latency
            latency_ms = int((time.time() - start_time) * 1000)
            result.latency_ms = latency_ms

            # Log event: crew completed
            await self.event_log.append_event(
                goal_id=request.session_id,
                crew_id=crew_id,
                event_type=GoalEventType.RESULT_READY,
                payload={
                    "response_preview": result.response[:100],
                    "cost": result.cost_usd,
                    "latency_ms": latency_ms,
                    "confidence": result.confidence,
                },
            )

            log.debug(
                f"Crew '{crew_id}' completed: {latency_ms}ms, cost=${result.cost_usd:.3f}"
            )

            return result

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            log.error(f"Crew '{crew_id}' error after {latency_ms}ms: {e}")

            # Log event: error
            await self.event_log.append_event(
                goal_id=request.session_id,
                crew_id=crew_id,
                event_type=GoalEventType.ERROR,
                payload={"error": str(e), "latency_ms": latency_ms},
            )

            # Return error result
            return CrewResult(
                response=f"Crew '{crew_id}' error: {str(e)}",
                crew_id=crew_id,
                cost_usd=0.0,
                llm_calls=0,
                confidence=0.0,
                latency_ms=latency_ms,
                sources=[],
                should_save_fact=False,
            )

    async def _node_compile_response(self, state_dict: dict) -> dict[str, Any]:
        """
        Compile node: Aggregate crew results into final response

        Intelligently merges crew outputs based on:
        - Response quality
        - Confidence scores
        - Crew priority
        """
        crew_results = state_dict.get("crew_results", {})

        if not crew_results:
            final = "No crews executed or all crews failed."
            total_cost = 0.0
            max_latency = 0
        else:
            # Aggregate responses by crew priority
            final = self._compile_final_response(crew_results)

            # Calculate totals
            total_cost = sum(r.cost_usd for r in crew_results.values())
            max_latency = max(
                (r.latency_ms for r in crew_results.values()), default=0
            )

        log.debug(
            f"Compiled response: cost=${total_cost:.3f}, "
            f"latency={max_latency}ms, crews={len(crew_results)}"
        )

        return {
            "final_response": final,
            "cost_total": total_cost,
            "latency_ms": max_latency,
        }

    def _compile_final_response(self, crew_results: dict[str, CrewResult]) -> str:
        """
        Intelligently merge crew responses

        Prioritizes high-confidence, primary crew results
        """
        if not crew_results:
            return "No results available."

        # Sort by confidence descending
        sorted_crews = sorted(
            crew_results.items(), key=lambda x: x[1].confidence, reverse=True
        )

        # If we have a high-confidence response (>0.8), use it primarily
        if sorted_crews[0][1].confidence > 0.8:
            primary = sorted_crews[0]
            response = f"{primary[1].response}"

            # Add supporting context from other crews if available
            supporting = [
                f"\n[{crew_id}: {result.response[:100]}...]"
                for crew_id, result in sorted_crews[1:]
                if result.confidence > 0.5
            ]

            if supporting:
                response += "\n\n**Supporting analysis:**" + "".join(supporting)

            return response
        else:
            # Low confidence: consolidate all results
            responses = [
                f"**{crew_id}** ({result.confidence:.0%} confidence):\n{result.response}"
                for crew_id, result in sorted_crews
            ]
            return "\n\n---\n\n".join(responses)

    async def process(
        self,
        user_input: str,
        user_id: int,
        session_id: str,
        memory_context: list[str] = None,
    ) -> CrewResult:
        """
        Main entry point: Process user input through supervisor

        Phase 1 Implementation: Direct async coordination (no LangGraph yet)
        Phase 2 will add full LangGraph state management

        Args:
            user_input: User's request
            user_id: Telegram user ID
            session_id: Unique session identifier
            memory_context: Top-k similar facts from memory

        Returns:
            Final CrewResult with aggregated response
        """
        if memory_context is None:
            memory_context = []

        start_time = time.time()
        log.info(f"Supervisor.process: user={user_id}, session={session_id}")

        try:
            # Create initial state
            state = SupervisorState()
            state.user_input = user_input
            state.user_id = user_id
            state.session_id = session_id
            state.memory_context = memory_context

            # Step 1: Router (determine which crews)
            router_result = await self._node_router(self._state_to_dict(state))
            state.decision = router_result.get("decision")
            log.info(f"Router decision: crews={state.decision.target_crews}")

            # Step 2: Execute crews
            executor_result = await self._node_execute_crews(self._state_to_dict(state))
            state.crew_results = executor_result.get("crew_results", {})
            log.info(f"Executed {len(state.crew_results)} crews")

            # Step 3: Compile response
            compiler_result = await self._node_compile_response(
                self._state_to_dict(state)
            )
            state.final_response = compiler_result.get("final_response", "")
            state.cost_total = compiler_result.get("cost_total", 0.0)
            state.latency_ms = compiler_result.get("latency_ms", 0)

            # Calculate total latency
            total_latency_ms = int((time.time() - start_time) * 1000)

            # Return aggregated result
            return CrewResult(
                response=state.final_response,
                crew_id="supervisor",
                cost_usd=state.cost_total,
                llm_calls=sum(r.llm_calls for r in state.crew_results.values()),
                confidence=self._calculate_confidence(state.crew_results),
                latency_ms=total_latency_ms,
                sources=self._aggregate_sources(state.crew_results),
                should_save_fact=False,
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            log.error(f"Supervisor error after {latency_ms}ms: {e}")
            return CrewResult(
                response=f"Supervisor error: {str(e)}",
                crew_id="supervisor",
                cost_usd=0.0,
                llm_calls=0,
                confidence=0.0,
                latency_ms=latency_ms,
                sources=[],
            )

    def _state_to_dict(self, state: SupervisorState) -> dict:
        """Convert SupervisorState to dict for node processing"""
        return {
            "user_input": state.user_input,
            "user_id": state.user_id,
            "session_id": state.session_id,
            "cognitive_depth": state.cognitive_depth,
            "memory_context": state.memory_context,
            "decision": state.decision,
            "crew_results": state.crew_results,
            "final_response": state.final_response,
            "cost_total": state.cost_total,
            "latency_ms": state.latency_ms,
        }

    def _calculate_confidence(self, crew_results: dict[str, CrewResult]) -> float:
        """Calculate overall confidence from crew results"""
        if not crew_results:
            return 0.0
        return sum(r.confidence for r in crew_results.values()) / len(crew_results)

    def _aggregate_sources(self, crew_results: dict[str, CrewResult]) -> list[str]:
        """Aggregate sources from all crews"""
        sources = []
        for result in crew_results.values():
            sources.extend(result.sources)
        return list(set(sources))  # Remove duplicates
