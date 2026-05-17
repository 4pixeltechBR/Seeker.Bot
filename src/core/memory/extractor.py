"""
Seeker.Bot — Fact Extractor
src/core/memory/extractor.py

Extrai fatos semânticos de conversas em background.
Roda DEPOIS da resposta — não bloqueia o usuário.
"""

import logging
import os
import re

from config.models import CognitiveRole, ModelRouter
from src.core.utils import parse_llm_json
from src.providers.base import LLMRequest, invoke_with_fallback

log = logging.getLogger("seeker.memory.extractor")

# ─────────────────────────────────────────────────────────────────────
# Identity-rule guard (incident 2026-05-16)
# ─────────────────────────────────────────────────────────────────────
# O extractor PRECISA NÃO destilar "regras" sobre nome/identidade do bot.
# Identidade é config (ASSISTANT_NAME no .env), não aprendizado de runtime.
#
# Sem este guard, uma única resposta defensiva tipo "eu sou o X, não Y"
# vira reflexive_rule de confidence 0.95, é re-injetada como L1 em todo turno,
# e o bot fica preso recusando o próprio nome configurado. Aconteceu em
# 2026-05-15 → 2026-05-16 (9 regras venenosas removidas manualmente).
#
# Os padrões abaixo são reconhecimento, não trava. O nome canônico do projeto
# ("seeker") fica fixo porque é o nome do repo; o nome dinâmico do operador
# vem do env ASSISTANT_NAME e é montado em runtime. Qualquer fork pode mudar
# o env e o guard se ajusta automaticamente — sem hardcode de apelido.


def _assistant_name_pattern() -> str:
    """
    Pattern regex (escapado) para o nome configurado em ASSISTANT_NAME.
    Vazio se não configurado — daí o regex base já cobre 'bot|seeker|...'.
    """
    name = os.getenv("ASSISTANT_NAME", "").strip()
    if not name or name.lower() == "seeker":
        return ""  # já está no _BASE_SUBJECTS
    return re.escape(name.lower())


_BASE_SUBJECTS = (
    r"bot|seeker|"
    r"ia|i\.a\.|"
    r"assistente|sistema|agente|"
    r"identificador|alcunha|apelido|nome do (?:bot|assistente)|"
    r"o nome|seu nome"
)


def _build_subject_re() -> re.Pattern[str]:
    extra = _assistant_name_pattern()
    pattern = _BASE_SUBJECTS if not extra else f"{extra}|{_BASE_SUBJECTS}"
    return re.compile(rf"\b({pattern})\b", re.IGNORECASE)


_IDENTITY_SUBJECT_RE = _build_subject_re()

_IDENTITY_VERB_RE = re.compile(
    r"\b("
    r"recus[ao]|recusa[md]o?|"
    r"n[aã]o deve|nao deve|"
    r"deve ser chamad[oa]?|chamar (?:apenas|somente|exclusivamente)|"
    r"identific\w*(?:-se)?|"      # identifica/identificar-se/identifica-se/identificou
    r"exclusivamente|"
    r"se refer(?:e|ir)|"
    r"opera como|opera sob|"
    r"descart[ao] (?:nomes|atribui)|"
    r"nomes? extern[oa]s?"
    r")\b",
    re.IGNORECASE,
)


# Âncoras semânticas — frases que SOZINHAS indicam regra de identidade,
# independente de sujeito gramatical. "Nomes externos" + "atribui" /
# "descart" praticamente só aparecem em contexto de regra-de-nome.
_IDENTITY_ANCHORS = (
    re.compile(r"\bnomes?\s+extern[oa]s?\b", re.IGNORECASE),
    re.compile(r"\batribui[çc][aã]o\s+de\s+nomes?\b", re.IGNORECASE),
    re.compile(r"\boutras?\s+alcunhas?\b", re.IGNORECASE),
    re.compile(r"\bn[aã]o\s+ser?\s+chamad[oa]\b", re.IGNORECASE),
)


def _looks_like_identity_rule(fact_text: str) -> bool:
    """
    True se o fato fala sobre nome/identidade do bot em tom prescritivo.
    Heurística conservadora — bloqueia tanto regras anti quanto pró-nome,
    porque a identidade vem do .env, não da conversa.

    Combinação: (sujeito identitário + verbo prescritivo) OU (âncora forte).

    O sujeito é re-buildado para incluir o ASSISTANT_NAME atual do env,
    permitindo que forks com nomes customizados peguem regras venenosas
    sobre seus próprios apelidos sem precisar editar este arquivo.
    """
    if not fact_text:
        return False
    if any(p.search(fact_text) for p in _IDENTITY_ANCHORS):
        return True
    subject_re = _build_subject_re()
    return bool(subject_re.search(fact_text) and _IDENTITY_VERB_RE.search(fact_text))


