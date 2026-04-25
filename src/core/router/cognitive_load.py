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
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger("seeker.router")


class CognitiveDepth(str, Enum):
    REFLEX     = "reflex"      # 0 LLM calls — resposta direta
    DELIBERATE = "deliberate"  # 1-2 LLM calls — Kernel + Synthesis
    DEEP       = "deep"        # 3+ LLM calls — pipeline completo


class ExecutionMode(str, Enum):
    INTERACTIVE = "interactive"  # Foco em latência (Telegram)
    HEADLESS    = "headless"     # Foco em qualidade (Curadoria, Background)


@dataclass(frozen=True)
class RoutingDecision:
    """Resultado do roteamento cognitivo."""
    depth: CognitiveDepth
    reason: str
    execution_mode: ExecutionMode = ExecutionMode.INTERACTIVE
    god_mode: bool = False
    forced_module: str | None = None
    needs_web: bool = False            # Independente da profundidade
    needs_vault: bool = False          # Indica se deve buscar no Obsidian


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
    r"estado\s+atual|status\s+de|novidades|"
    r"existe\b|ainda\s+existe|já\s+saiu|foi\s+lançad|foi\s+lancad|"
    r"morreu|faleceu|eleito|nomeado|demitido|"
    r"placar|resultado\s+do\s+jogo|score|"
    r"clima|tempo\s*lá\s*fora|cotação|preço|valor\s*da\s*ação|"
    r"notícia|aconteceu|google\s|pesquisa|busca\s|"
    r"verifi[cq]|de\s+novo|novamente|outra\s+vez|confirma|"
    r"tem\s+certeza|realmente\s+(existe|foi|tem)|"
    # Modelos de IA — sempre requerem busca web (versões mudam rápido)
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
    re.IGNORECASE
)

