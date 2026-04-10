"""
ActionOrchestrator — LLM-based action planning.

Responsabilidades:
- Converter intenção do usuário em ExecutionPlan multi-step
- Usar CascadeAdapter para planning (STRATEGIC role)
- Validar plano contra constraints (max steps, timeout, cost)
- Estruturar steps com dependências, rollback, e estimativas de custo
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

from .models import (
    ActionType,
    AutonomyTier,
    ActionStep,
    ExecutionPlan,
    ExecutionContext,
    SafetyGate,
)

logger = logging.getLogger("seeker.executor.orchestrator")


class ActionOrchestrator:
    """
    Planeja ações multi-step via LLM.

    Fluxo:
    1. Recebe intenção do usuário (string)
    2. Chama LLM via CascadeAdapter (role=PLANNING)
    3. Parseia resposta → ExecutionPlan
    4. Valida contra constraints
    5. Retorna plano aprovado ou erro
    """

    def __init__(self, cascade_adapter=None, timeout_sec: int = 30):
        """
        Inicializa orchestrator.

        Args:
            cascade_adapter: CascadeAdapter para chamar LLM (planning role)
            timeout_sec: Timeout para chamada LLM
        """
        self.cascade_adapter = cascade_adapter
        self.timeout_sec = timeout_sec

        # Constraints
        self.max_steps = 10
        self.max_total_timeout_sec = 60
        self.max_cost_usd = 0.20

    async def plan(
        self,
        intention: str,
        context: ExecutionContext,
    ) -> Tuple[Optional[ExecutionPlan], str]:
        """
        Gera plano de execução para intenção.

        Args:
            intention: Intenção em linguagem natural (ex: "fazer commit do código")
            context: ExecutionContext com budget, AFK status, etc.

        Returns:
            (ExecutionPlan, error_message)
            - Se sucesso: (plan, "")
            - Se erro: (None, "motivo")
        """
        logger.info(f"[orchestrator] Planning: {intention[:80]}")

        try:
            # 1. Build system prompt (português)
            system_prompt = self._build_system_prompt()

            # 2. Build user prompt
            user_prompt = self._build_user_prompt(intention, context)

            # 3. Call LLM via cascade (planning role)
            try:
                llm_response = await asyncio.wait_for(
                    self._call_llm_planning(system_prompt, user_prompt),
                    timeout=self.timeout_sec,
                )
            except asyncio.TimeoutError:
                logger.error("[orchestrator] LLM timeout, fallback to simple plan")
                # Fallback: criar plano simples (1 bash step)
                llm_response = self._fallback_simple_plan(intention)

            # 4. Parse resposta JSON
            try:
                plan_dict = json.loads(llm_response)
            except json.JSONDecodeError as e:
                logger.error(f"[orchestrator] JSON parse failed: {e}")
                return None, f"Resposta LLM inválida: {str(e)}"

            # 5. Construir ExecutionPlan a partir de dict
            plan = self._build_execution_plan(
                plan_dict=plan_dict,
                intention=intention,
                context=context,
            )

            # 6. Validar contra constraints
            is_valid, error = await self._validate_plan(plan, context)
            if not is_valid:
                logger.warning(f"[orchestrator] Plan validation failed: {error}")
                return None, f"Plano inválido: {error}"

            logger.info(
                f"[orchestrator] Plan created: {len(plan.steps)} steps, "
                f"cost=${plan.estimated_total_cost_usd:.2f}"
            )
            return plan, ""

        except Exception as e:
            logger.error(f"[orchestrator] Planning failed: {e}", exc_info=True)
            return None, f"Erro ao gerar plano: {str(e)}"

    def _build_system_prompt(self) -> str:
        """Constrói system prompt para planning."""
        return """Você é um assistente de planejamento de ações para Seeker.Bot.

Sua tarefa é quebrar intenções do usuário em passos executáveis.

REGRAS:
1. Cada passo deve ser uma ação atômica (bash, file_ops, api, ou remote_trigger)
2. Máximo 10 passos por plano
3. Máximo 60 segundos de timeout total
4. Máximo $0.20 de custo estimado
5. Especifique dependências se um passo depender de outro
6. Inclua rollback_instruction se a ação for reversível (ex: rm → restore backup)
7. Classifique cada passo em tier de autonomia:
   - L2_SILENT: ações seguras que podem executar anytime (ls, cat, echo)
   - L1_LOGGED: ações médias que auto-executam com log até 12h AFK (mkdir, touch, api GET)
   - L0_MANUAL: ações perigosas que requerem aprovação (rm, chmod, desktop_click)

FORMATO ESPERADO (JSON):
{
  "steps": [
    {
      "id": "step_1",
      "type": "bash",  // bash, file_ops, api, remote_trigger
      "description": "descrição clara do que faz",
      "command": "bash command ou dict conforme tipo",
      "timeout_seconds": 30,
      "approval_tier": "L2_SILENT",  // L0_MANUAL, L1_LOGGED, or L2_SILENT
      "estimated_cost_usd": 0.0,
      "depends_on": [],  // [] ou ["step_0"] se depender
      "rollback_instruction": null ou "como desfazer"
    }
  ],
  "estimated_total_cost_usd": 0.0,
  "safety_notes": "observações sobre segurança"
}

EXEMPLOS BONS:
- Fazer commit: [git add, git commit] (2 steps, L1)
- Buscar e resumir: [curl, extract_text] (2 steps, L1)
- Deletar arquivo com rollback: [cp para backup, rm original] (2 steps, L0)

