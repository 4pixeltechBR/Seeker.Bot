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

EXTRACTION_PROMPT = """Analise esta interação e extraia fatos relevantes sobre o usuário e o contexto.

INPUT DO USUÁRIO:
{user_input}

RESUMO DA RESPOSTA:
{response_summary}

Retorne APENAS JSON válido, sem markdown:
{{
  "facts": [
    {{
      "fact": "frase curta descrevendo o fato",
      "category": "reflexive_rule|user_pref|tech_context|decision|pattern|project|general",
      "confidence": 0.7
    }}
  ],
  "response_summary": "resumo de 1-2 frases do que foi discutido"
}}

REGRAS CRÍTICAS - MEMÓRIA REFLEXIVA:
- Se o usuário estiver CORRIGINDO você, RECUSANDO um resultado, ou exigindo um AJUSTE DE FORMATO, crie URGENTE um fato da categoria `reflexive_rule`. 
  Exemplo: "Sempre que gerar planilhas comerciais, o usuário prefere que a data seja formato BR".
- Fatos `reflexive_rule` devem sempre registrar a regra de como você deve se comportar no futuro.

OUTRAS REGRAS:
- Extraia apenas fatos CONCRETOS
- Máximo 5 fatos por interação
- Categorias normais: user_pref (preferências gerais), tech_context (stack),
  decision (escolhas feitas), pattern (comportamentos recorrentes),
  project (sobre projetos ativos), general (outros)
- Confiança 0.8+ para fatos explícitos, 0.5-0.7 para inferidos
- response_summary em português curto
"""


class FactExtractor:
    """Extrai fatos de interações para memória semântica. Usa modelo FAST."""

    def __init__(self, router: ModelRouter, api_keys: dict[str, str]):
        self.router = router
        self.api_keys = api_keys

    async def extract(
        self, user_input: str, response_text: str,
    ) -> tuple[list[dict], str]:
        """Retorna: (lista_de_fatos, resumo_da_resposta)"""
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
                    system="Extraia fatos de conversas. Responda APENAS JSON válido, nada mais.",
                    max_tokens=500,
                    temperature=0.0,
                    response_format="json",
                ),
                router=self.router,
                api_keys=self.api_keys,
            )
            data = parse_llm_json(response.text)
            facts = data.get("facts", [])
            summary = data.get("response_summary", "")
            valid_facts = []
            for f in facts:
                if isinstance(f, dict) and f.get("fact") and len(f["fact"]) > 5:
                    valid_facts.append({
                        "fact": f["fact"][:200],
                        "category": f.get("category", "general"),
                        "confidence": min(0.95, max(0.1, float(f.get("confidence", 0.5)))),
                    })
            log.info(f"[extractor] {len(valid_facts)} fatos extraídos")
            return valid_facts, summary[:500]
        except Exception as e:
            log.warning(f"[extractor] Falha: {e}")
            # Fallback: sem fatos mas salva resumo mínimo
            fallback_summary = user_input[:200] if user_input else ""
            return [], fallback_summary
