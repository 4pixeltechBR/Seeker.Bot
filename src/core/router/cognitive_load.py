"""
Seeker.Bot — Cognitive Load Router
src/core/router/cognitive_load.py

Metacognição sobre quanto pensar.

Humanos não ativam o córtex pré-frontal para responder "que horas são".
O Seeker também não deveria rodar o pipeline cognitivo inteiro para
perguntas simples. Este módulo faz o pre-screening com ZERO chamadas LLM.

Três faixas:
  REFLEX     → resposta direta, sem pipeline (ex: "ok", "status?")
  DELIBERATE → Kernel + Synthesis, sem Council (ex: "como configuro X?")
  DEEP       → pipeline completo + Council + Evidence Arbitrage
               (ex: "analisa se vale migrar pra Kubernetes")

O router erra conservadoramente: na dúvida, sobe a profundidade.
O usuário pode forçar god mode a qualquer momento.
"""

import re
import logging
import asyncio
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger("seeker.router")


class CognitiveDepth(str, Enum):
    REFLEX = "reflex"  # 0 LLM calls — resposta direta
    DELIBERATE = "deliberate"  # 1-2 LLM calls — Kernel + Synthesis
    DEEP = "deep"  # 3+ LLM calls — pipeline completo


class ExecutionMode(str, Enum):
    INTERACTIVE = "interactive"  # Foco em latência (Telegram)
    HEADLESS = "headless"  # Foco em qualidade (Curadoria, Background)


@dataclass(frozen=True)
class RoutingDecision:
    """Resultado do roteamento cognitivo."""

    depth: CognitiveDepth
    reason: str
    execution_mode: ExecutionMode = ExecutionMode.INTERACTIVE
    god_mode: bool = False
    forced_module: str | None = None
    needs_web: bool = False  # Independente da profundidade
    needs_vault: bool = False  # Indica se deve buscar no Obsidian
    active_toolsets: list[str] | None = None  # Lista de toolsets ativos


# ─────────────────────────────────────────────────────────────────────
# PADRÕES DE DETECÇÃO — regex puro, zero LLM
# ─────────────────────────────────────────────────────────────────────

# God mode — sempre DEEP, sem discussão
GOD_MODE_PATTERNS = re.compile(
    r"god\s*mode|potência\s*máxima|modo\s*deus|godmode|"
    r"aprofunda|investiga|análise\s*completa|"
    r"ative?\s*o\s*godmode|ative?\s*godmode",
    re.IGNORECASE,
)

# Reflex — respostas curtas que não precisam de raciocínio
REFLEX_PATTERNS = re.compile(
    r"^(ok|sim|não|beleza|valeu|obrigado|thanks|yes|no|"
    r"blz|vlw|top|show|tmj|bom dia|boa tarde|boa noite|"
    r"oi|olá|hello|hi|hey|e aí|fala|salve|"
    r"entendi|perfeito|combinado|fechado|pode ser|bora|"
    r"que dia é hoje|que horas são|qual a data|qual é a data|hoje é que dia|"
    r"status|continua|avança|próximo|next|go)[\s!?.]*$",
    re.IGNORECASE,
)

# Perguntas de tempo/data — resolvidas pelo sistema, zero LLM
SYSTEM_ANSWERABLE = re.compile(
    r"que\s+(dia|horas?|data)\s+(é|são)\s*(hoje|agora)?|"
    r"qual\s+(a\s+)?(data|hora)\s*(de\s+hoje|atual|agora)?|"
    r"hoje\s+é\s+que\s+dia|"
    r"que\s+dia\s+da\s+semana",
    re.IGNORECASE,
)

# Deep triggers — palavras que indicam necessidade de análise profunda
DEEP_TRIGGERS = re.compile(
    r"vale\s*a\s*pena|trade.?off|compara|versus|vs\.?|"
    r"migrar|arquitetura|escalar|decisão|estratégia|"
    r"pré.?mortem|post.?mortem|red\s*team|"
    r"irreversível|consequência|longo\s*prazo|"
    r"como\s*funciona\s*realmente|descobre?\s*a\s*verdade|"
    r"analisa\s*com\s*tudo|qual\s*o\s*risco|"
    r"evidência|confiança|triangul|arbitrage|"
    r"complexo|sistêm|emergent|"
    r"investimento|roi\s|custo.?benefício",
    re.IGNORECASE,
)

