from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config.models import CognitiveRole
from src.providers.base import LLMRequest, invoke_with_fallback
from src.skills.ruflo_swarm import store as swarm_store
from src.skills.ruflo_swarm.policy import ArmConfig, BanditPolicy
from src.skills.ruflo_swarm.prompts import SWARM_FACTORY_PROMPT

log = logging.getLogger("seeker.ruflo_swarm.swarm")


@dataclass(frozen=True)
class SwarmTask:
    id: str
    goal: str
    role: CognitiveRole = CognitiveRole.FAST
    max_turns: int = 3
    context: dict = field(default_factory=dict)


@dataclass
class SwarmResult:
    task_id: str
    success: bool
    summary: str
    cost_usd: float
    turns: int
    tool_calls: list[str]
    duration_s: float
    artifacts: dict = field(default_factory=dict)


class SwarmRunner:
    def __init__(self, pipeline, max_agents: int = 12):
        self.pipeline = pipeline
        self.max_agents = max_agents
        self._semaphore = asyncio.Semaphore(max_agents)

    async def dispatch(
        self,
        tasks: list[SwarmTask],
        semaphore: int = 5,
        learn: bool = True,
        policy: BanditPolicy | None = None,
        persist: bool = True,
    ) -> list[SwarmResult]:
        if not tasks:
            return []
        effective_sem = asyncio.Semaphore(min(semaphore, self.max_agents))
        log.info(f"[swarm] Dispatching {len(tasks)} tasks (semaphore={semaphore}, learn={learn})")

        async def _run_one(task: SwarmTask) -> SwarmResult:
            async with effective_sem:
                arm = ArmConfig(role=task.role, max_turns=task.max_turns, temperature=0.15)
                return await self._execute(task, arm)

        results = await asyncio.gather(*[_run_one(t) for t in tasks])

        if learn and policy:
            arm = ArmConfig(role=tasks[0].role, max_turns=tasks[0].max_turns, temperature=0.15)
            success_rate = sum(1 for r in results if r.success) / len(results) if results else 0
            avg_cost = sum(r.cost_usd for r in results) / len(results) if results else 0
            avg_duration = sum(r.duration_s for r in results) / len(results) if results else 0
            reward = success_rate * 0.5 + min(1.0, 10.0 / max(avg_duration, 0.1)) * 0.3 - avg_cost * 0.2
            policy.update(arm, reward)

        if persist:
            self._persist_results(tasks, results)

        return results

    def _persist_results(self, tasks: list[SwarmTask], results: list[SwarmResult]) -> None:
        """Persiste resultados no store para histórico e contadores."""
        try:
            state = swarm_store.load_state()
            now_iso = datetime.now(timezone.utc).isoformat()

            history = state.setdefault("task_history", {})
            recent = state.setdefault("recent_jobs", [])

            for task, result in zip(tasks, results):
                entry = {
                    "task_id": task.id,
                    "query": task.goal[:120],
                    "role": task.role.value if hasattr(task.role, "value") else str(task.role),
                    "max_turns": task.max_turns,
                    "status": "done" if result.success else "failed",
                    "cost_usd": round(result.cost_usd, 6),
                    "duration_s": round(result.duration_s, 3),
                    "turns": result.turns,
                    "tool_calls": len(result.tool_calls),
                    "summary_excerpt": (result.summary or "")[:200],
                    "ts": now_iso,
                }
                history[task.id] = entry
                recent.append(entry)

            # Cap recent em 50 (FIFO)
            state["recent_jobs"] = recent[-50:]

            # Contadores
            state["total_dispatched"] = state.get("total_dispatched", 0) + len(results)
            state["active_agents"] = 0  # não temos tracking ao vivo; reset ao final

            swarm_store.save_state(state)
        except Exception as e:
            log.warning(f"[swarm] Falha ao persistir resultados: {e}")

    async def _execute(self, task: SwarmTask, arm: ArmConfig) -> SwarmResult:
        start = time.monotonic()
        log.info(f"[swarm] task={task.id} role={arm.role.value} turns={task.max_turns} goal={task.goal!r}")

        messages: list[dict] = [{"role": "user", "content": f"Por favor, execute: {task.goal}"}]
        system = SWARM_FACTORY_PROMPT.format(goal=task.goal)
        tool_calls: list[str] = []
        turn = 0
        response_text = ""

        while turn < task.max_turns:
            req = LLMRequest(
                messages=messages,
                system=system,
                temperature=arm.temperature,
                max_tokens=2048,
            )
            try:
                resp = await invoke_with_fallback(
                    role=arm.role,
                    request=req,
                    router=self.pipeline.model_router,
                    api_keys=self.pipeline.api_keys,
                )
            except Exception as e:
                log.warning(f"[swarm] task={task.id} turn={turn} falhou: {e}")
                elapsed = time.monotonic() - start
                return SwarmResult(
                    task_id=task.id, success=False, summary=str(e), cost_usd=0.0,
                    turns=turn, tool_calls=tool_calls, duration_s=elapsed,
                )

            response_text = resp.text.strip()
            cost = getattr(resp, "cost_usd", 0.0) or 0.0
            messages.append({"role": "assistant", "content": response_text})

            had_tool = False
            tool_output = ""

            if "[SEARCH_REQUIRED:" in response_text:
                s = response_text.find("[SEARCH_REQUIRED:") + len("[SEARCH_REQUIRED:")
                e = response_text.find("]", s)
                if e != -1:
                    query = response_text[s:e].strip().strip('"').strip("'")
                    had_tool = True
                    tool_calls.append(f"search:{query}")
                    try:
                        results = await self.pipeline.searcher.search(query, max_results=2)
                        tool_output = f"\n\n[RETORNO DA BUSCA]\n{results.to_context(max_results=2)}"
                    except Exception as ex:
                        tool_output = f"\n\n[ERRO BUSCA]\n{ex}"

            elif "[READ_FILE:" in response_text:
                s = response_text.find("[READ_FILE:") + len("[READ_FILE:")
                e = response_text.find("]", s)
                if e != -1:
                    path = response_text[s:e].strip().strip('"').strip("'")
                    had_tool = True
                    tool_calls.append(f"read:{path}")
                    try:
                        from src.core.execution.registry import execute_read_file
                        content = await execute_read_file(path)
                        tool_output = f"\n\n[CONTEÚDO DO ARQUIVO {path}]\n{content}"
                    except Exception as ex:
                        tool_output = f"\n\n[ERRO AO LER {path}]\n{ex}"

            if had_tool:
                messages.append({
                    "role": "user",
                    "content": f"Resultado da ferramenta:{tool_output}\n\nAnalise e prossiga.",
                })
                turn += 1
                continue
            break

        elapsed = time.monotonic() - start
        return SwarmResult(
            task_id=task.id, success=True, summary=response_text, cost_usd=cost,
            turns=turn + 1, tool_calls=tool_calls, duration_s=elapsed,
        )