EXTRACTION_PROMPT = """Analise esta interação e extraia fatos e relacionamentos estruturados (Knowledge Graph).

INPUT DO USUÁRIO:
{user_input}

RESUMO DA RESPOSTA:
{response_summary}

Retorne APENAS JSON válido:
{{
  "entities": [
    {{ "name": "Nome", "type": "person|project|tech|org|place", "props": {{ "key": "val" }} }}
  ],
  "triples": [
    {{ "subject": "Victor", "predicate": "has_project", "object": "Seeker.Bot", "valid_from": "2026-04" }}
  ],
  "facts": [
    {{ "fact": "fato textual curto", "category": "reflexive_rule|user_pref|tech_context|decision|project|general", "confidence": 0.8 }}
  ],
  "response_summary": "resumo de 1-2 frases"
}}

REGRAS CRÍTICAS — MEMÓRIA REFLEXIVA:
- Se o usuário estiver CORRIGINDO, RECUSANDO ou EXIGINDO AJUSTE de COMPORTAMENTO/FORMATO,
  crie URGENTE um fato `reflexive_rule`.
  Exemplo: "Sempre que gerar relatórios, usar formato de data BR (DD/MM/AAAA)".
- Fatos `reflexive_rule` registram como o bot deve se comportar no futuro. Prioridade máxima.

PROIBIDO — NUNCA CRIE FATOS SOBRE:
- Nome do bot ou identidade do assistente (ex: "deve se chamar X", "recusa o nome Y",
  "identifica-se como Z", "opera como W"). A identidade do bot é CONFIGURAÇÃO de
  ambiente (ASSISTANT_NAME no .env), não memória aprendida. Qualquer fato sobre
  nome/alcunha/apelido do bot será descartado pelo filtro pós-extração de qualquer
  forma — não desperdice slots.

OUTRAS REGRAS:
1. ENTIDADES: Nomes próprios de pessoas, projetos (ViralClip, Seeker), tecnologias (Gemini, Flux) e orgs.
2. TRIPLAS: Relacionamentos duradouros ou mudanças de estado (quem usa o quê, status de projeto).
3. FATOS: Máximo 5 fatos por interação. Confiança 0.8+ para explícitos, 0.5-0.7 para inferidos.
4. TEMPO: Se houver indicação temporal, use "YYYY-MM" no `valid_from`.
"""


class FactExtractor:
    """Extrai fatos e triplas do Knowledge Graph. Usa modelo FAST."""

    def __init__(self, router: ModelRouter, api_keys: dict[str, str]):
        self.router = router
        self.api_keys = api_keys

    async def extract(
        self,
        user_input: str,
        response_text: str,
    ) -> dict:
        """
        Retorna dicionário com:
          - facts: list[dict]
          - entities: list[dict]
          - triples: list[dict]
          - summary: str
        """
        response_summary = response_text[:800]
        try:
            response = await invoke_with_fallback(
                role=CognitiveRole.FAST,
                request=LLMRequest(
                    messages=[
                        {
                            "role": "user",
                            "content": EXTRACTION_PROMPT.format(
                                user_input=user_input[:500],
                                response_summary=response_summary,
                            ),
                        }
                    ],
                    system="Você é um extrator de Knowledge Graph. Responda APENAS JSON.",
                    max_tokens=800,
                    temperature=0.0,
                    response_format="json",
                ),
                router=self.router,
                api_keys=self.api_keys,
            )
            data = parse_llm_json(response.text)

            return {
                "facts": self._sanitize_facts(data.get("facts", [])),
                "entities": data.get("entities", []),
                "triples": data.get("triples", []),
                "summary": data.get("response_summary", "")[:500],
            }
        except Exception as e:
            log.warning(f"[extractor] Falha: {e}")
            return {
                "facts": [],
                "entities": [],
                "triples": [],
                "summary": user_input[:200],
            }

    def _sanitize_facts(self, facts: list) -> list[dict]:
        valid = []
        dropped_identity = 0
        for f in facts:
            if not (isinstance(f, dict) and f.get("fact") and len(f["fact"]) > 5):
                continue
            fact_text = f["fact"][:200]

            # Identity-rule guard — incident 2026-05-16. Defense in depth: o
            # prompt já avisa, mas se o LLM mesmo assim destilar uma regra de
            # nome/identidade, dropamos aqui.
            if _looks_like_identity_rule(fact_text):
                dropped_identity += 1
                log.info(
                    f"[extractor] Identity-rule dropped (guard): {fact_text[:100]!r}"
                )
                continue

            valid.append(
                {
                    "fact": fact_text,
                    "category": f.get("category", "general"),
                    "confidence": min(
                        0.95, max(0.1, float(f.get("confidence", 0.5)))
                    ),
                }
            )
        if dropped_identity:
            log.warning(
                f"[extractor] Bloqueou {dropped_identity} regra(s) de identidade — "
                f"ver _looks_like_identity_rule em src/core/memory/extractor.py"
            )
        return valid