# Web triggers — perguntas que PRECISAM de dados atuais da internet
# Independente da profundidade cognitiva
WEB_TRIGGERS = re.compile(
    r"atual|atualmente|hoje|agora\b|recente|último|última|"
    r"2024|2025|2026|2027|"
    r"quem\s+é\s+o|quem\s+é\s+a|quem\s+ganhou|quem\s+venceu|"
    r"qual\s+o\s+preço|qual\s+o\s+valor|quanto\s+custa|"
    r"paper|artigo|publicou|publicação|published|"
    r"lançou|lançamento|lanc(ou|amento|ado)|release|versão\s+\d|v\d+\b|"
    r"foi\s+lançad|foi\s+lancad|"
    r"estado\s+atual|status\s+de|novidades|"
    r"existe\b|ainda\s+existe|já\s+saiu|"
    r"verifi[cq]|de\s+novo|novamente|outra\s+vez|confirma|confere|checa|checagem|valida|"
    r"tem\s+certeza|realmente\s+(existe|foi|tem)|verdade\s+que|fato\s+novo|rumor|boato|dizem\s+que|"
    r"morreu|faleceu|eleito|nomeado|demitido|"
    r"placar|resultado\s+do\s+jogo|score|"
    r"clima|tempo\s*lá\s*fora|cotação|preço|valor\s*da\s*ação|"
    r"notícia|aconteceu|google\s|pesquisa|busca\s|"
    r"deepseek|gemma\s*\d|qwen\s*\d|llama\s*\d|gpt-\d|claude\s*\d|"
    r"mistral|gemini\s*\d|grok\s*\d|phi-\d|command\s*r|"
    r"modelo.*lançad|lançad.*modelo|novo\s+modelo|"
    r"benchmark|mmlu|humaneval|swe-bench|lmarena",
    re.IGNORECASE,
)

# Vault triggers — perguntas que envolvem o cofre do Obsidian
VAULT_TRIGGERS = re.compile(
    r"no cofre|no obsidian|nas notas|minhas anotações|meu segundo cérebro|"
    r"o que eu anotei|pesquisa nas notas|busca no obsidian",
    re.IGNORECASE,
)

# Local-action triggers — intenções que NUNCA precisam de busca web.
# Lembretes, agendamentos, alarmes, contagens regressivas e ações pessoais
# locais devem ser processados offline. Avaliado ANTES de WEB_TRIGGERS.
LOCAL_ACTION_TRIGGERS = re.compile(
    r"me\s+lembr[ae]|me\s+avisa|\blembrete\b|\balarme\b|\btimer\b|"
    r"daqui\s+a\s+\d+|em\s+\d+\s*(min|hora|segundo|seg|h\b)|conta\s+regressiva|"
    r"agenda|agendar|/agendar|\bschedule\b|tarefa\s+agendada|"
    r"\bdespertar\b|\bacordar\b|me\s+acorda|acorda\s+(me|eu)|"
    r"ao\s+final\s+de|daqui\s+pouco|em\s+breve|não\s+deixa\s+eu",
    re.IGNORECASE,
)

