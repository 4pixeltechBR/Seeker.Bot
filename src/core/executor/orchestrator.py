"""ActionOrchestrator — LLM-based Planning for Remote Executor (Track B3)"""
import logging
import json
from src.core.executor.models import ExecutionPlan, ActionStep, ActionType, ApprovalTier

log = logging.getLogger("executor.orchestrator")

class ActionOrchestrator:
    """Orquestra intenção do usuário em plano de execução estruturado via LLM"""

    def __init__(self, cascade_adapter):
        self.cascade = cascade_adapter

    async def plan_actions(self, user_intention: str, context: dict = None) -> ExecutionPlan:
        """
        Converte intenção em plano estruturado de execução.

        Args:
            user_intention: O que o usuário quer fazer
            context: Contexto adicional (projeto, arquivos, etc)

        Returns:
            ExecutionPlan com steps sequenciais
        """
        prompt = self._build_planning_prompt(user_intention, context)

        try:
            response = await self.cascade.call(
                role="STRATEGIC",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=800,
            )

            plan = self._parse_plan(response.get("content", "{}"), user_intention)
            log.info(f"[orchestrator] Plano criado: {len(plan.steps)} steps, cost=${plan.estimated_total_cost_usd:.2f}")
            return plan

        except Exception as e:
            log.error(f"[orchestrator] Planning error: {e}")
            raise

    def _build_planning_prompt(self, intention: str, context: dict = None) -> str:
        ctx_str = ""
        if context:
            ctx_str = f"\nCONTEXTO: {json.dumps(context, indent=2)}"

        return f"""Você é um especialista em planejamento de execução autônoma.
Converta a intenção do usuário em plano estruturado de ações.

INTENÇÃO: {intention}{ctx_str}

Retorne APENAS um JSON válido com estrutura:
{{
  "plan_id": "uuid",
  "steps": [
    {{"id": "step_1", "type": "bash", "command": "git add .", "timeout": 30, "approval_tier": "l1_logged", "cost": 0.0}},
    {{"id": "step_2", "type": "bash", "command": "git commit -m '...'", "timeout": 15, "approval_tier": "l1_logged", "cost": 0.01, "depends_on": ["step_1"]}}
  ],
  "estimated_cost": 0.01,
  "estimated_timeout": 60,
  "safety_notes": "..."
}}"""

    def _parse_plan(self, response_text: str, intention: str) -> ExecutionPlan:
        """Parse resposta LLM em ExecutionPlan"""
        try:
            s = response_text.find("{")
            e = response_text.rfind("}") + 1
            if s == -1 or e <= s:
                raise ValueError("No JSON in response")

            data = json.loads(response_text[s:e])

            steps = []
            for step_data in data.get("steps", []):
                step = ActionStep(
                    id=step_data.get("id", ""),
                    type=ActionType(step_data.get("type", "bash")),
                    command=step_data.get("command", ""),
                    timeout_seconds=int(step_data.get("timeout", 30)),
                    approval_tier=ApprovalTier(step_data.get("approval_tier", "l1_logged")),
                    estimated_cost_usd=float(step_data.get("cost", 0.0)),
                    depends_on=step_data.get("depends_on", []),
                    description=step_data.get("description"),
                )
                steps.append(step)

            return ExecutionPlan(
                plan_id=data.get("plan_id", "unknown"),
                steps=steps,
                estimated_total_cost_usd=float(data.get("estimated_cost", 0.0)),
                estimated_total_timeout_seconds=int(data.get("estimated_timeout", 300)),
                safety_notes=data.get("safety_notes", ""),
                highest_approval_tier=self._compute_highest_tier(steps),
                user_intention=intention,
            )

        except Exception as e:
            log.warning(f"[orchestrator] Parse error: {e}")
            raise

    def _compute_highest_tier(self, steps: list) -> ApprovalTier:
        """Computa approval tier máximo entre todos os steps"""
        tiers = [s.approval_tier for s in steps]
        if ApprovalTier.L0_MANUAL in tiers:
            return ApprovalTier.L0_MANUAL
        if ApprovalTier.L1_LOGGED in tiers:
            return ApprovalTier.L1_LOGGED
        return ApprovalTier.L2_SILENT
