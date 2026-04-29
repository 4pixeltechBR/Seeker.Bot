"""
Cortex Consolidator Goal
src/skills/cortex/goal.py

Roda 1x/dia às 04:00h.
- Lê insights do staging (insights.jsonl)
- Lê notas recentes do Obsidian Vault
- Puxa triplas e fatos do banco
- Sintetiza tudo em um Markdown curado de alto nível
- Envia relatório diário no Telegram
"""
import os
import json
import logging
from datetime import datetime
from src.core.goals.protocol import GoalResult, GoalStatus, NotificationChannel, GoalBudget
from src.skills.knowledge_vault.vault_searcher import VaultSearcher

log = logging.getLogger("seeker.cortex.consolidator")

CORTEX_PROMPT_SYSTEM = """Você é a Mente Analítica de Consolidação de Memória de um agente autônomo de IA.
Sua tarefa é analisar logs brutos de interações, novos conhecimentos adquiridos e notas feitas pelo usuário, e condensá-los em um Markdown Ultra-Curado de longo prazo.

REGRAS DO MARKDOWN CURADO:
1. Deve ser ultra-denso e direto. Sem filler, sem introduções.
2. Limite máximo de tamanho: 4000 caracteres (~1000 tokens). O que for irrelevante ou velho demais, descarte.
3. Regras de comportamento (Reflexive Rules) definidas pelo usuário são IMORTAIS. Elas NUNCA devem ser descartadas.
4. Mantenha seções fixas como:
   - ## Regras Comportamentais Críticas (Imortais)
   - ## Decisões Técnicas e Projetos
   - ## Padrões e Hábitos do Usuário
   - ## Digest do Vault (Resumo de novas notas)

Se já existir um conhecimento curado anterior, você receberá ele e deverá ATUALIZÁ-LO (manter o que importa, adicionar o novo, remover o obsoleto).
"""

CORTEX_PROMPT_USER = """Por favor, consolide o conhecimento.

CONHECIMENTO CURADO ATUAL (Base anterior para você atualizar):
{current_curated}

NOVOS INSIGHTS BRUTOS (Últimas 24h):
{insights_json}

NOVAS NOTAS NO VAULT (Resumo do que o usuário escreveu):
{vault_notes}

Gere o NOVO arquivo Markdown curado. Apenas o Markdown, nada de "Aqui está o arquivo".
"""

class CortexConsolidatorGoal:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.searcher = VaultSearcher()
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.01, max_daily_usd=0.05)
        
        self.target_hour = 4
        self.target_minute = 0
        self._last_run_date = ""

    @property
    def name(self) -> str:
        return "cortex_consolidator"

    @property
    def interval_seconds(self) -> int:
        return 3600 # Checa a cada hora

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    def serialize_state(self) -> dict:
        return {"last_run_date": self._last_run_date}

    def load_state(self, state: dict) -> None:
        self._last_run_date = state.get("last_run_date", "")

    async def run_cycle(self) -> GoalResult:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        
        # Verifica se já rodou hoje
        if self._last_run_date == today_str:
            return GoalResult(success=True, summary="Consolidação já foi gerada hoje")

        if now.hour < self.target_hour or (now.hour == self.target_hour and now.minute < self.target_minute):
            return GoalResult(success=True, summary="Aguardando 04:00h")

        self._status = GoalStatus.RUNNING
        
        try:
            manager = self.pipeline.cortex_manager
            
            # 1. Coleta Insights do Cortex (Staging)
            insights = manager.get_staging_insights()
            insights_json = json.dumps(insights, ensure_ascii=False, indent=2) if insights else "Nenhum insight novo."
            
            # 2. Coleta Notas do Vault
            recent_notes = self.searcher.list_recent(days=1)
            vault_summary = "\n".join([f"- {n.title} ({', '.join(n.tags)})" for n in recent_notes]) if recent_notes else "Nenhuma nota nova no Vault."

            # Se não houver absolutamente nada de novo, não gasta token
            if not insights and not recent_notes:
                self._last_run_date = today_str
                self._status = GoalStatus.IDLE
                return GoalResult(success=True, summary="Nada novo para consolidar hoje.")

            # 3. Lê o Markdown atual
            current_curated = manager.get_curated_knowledge(cached=False) or "Nenhum conhecimento curado anterior."

            # 4. Envia para o LLM
            prompt_user = CORTEX_PROMPT_USER.format(
                current_curated=current_curated,
                insights_json=insights_json,
                vault_notes=vault_summary
            )
            
            # Usa cascade_adapter.call com mensagens estruturadas
            response = await self.pipeline.cascade_adapter.call(
                role="extraction",
                messages=[
                    {"role": "system", "content": CORTEX_PROMPT_SYSTEM},
                    {"role": "user", "content": prompt_user}
                ],
                max_tokens=2048,
                temperature=0.1
            )
            
            curated_text = response.get("content", "").strip() if response and response.get("content") else ""
            
            # Remove crase markdown se o LLM devolver dentro de bloco code
            if curated_text.startswith("```markdown"):
                curated_text = curated_text[11:]
            if curated_text.startswith("```"):
                curated_text = curated_text[3:]
            if curated_text.endswith("```"):
                curated_text = curated_text[:-3]
                
            curated_text = curated_text.strip()
            
            # 5. Salva Curated e Limpa Staging
            manager.write_curated_knowledge(curated_text)
            manager.clear_staging()
            
            self._last_run_date = today_str
            self._status = GoalStatus.IDLE
            
            # 6. Notificação amigável para o Telegram
            insight_count = len(insights)
            note_count = len(recent_notes)
            
            notification = (
                f"🧠 **Cortex: Relatório Diário de Consolidação**\n\n"
                f"Foram absorvidos **{insight_count} insights** autônomos e **{note_count} novas notas** do Vault.\n\n"
                f"A memória cristalizada foi atualizada (agora com {len(curated_text)} caracteres). "
                f"Este contexto será ativamente carregado nas próximas interações."
            )
            
            return GoalResult(
                success=True,
                summary=f"Cortex consolidou {insight_count} insights e {note_count} notas.",
                notification=notification,
                cost_usd=0.002 # Estimativa
            )
            
        except Exception as e:
            self._status = GoalStatus.IDLE
            log.error(f"[cortex] Erro ao consolidar: {e}", exc_info=True)
            return GoalResult(success=False, summary=f"Erro no cortex consolidator: {e}")

def create_goal(pipeline):
    return CortexConsolidatorGoal(pipeline)