# Módulos detectáveis por keyword (ajuda o Kernel a pular detecção)
MODULE_PATTERNS = {
    "debug": re.compile(
        r"erro|error|traceback|quebrou|não\s*funciona|bug|crash|exception",
        re.IGNORECASE,
    ),
    "arq": re.compile(
        r"arquitetura|estrutur|escalar|stack|refatorar|migrar|sistema", re.IGNORECASE
    ),
    "review": re.compile(
        r"revis[ae]|code\s*review|está\s*bom|avalia|feedback", re.IGNORECASE
    ),
    "growth": re.compile(
        r"\bviews?\b|viral|hook|retenção|ctr|shorts?|engajamento", re.IGNORECASE
    ),
    "edu": re.compile(
        r"explic[ae]|como\s*funciona|o\s*que\s*é|me\s*ensin[ae]|diferença\s*entre",
        re.IGNORECASE,
    ),
    "llm": re.compile(
        r"modelo|fine.?tun|quantiz|rag\b|agente\b|embedding|llm|ollama", re.IGNORECASE
    ),
    "ideia": re.compile(
        r"ideia|e\s*se\b|brainstorm|seria\s*possível|e\s*se\s*eu", re.IGNORECASE
    ),
    "lumen": re.compile(
        r"design|ui\b|ux\b|interface|visual|slide|layout|tipografia", re.IGNORECASE
    ),
    "email": re.compile(
        r"e-?mails?|inbox|caixa\s*de\s*entrada|correspondência", re.IGNORECASE
    ),
    "vision": re.compile(
        r"veja?\s*(minha)?\s*tela|print\b|screenshot|"
        r"olh[ae]\s*(minha)?\s*tela|mostra?\s*(a\s*)?tela|"
        r"o\s*que\s*(tem|há)\s*na\s*(minha\s*)?tela|captur[ae]\s*tela|"
        r"tira?\s*(um\s*)?print|cliqu[ea]|clicar|clique\s+(em|no|na|n[oa]s)|"
        r"mouse|arrast[ea]|arrastar|press\s|pressione|apertar?\s|"
        r"abr[ae]\s|fechar?\s|minimiz|maximiz|"
        r"digit[ea]|escrev[ae]|type\s",
        re.IGNORECASE,
    ),
}


# ─────────────────────────────────────────────────────────────────────
# HEURÍSTICAS DE COMPLEXIDADE
# ─────────────────────────────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    """Conta sentenças de forma aproximada."""
    return len(re.split(r"[.!?]+", text.strip())) - 1 or 1


def _count_questions(text: str) -> int:
    """Conta perguntas no input."""
    return text.count("?")


def _has_code_block(text: str) -> bool:
    """Detecta se tem bloco de código."""
    return (
        "```" in text
        or text.strip().startswith("def ")
        or text.strip().startswith("class ")
    )


def _word_count(text: str) -> int:
    return len(text.split())


# ─────────────────────────────────────────────────────────────────────
# O ROUTER
# ─────────────────────────────────────────────────────────────────────