# Módulos detectáveis por keyword (ajuda o Kernel a pular detecção)
MODULE_PATTERNS = {
    "debug":  re.compile(r"erro|error|traceback|quebrou|não\s*funciona|bug|crash|exception", re.IGNORECASE),
    "arq":    re.compile(r"arquitetura|estrutur|escalar|stack|refatorar|migrar|sistema", re.IGNORECASE),
    "review": re.compile(r"revis[ae]|code\s*review|está\s*bom|avalia|feedback", re.IGNORECASE),
    "growth": re.compile(r"\bviews?\b|viral|hook|retenção|ctr|shorts?|engajamento", re.IGNORECASE),
    "edu":    re.compile(r"explic[ae]|como\s*funciona|o\s*que\s*é|me\s*ensin[ae]|diferença\s*entre", re.IGNORECASE),
    "llm":    re.compile(r"modelo|fine.?tun|quantiz|rag\b|agente\b|embedding|llm|ollama", re.IGNORECASE),
    "ideia":  re.compile(r"ideia|e\s*se\b|brainstorm|seria\s*possível|e\s*se\s*eu", re.IGNORECASE),
    "lumen":  re.compile(r"design|ui\b|ux\b|interface|visual|slide|layout|tipografia", re.IGNORECASE),
    "email":  re.compile(r"e-?mails?|inbox|caixa\s*de\s*entrada|correspondência", re.IGNORECASE),
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
    return len(re.split(r'[.!?]+', text.strip())) - 1 or 1


def _count_questions(text: str) -> int:
    """Conta perguntas no input."""
    return text.count("?")


def _has_code_block(text: str) -> bool:
    """Detecta se tem bloco de código."""
    return "```" in text or text.strip().startswith("def ") or text.strip().startswith("class ")


def _word_count(text: str) -> int:
    return len(text.split())


# ─────────────────────────────────────────────────────────────────────
# O ROUTER
# ─────────────────────────────────────────────────────────────────────

class CognitiveLoadRouter:
    """
    Classifica a profundidade cognitiva necessária para processar um input.
    
    Zero chamadas LLM. Regex + heurísticas + contadores.
    Erra conservadoramente — na dúvida, sobe.
    
    Uso:
        router = CognitiveLoadRouter()
        decision = router.route("analisa se vale migrar pra K8s")
        # RoutingDecision(depth=DEEP, reason="deep trigger: migrar", god_mode=False)
    """

    def route(self, text: str, mode: ExecutionMode = ExecutionMode.INTERACTIVE) -> RoutingDecision:
        """Classifica profundidade E necessidade de web, independentemente."""

        text_stripped = text.strip()

        # Detecta necessidade de web ANTES da profundidade
        needs_web = bool(WEB_TRIGGERS.search(text_stripped))
        needs_vault = bool(VAULT_TRIGGERS.search(text_stripped))

        # ── Perguntas de sistema: tempo, data ─────────────
        if SYSTEM_ANSWERABLE.search(text_stripped):
            return RoutingDecision(
                depth=CognitiveDepth.REFLEX,
                reason="pergunta de sistema (data/hora)",
                execution_mode=mode,
                needs_web=False,
                needs_vault=needs_vault,
                forced_module="system_time",
            )

        # ── God Mode: sempre DEEP + web ───────────────────────
        if GOD_MODE_PATTERNS.search(text_stripped):
            trigger = GOD_MODE_PATTERNS.search(text_stripped).group()
            return RoutingDecision(
                depth=CognitiveDepth.DEEP,
                reason=f"god mode trigger: '{trigger}'",
                execution_mode=mode,
                god_mode=True,
                needs_web=True,  # God Mode sempre busca
                needs_vault=True, # God Mode também olha o cofre
            )

        # ── Reflex: input curto e padrão reconhecido ──────────
        if REFLEX_PATTERNS.match(text_stripped):
            return RoutingDecision(
                depth=CognitiveDepth.REFLEX,
                reason="padrão reflex reconhecido",
                execution_mode=mode,
                needs_web=needs_web,  # Respeita WEB_TRIGGERS mesmo em reflex
                needs_vault=needs_vault,
            )

        # ── Input muito curto sem trigger → REFLEX ────────────
        words = _word_count(text_stripped)
        has_question = "?" in text_stripped
        if words <= 3 and not DEEP_TRIGGERS.search(text_stripped) and not has_question:
            return RoutingDecision(
                depth=CognitiveDepth.REFLEX,
                reason=f"input curto ({words} palavras), sem deep triggers",
                execution_mode=mode,
                needs_web=needs_web,  # Respeita WEB_TRIGGERS mesmo em reflex
                needs_vault=needs_vault,
            )

        # ── Deep: triggers explícitos ─────────────────────────
        deep_match = DEEP_TRIGGERS.search(text_stripped)
        if deep_match:
            module = self._detect_module(text_stripped)
            return RoutingDecision(
                depth=CognitiveDepth.DEEP,
                reason=f"deep trigger: '{deep_match.group()}'",
                execution_mode=mode,
                forced_module=module,
                needs_web=True,  # Deep sempre busca
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
            return RoutingDecision(
                depth=CognitiveDepth.DEEP,
                reason=f"alta complexidade ({', '.join(complexity_reasons)})",
                execution_mode=mode,
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
                
            return RoutingDecision(
                depth=target_depth,
                reason=f"complexidade moderada ({', '.join(complexity_reasons or ['input médio'])})",
                execution_mode=mode,
                forced_module=module,
                needs_web=needs_web,
                needs_vault=needs_vault,
            )

        # ── Default conservador ───────────────────
        return RoutingDecision(
            depth=CognitiveDepth.DELIBERATE,
            reason="default conservador",
            execution_mode=mode,
            forced_module=module,
            needs_web=needs_web,
        )

    def _detect_module(self, text: str) -> str | None:
        """Detecta módulo cognitivo por keyword match com hierarquia de desempate."""
        scores: dict[str, int] = {}
        for module, pattern in MODULE_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                scores[module] = len(matches)

        if not scores:
            return None
            
        # Hierarquia estrita (cynefin mapping) em caso de empate
        hierarchy = ["vision", "debug", "arq", "review", "growth", "edu", "llm", "lumen", "email", "ideia"]
        
        # Encontra a pontuação máxima
        max_score = max(scores.values())
        
        # Filtra os módulos que atingiram a pontuação máxima
        top_modules = [m for m, s in scores.items() if s == max_score]
        
        # Desempata usando a hierarquia (o menor índice na lista vence)
        return min(top_modules, key=lambda m: hierarchy.index(m) if m in hierarchy else 99)


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
