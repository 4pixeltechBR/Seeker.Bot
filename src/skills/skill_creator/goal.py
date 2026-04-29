import logging
import asyncio
from datetime import datetime

from src.core.pipeline import SeekerPipeline
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel
)
from src.providers.base import LLMRequest, invoke_with_fallback
from config.models import CognitiveRole
from src.core.utils import parse_llm_json
from src.skills.skill_creator.coder import CodeGenerator

log = logging.getLogger("seeker.skill_creator")

class AutoSkillCreatorGoal(AutonomousGoal):
    """
    Rastreia intenções repetitivas no chat (ex: "me lembre do flamengo") 
    e auto-gera skills quando detecta frequência >= 4x na semana.
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.05, max_daily_usd=0.10)
        # CodeGenerator (SkillCreatorEngine) usa apenas @staticmethod — não instanciar com args
        
    @property
    def name(self) -> str:
        return "skill_creator"

    @property
    def interval_seconds(self) -> int:
        return 43200  # A cada 12 horas

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    def serialize_state(self) -> dict:
        return {}  # Sem estado persistível neste goal

    def load_state(self, state: dict) -> None:
        pass  # Sem estado para restaurar

    async def run_cycle(self) -> GoalResult:
        self._status = GoalStatus.RUNNING
        cycle_cost = 0.0

        try:
            # Pega as ultimas mensagens do usuario do banco (via memory.get_session_turns)
            # Para simplificar, iteramos pelas sessões ativas
            all_user_messages = []
            
            # memory_store sqlite
            if hasattr(self.pipeline.memory, "get_session_turns"):
                # "telegram" é o id da sessão principal
                turns = await self.pipeline.memory.get_session_turns("telegram", limit=100)
                all_user_messages = [t["content"] for t in turns if t["role"] == "user"]
                
            if len(all_user_messages) < 10:
                self._status = GoalStatus.IDLE
                return GoalResult(success=True, summary="Contexto insuficiente para analisar intents.", cost_usd=0.0)

            # Analisa as mensagens buscando repeticao
            messages_text = "\n".join([f"- {m}" for m in all_user_messages[-50:]])
            
            prompt = (
                "Você é o módulo de percepção do Seeker.Bot. O usuário enviou estas mensagens nos últimos dias.\n"
                "Sua tarefa é encontrar algum PADRÃO ou INTENÇÃO REPETIDA que o usuário tenha pedido explícita ou implicitamente mais de 3 vezes.\n"
                "Exemplos de padrões: 'perguntar sobre jogos do flamengo', 'pedir para resumir pdf', 'perguntar cotação do dolar'.\n\n"
                "Regra: Retorne JSON válido ESTRITAMENTE neste formato:\n"
                "{\n"
                '  "pattern_found": true ou false,\n'
                '  "pattern_description": "Descreva o padrao encontrado de forma clara",\n'
                '  "occurrences": número inteiro estimado de vezes que o usuário pediu isso,\n'
                '  "skill_proposal": "Uma descrição técnica de 2 linhas de como uma Skill Python resolveria isso rodando autonomamente."\n'
                "}\n\n"
                f"MENSAGENS DO USUÁRIO:\n{messages_text}"
            )

            resp = await invoke_with_fallback(
                CognitiveRole.FAST,
                LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    system="Responda apenas com JSON sem blocos markdown.",
                    temperature=0.0,
                ),
                self.pipeline.model_router,
                self.pipeline.api_keys,
            )
            cycle_cost += resp.cost_usd
            
            data = parse_llm_json(resp.text)
            
            if data.get("pattern_found") and data.get("occurrences", 0) >= 4:
                # Gerar a proposta de skill
                desc = data.get("pattern_description")
                prop = data.get("skill_proposal")
                
                notification = (
                    f"🧠 **EUREKA! Padrão Detectado**\n\n"
                    f"Eu notei que você me pediu sobre `{desc}` aproximadamente {data.get('occurrences')} vezes recentemente.\n\n"
                    f"**Proposta de Automação:**\n{prop}\n\n"
                    f"Deseja que eu escreva o código dessa Skill e instale no meu núcleo agora? (Responda no chat)"
                )
                
                self._status = GoalStatus.IDLE
                return GoalResult(
                    success=True,
                    summary=f"Padrão detectado: {desc}",
                    notification=notification,
                    cost_usd=cycle_cost,
                    data={"intent": desc}
                )

            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Nenhum padrão latente forte encontrado.", cost_usd=cycle_cost)

        except Exception as e:
            log.error(f"[skill_creator] Erro no loop de auto-creation: {e}", exc_info=True)
            self._status = GoalStatus.IDLE
            return GoalResult(success=False, summary=f"Erro de tracker: {e}", cost_usd=cycle_cost)

def create_goal(pipeline) -> AutonomousGoal:
    return AutoSkillCreatorGoal(pipeline)