class CognitiveLoadRouter:
    """
    Classifica a profundidade cognitiva necessária para processar um input.

    Zero chamadas LLM por padrão, com triagem semântica via FAST LLM em
    consultas com intenção dinâmica ambígua.
    """

    def __init__(self, model_router=None, api_keys=None):
        self.model_router = model_router
        self.api_keys = api_keys

    def _create_decision(
        self,
        depth: CognitiveDepth,
        reason: str,
        mode: ExecutionMode,
        god_mode: bool = False,
        forced_module: str | None = None,
        needs_web: bool = False,
        needs_vault: bool = False,
    ) -> RoutingDecision:
        active = []
        if god_mode:
            active = ["web", "files", "terminal"]
        else:
            if needs_web:
                active.append("web")
            if depth in (CognitiveDepth.DELIBERATE, CognitiveDepth.DEEP):
                active.append("files")
            if forced_module in ("debug", "arq") and depth == CognitiveDepth.DEEP:
                active.append("terminal")
                
        return RoutingDecision(
            depth=depth,
            reason=reason,
            execution_mode=mode,
            god_mode=god_mode,
            forced_module=forced_module,
            needs_web=needs_web,
            needs_vault=needs_vault,
            active_toolsets=active,
        )

    async def route(
        self, text: str, mode: ExecutionMode = ExecutionMode.INTERACTIVE
    ) -> RoutingDecision:
        """Classifica profundidade E necessidade de web, independentemente."""

        text_stripped = text.strip()

        # Intenções locais (lembrete, agenda, timer) NUNCA precisam de web.
        # Avaliado antes de WEB_TRIGGERS para evitar falso-positivo em frases
        # como "me lembre agora" ("agora" matcharia WEB_TRIGGERS sem isso).
        is_local_action = bool(LOCAL_ACTION_TRIGGERS.search(text_stripped))

        # Detecta necessidade de web ANTES da profundidade
        needs_web = False if is_local_action else bool(WEB_TRIGGERS.search(text_stripped))
        needs_vault = bool(VAULT_TRIGGERS.search(text_stripped))

        # Determina heurística se a pergunta é do tipo Reflex curta
        is_reflex = bool(
            REFLEX_PATTERNS.match(text_stripped) or
            SYSTEM_ANSWERABLE.search(text_stripped) or
            (_word_count(text_stripped) <= 3 and not DEEP_TRIGGERS.search(text_stripped) and "?" not in text_stripped)
        )

        # Roteador Semântico de Triagem Rápida
        if not needs_web and not is_reflex and self.model_router and self.api_keys:
            try:
                from src.providers.base import LLMRequest, invoke_with_fallback
                from config.models import CognitiveRole
                from src.core.utils import parse_llm_json

                classifier_prompt = (
                    "Você é o Classificador de Tempo Real do Seeker.\n"
                    "Analise a mensagem do usuário e decida se responder de forma correta e precisa EXIGE dados em tempo real da internet (como versões recentes de software, preços, notícias recentes, eventos atuais, cotações ou documentação de ferramentas de tecnologia atualizadas pós-2025).\n"
                    "Retorne APENAS um JSON com o formato:\n"
                    '{"needs_web": true/false}'
                )

                resp = await asyncio.wait_for(
                    invoke_with_fallback(
                        role=CognitiveRole.FAST,
                        request=LLMRequest(
                            messages=[
                                {"role": "system", "content": classifier_prompt},
                                {"role": "user", "content": f"Mensagem: {text_stripped}"}
                            ],
                            max_tokens=20,
                            temperature=0.0,
                            response_format="json"
                        ),
                        router=self.model_router,
                        api_keys=self.api_keys
                    ),
                    timeout=1.5
                )
                res_json = parse_llm_json(resp.text)
                if res_json and isinstance(res_json.get("needs_web"), bool):
                    needs_web = res_json["needs_web"]
                    log.info(f"[router] Triagem semântica detectou needs_web={needs_web}")
            except Exception as e:
                # Falha na triagem semântica (ex: rate-limit, timeout) → mantém
                # needs_web=False. Forçar True aqui causava cascata errada:
                # busca web → modelo gera queries duplicadas → guardrail dispara.
                log.warning(
                    f"[router] Falha na triagem semântica ({e}). "
                    f"Fallback conservador: needs_web=False para evitar busca desnecessária."
                )
                needs_web = False

        # ── Perguntas de sistema: tempo, data ─────────────
        if SYSTEM_ANSWERABLE.search(text_stripped):
            return self._create_decision(
                depth=CognitiveDepth.REFLEX,
                reason="pergunta de sistema (data/hora)",
                mode=mode,
                needs_web=False,
                needs_vault=needs_vault,
                forced_module="system_time",
            )

        # ── God Mode: sempre DEEP + web ───────────────────────
        if GOD_MODE_PATTERNS.search(text_stripped):
            trigger = GOD_MODE_PATTERNS.search(text_stripped).group()
            return self._create_decision(
                depth=CognitiveDepth.DEEP,
                reason=f"god mode trigger: '{trigger}'",
                mode=mode,
                god_mode=True,
                needs_web=True,
                needs_vault=True,
            )

        # ── Reflex: input curto e padrão reconhecido ──────────
        if REFLEX_PATTERNS.match(text_stripped):
            return self._create_decision(
                depth=CognitiveDepth.REFLEX,
                reason="padrão reflex reconhecido",
                mode=mode,
                needs_web=needs_web,
                needs_vault=needs_vault,
            )

        # ── Input muito curto sem trigger → REFLEX ────────────
        words = _word_count(text_stripped)
        has_question = "?" in text_stripped
        if words <= 3 and not DEEP_TRIGGERS.search(text_stripped) and not has_question:
            return self._create_decision(
                depth=CognitiveDepth.REFLEX,
                reason=f"input curto ({words} palavras), sem deep triggers",
                mode=mode,
                needs_web=needs_web,
                needs_vault=needs_vault,
            )

        # ── Deep: triggers explícitos ─────────────────────────
        deep_match = DEEP_TRIGGERS.search(text_stripped)
        if deep_match:
            module = self._detect_module(text_stripped)
            return self._create_decision(
                depth=CognitiveDepth.DEEP,
                reason=f"deep trigger: '{deep_match.group()}'",
                mode=mode,
                forced_module=module,
                needs_web=True,
                needs_vault=needs_vault,
            )

        # ── Heurísticas de complexidade ───────────────────────
        questions = _count_questions(text_stripped)
        sentences = _count_sentences(text_stripped)
        has_code = _has_code_block(text_stripped)

        complexity_score = 0
        complexity_reasons = []

        if words > 100:
            complexity_score += 2
            complexity_reasons.append(f"{words} palavras")
        elif words > 40:
            complexity_score += 1
            complexity_reasons.append(f"{words} palavras")

        if questions >= 3:
            complexity_score += 2
            complexity_reasons.append(f"{questions} perguntas")
        elif questions >= 2:
            complexity_score += 1
            complexity_reasons.append(f"{questions} perguntas")

        if has_code:
            complexity_score += 1
            complexity_reasons.append("contém código")

        if sentences > 5:
            complexity_score += 1
            complexity_reasons.append(f"{sentences} sentenças")

        # Score → profundidade
        module = self._detect_module(text_stripped)

        if complexity_score >= 3:
            return self._create_decision(
                depth=CognitiveDepth.DEEP,
                reason=f"alta complexidade ({', '.join(complexity_reasons)})",
                mode=mode,
                forced_module=module,
                needs_web=True,
                needs_vault=needs_vault,
            )
        elif complexity_score >= 1 or words > 10:
            # Em modo HEADLESS, complexidade moderada pode ser tratada como DEEP
            # para forçar o loop de refinamento
            target_depth = CognitiveDepth.DELIBERATE
            if mode == ExecutionMode.HEADLESS and complexity_score >= 2:
                target_depth = CognitiveDepth.DEEP

            return self._create_decision(
                depth=target_depth,
                reason=f"complexidade moderada ({', '.join(complexity_reasons or ['input médio'])})",
                mode=mode,
                forced_module=module,
                needs_web=needs_web,
                needs_vault=needs_vault,
            )

        # ── Default conservador ───────────────────
        return self._create_decision(
            depth=CognitiveDepth.DELIBERATE,
            reason="default conservador",
            mode=mode,
            forced_module=module,
            needs_web=needs_web,
        )

    def _detect_module(self, text: str) -> str | None:
        """Detecta módulo cognitivo por keyword match."""
        scores: dict[str, int] = {}
        for module, pattern in MODULE_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                scores[module] = len(matches)

        if not scores:
            return None
        return max(scores, key=scores.get)


# ─────────────────────────────────────────────────────────────────────
# DEMONSTRAÇÃO
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    router = CognitiveLoadRouter()

    test_cases = [
        "ok",
        "bom dia",
        "status",
        "como configuro o nginx?",
        "ative o godmode",
        "vale a pena migrar de MongoDB pra PostgreSQL?",
        "analisa com tudo se devo usar LangGraph ou loop async puro",
        "o que é RAG?",
        "esse código tá dando erro: ```python\ndef foo(): pass```",
        "compara DeepSeek V3.2 vs GPT-5 pra uso agêntico, "
        "considerando custo, latência, tool use e contexto. "
        "Quero trade-offs reais, não marketing.",
        "blz",
        "investiga como funciona realmente o Evidence Arbitrage "
        "e se existe algo parecido no mercado",
    ]

    for case in test_cases:
        decision = router.route(case)
        preview = case[:60] + "..." if len(case) > 60 else case
        print(
            f"[{decision.depth.value:>10}] "
            f"{'🔴 GOD' if decision.god_mode else '   '} "
            f"mod={decision.forced_module or '-':>6} | "
            f"{preview}"
        )
        print(f"             razão: {decision.reason}")
        print()
