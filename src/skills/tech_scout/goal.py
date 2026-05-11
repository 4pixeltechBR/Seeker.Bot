import logging
import os
import json
import datetime
from typing import Any

from src.core.pipeline import SeekerPipeline
from src.providers.base import LLMRequest, invoke_with_fallback
from src.core.goals.protocol import (
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)
from config.models import CognitiveRole

log = logging.getLogger("seeker.tech_scout")

TECH_CATEGORIES = {
    "vision": ["ComfyUI", "Flux AI", "HunyuanVideo", "Stable Diffusion"],
    "llm": ["DeepSeek API", "Groq API", "NVIDIA NIM", "Anthropic Claude"],
    "audio": ["F5-TTS", "ChatTTS", "ElevenLabs", "Suno Bark"],
    "core": ["Python 3.12/3.13", "FastAPI", "Pydantic v2", "aiogram 3.x", "Tavily API"]
}

CATEGORY_NAMES = {
    "vision": "👁️ Visão & Geração de Vídeo",
    "llm": "🧠 Modelos de Linguagem",
    "audio": "🎙️ Áudio & TTS",
    "core": "⚙️ Core & Infraestrutura"
}

class TechScoutGoal:
    """
    Goal autônomo que monitora lançamentos e atualizações de ferramentas no stack do Seeker.
    Analisa se as novidades trazem benefício real e sugere upgrades.
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.30, max_daily_usd=1.5)
        self.last_scout_date = ""
        self.active_categories = list(TECH_CATEGORIES.keys())
        self.history_file = os.path.join(os.getcwd(), "data", "tech_scout_history.json")
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)

    @property
    def name(self) -> str:
        return "tech_scout"

    @property
    def interval_seconds(self) -> int:
        # A cada 48 horas (172800 segundos)
        return 172800

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    async def run_cycle(self) -> GoalResult:
        self._status = GoalStatus.RUNNING
        cycle_cost = 0.0
        
        log.info("[tech_scout] Iniciando ciclo de monitoramento de stack...")
        
        # 1. Carrega histórico para evitar duplicidade
        history = self._load_history()
        
        # 2. Realiza pesquisas para o stack ativo
        search_results = []
        stack_to_search = []
        for cat in self.active_categories:
            if cat in TECH_CATEGORIES:
                stack_to_search.extend(TECH_CATEGORIES[cat])

        if not stack_to_search:
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Nenhuma categoria ativa no Tech Scout.", cost_usd=0.0)

        for tech in stack_to_search:
            query = f"{tech} latest releases news {datetime.date.today().year}"
            try:
                resp = await self.pipeline.searcher.search(query, max_results=3)
                if resp.results:
                    search_results.append({
                        "tech": tech,
                        "results": [r.to_context() for r in resp.results]
                    })
            except Exception as e:
                log.warning(f"[tech_scout] Falha ao pesquisar {tech}: {e}")

        # 3. Coleta dados de custo reais para comparação (Sprint 11)
        cost_summary = "Dados de custo indisponíveis"
        if hasattr(self.pipeline, "cost_tracker"):
            resumo_hoje = self.pipeline.cost_tracker.obter_resumo_diario()
            resumo_mes = self.pipeline.cost_tracker.obter_resumo_mensal()
            cost_summary = (
                f"Gasto Hoje: ${resumo_hoje['custo_total']:.2f} (Limite: ${resumo_hoje['limite']:.2f})\n"
                f"Gasto Mês: ${resumo_mes['custo_total']:.2f} (Limite: ${resumo_mes['limite']:.2f})\n"
                f"Provedores ativos hoje: {resumo_hoje['provedores']}"
            )

        # 4. Análise de benefício via LLM
        context_str = json.dumps(search_results, indent=2)
        history_str = json.dumps(list(history.keys()), indent=2)
        
        prompt = (
            "Você é o Seeker Tech Scout, um analista de infraestrutura IA sênior.\n"
            "Sua missão é analisar as notícias de lançamentos abaixo e identificar se há benefícios REAIS para o Seeker.Bot.\n\n"
            f"=== CUSTOS ATUAIS DO SISTEMA ===\n{cost_summary}\n\n"
            f"=== TECH STACK ATUAL ===\n{stack_to_search}\n\n"
            f"=== NOTÍCIAS RECENTES ===\n{context_str}\n\n"
            f"=== JÁ REPORTADOS (IGNORE ESTES) ===\n{history_str}\n\n"
            "Classifique as novidades em:\n"
            "🟢 UPGRADE RECOMENDADO: Ganho direto de performance, custo ou novas capacidades críticas.\n"
            "🟡 MONITORAR: Interessante, mas aguardar estabilidade ou caso de uso claro.\n"
            "🔴 IRRELEVANTE: Mudanças menores ou fora do escopo.\n\n"
            "Retorne APENAS um JSON no formato:\n"
            "{\n"
            '  "upgrades": [\n'
            '    {"tech": "Nome", "status": "🟢", "impact": "Resumo 1 linha", "url": "link"}\n'
            '  ]\n'
            "}\n"
            "Se não houver nada relevante que não tenha sido reportado, retorne upgrades vazio."
        )

        try:
            response = await invoke_with_fallback(
                CognitiveRole.FAST,
                LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    system="Você é um analista técnico direto e sem enrolação. Retorna apenas JSON.",
                    temperature=0.0
                ),
                self.pipeline.model_router,
                self.pipeline.api_keys
            )
            cycle_cost += response.cost_usd
            
            from src.core.utils import parse_llm_json
            analysis = parse_llm_json(response.text)
            upgrades = analysis.get("upgrades", [])
            
            # Filtra novos e atualiza histórico
            new_upgrades = []
            for upg in upgrades:
                tech_key = upg.get("tech", "") + upg.get("impact", "")
                if tech_key not in history:
                    new_upgrades.append(upg)
                    history[tech_key] = datetime.datetime.now().isoformat()

            if not new_upgrades:
                self._save_history(history)
                self._status = GoalStatus.IDLE
                return GoalResult(success=True, summary="Nenhum upgrade novo relevante detectado.", cost_usd=cycle_cost)

            # 4. Formata Notificação
            msg_lines = ["🔭 <b>Tech Scout — Radar de Upgrades</b>\n"]
            for upg in new_upgrades:
                msg_lines.append(
                    f"{upg['status']} <b>{upg['tech']}</b>\n"
                    f"  💡 Impacto: {upg['impact']}\n"
                    f"  🔗 <a href='{upg.get('url', '#')}'>Ver mais</a>\n"
                )
            
            msg_lines.append("\n<i>Análise baseada no stack ativo e releases recentes.</i>")
            
            self._save_history(history)
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary=f"Detectados {len(new_upgrades)} upgrades relevantes.",
                notification="\n".join(msg_lines),
                cost_usd=cycle_cost
            )

        except Exception as e:
            log.error(f"[tech_scout] Falha cognitiva: {e}", exc_info=True)
            self._status = GoalStatus.ERROR
            return GoalResult(success=False, summary=f"Falha na análise: {e}", cost_usd=cycle_cost)

    def _load_history(self) -> dict:
        if not os.path.exists(self.history_file):
            return {}
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_history(self, history: dict):
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"[tech_scout] Erro ao salvar histórico: {e}")

    def serialize_state(self) -> dict:
        return {
            "last_scout_date": self.last_scout_date,
            "active_categories": self.active_categories
        }

    def load_state(self, state: dict) -> None:
        self.last_scout_date = state.get("last_scout_date", "")
        self.active_categories = state.get("active_categories", list(TECH_CATEGORIES.keys()))

def create_goal(pipeline) -> TechScoutGoal:
    return TechScoutGoal(pipeline)