EXEMPLOS RUINS:
- "restart system" → perigoso, não é L0
- 15 passos → excede limite
- Passo sem descrição → inválido
"""

    def _build_user_prompt(self, intention: str, context: ExecutionContext) -> str:
        """Constrói user prompt customizado."""
        afk_status = "ONLINE" if context.afk_time_seconds < 300 else "AFK"
        return f"""Planeje a execução para esta intenção:

INTENÇÃO: {intention}

CONTEXTO:
- Budget restante: ${context.budget_remaining_usd:.2f}
- Status do usuário: {afk_status} ({context.afk_time_seconds}s sem atividade)
- AFK window L1: {context.afk_window_l1_hours} horas
- Goal: {context.goal_name}

Gere o plano em JSON puro (sem markdown, sem explicação).
"""

    async def _call_llm_planning(
        self, system_prompt: str, user_prompt: str
    ) -> str:
        """Chama LLM via CascadeAdapter."""
        if not self.cascade_adapter:
            logger.warning("[orchestrator] No cascade adapter, using fallback")
            return json.dumps({"steps": [], "estimated_total_cost_usd": 0.0})

        # Formata para chamada cascade
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            # Usa PLANNING role do cascade
            response = await self.cascade_adapter.call(
                role="planning",
                messages=messages,
            )
            return response.get("content", "")
        except Exception as e:
            logger.error(f"[orchestrator] Cascade call failed: {e}")
            return json.dumps({"steps": [], "estimated_total_cost_usd": 0.0})

    def _fallback_simple_plan(self, intention: str) -> str:
        """Fallback simples se LLM falhar."""
        # Tenta extrair um comando bash simples
        return json.dumps(
            {
                "steps": [
                    {
                        "id": "step_1",
                        "type": "bash",
                        "description": intention,
                        "command": "echo 'Fallback: não consegui planejar'",
                        "timeout_seconds": 10,
                        "approval_tier": "L2_SILENT",
                        "estimated_cost_usd": 0.0,
                        "depends_on": [],
                        "rollback_instruction": None,
                    }
                ],
                "estimated_total_cost_usd": 0.0,
                "safety_notes": "Fallback plan due to LLM timeout",
            }
        )

    def _build_execution_plan(
        self,
        plan_dict: Dict,
        intention: str,
        context: ExecutionContext,
    ) -> ExecutionPlan:
        """Constrói ExecutionPlan a partir de dict do LLM."""
        import uuid

        plan_id = f"plan_{uuid.uuid4().hex[:8]}"

        # Parse steps
        steps = []
        dependencies = {}
        total_cost = 0.0

        for step_dict in plan_dict.get("steps", []):
            step = ActionStep(
                id=step_dict.get("id", f"step_{len(steps)}"),
                type=ActionType(step_dict.get("type", "bash")),
                description=step_dict.get("description", ""),
                command=step_dict.get("command", ""),
                timeout_seconds=step_dict.get("timeout_seconds", 30),
                approval_tier=AutonomyTier(
                    step_dict.get("approval_tier", "L2_SILENT")
                ),
                estimated_cost_usd=step_dict.get("estimated_cost_usd", 0.0),
                depends_on=step_dict.get("depends_on", []),
                rollback_instruction=step_dict.get("rollback_instruction"),
            )
            steps.append(step)
            dependencies[step.id] = step.depends_on
            total_cost += step.estimated_cost_usd

        plan = ExecutionPlan(
            plan_id=plan_id,
            intention=intention,
            steps=steps,
            dependencies=dependencies,
            estimated_total_cost_usd=plan_dict.get("estimated_total_cost_usd", total_cost),
            safety_notes=plan_dict.get("safety_notes", ""),
            max_steps=self.max_steps,
            max_timeout_seconds=self.max_total_timeout_sec,
            max_cost_usd=self.max_cost_usd,
        )

        return plan

    async def _validate_plan(
        self, plan: ExecutionPlan, context: ExecutionContext
    ) -> Tuple[bool, str]:
        """Valida plano contra constraints."""
        # Número de steps
        if len(plan.steps) > self.max_steps:
            return False, f"Plano tem {len(plan.steps)} steps, máximo {self.max_steps}"

        # Custo total
        if plan.estimated_total_cost_usd > self.max_cost_usd:
            return False, (
                f"Custo ${plan.estimated_total_cost_usd:.2f} exceeds cap "
                f"${self.max_cost_usd:.2f}"
            )

        # Budget disponível
        if plan.estimated_total_cost_usd > context.budget_remaining_usd:
            return False, (
                f"Custo ${plan.estimated_total_cost_usd:.2f} exceeds budget "
                f"${context.budget_remaining_usd:.2f}"
            )

        # Timeout total
        total_timeout = sum(step.timeout_seconds for step in plan.steps)
        if total_timeout > self.max_total_timeout_sec:
            return False, (
                f"Timeout total {total_timeout}s exceeds max "
                f"{self.max_total_timeout_sec}s"
            )

        # Validação de dependências (DAG, sem ciclos)
        if not self._is_valid_dag(plan.dependencies):
            return False, "Dependências contêm ciclos"

        return True, ""

    def _is_valid_dag(self, dependencies: Dict[str, List[str]]) -> bool:
        """Verifica se grafo de dependências é acíclico (DAG)."""
        # Simples DFS para detecção de ciclos
        visited = set()
        rec_stack = set()

        def has_cycle(node):
            visited.add(node)
            rec_stack.add(node)

            for dep in dependencies.get(node, []):
                if dep not in visited:
                    if has_cycle(dep):
                        return True
                elif dep in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for node in dependencies:
            if node not in visited:
                if has_cycle(node):
                    return False

        return True
