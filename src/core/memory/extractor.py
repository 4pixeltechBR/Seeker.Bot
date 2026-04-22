"""
Seeker.Bot — Fact Extractor
src/core/memory/extractor.py

Extrai fatos semânticos de conversas em background.
Roda DEPOIS da resposta — não bloqueia o usuário.
"""

import logging

from config.models import CognitiveRole, ModelRouter
from src.core.utils import parse_llm_json
from src.providers.base import LLMRequest, invoke_with_fallback

log = logging.getLogger("seeker.memory.extractor")

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
- Se o usuário estiver CORRIGINDO, RECUSANDO ou EXIGINDO AJUSTE, crie URGENTE um fato `reflexive_rule`.
  Exemplo: "Sempre que gerar relatórios, usar formato de data BR (DD/MM/AAAA)".
- Fatos `reflexive_rule` registram como o bot deve se comportar no futuro. Prioridade máxima.

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
        self, user_input: str, response_text: str,
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
                    messages=[{
                        "role": "user",
                        "content": EXTRACTION_PROMPT.format(
                            user_input=user_input[:500],
                            response_summary=response_summary,
                        ),
                    }],
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
                "summary": data.get("response_summary", "")[:500]
            }
        except Exception as e:
            log.warning(f"[extractor] Falha: {e}")
            return {"facts": [], "entities": [], "triples": [], "summary": user_input[:200]}

    def _sanitize_facts(self, facts: list) -> list[dict]:
        valid = []
        for f in facts:
            if isinstance(f, dict) and f.get("fact") and len(f["fact"]) > 5:
                valid.append({
                    "fact": f["fact"][:200],
                    "category": f.get("category", "general"),
                    "confidence": min(0.95, max(0.1, float(f.get("confidence", 0.5)))),
                })
        return valid
