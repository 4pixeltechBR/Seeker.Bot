"""
Seeker.Bot — Fact Extractor
src/core/memory/extractor.py

Extrai fatos semânticos de conversas em background.
Roda DEPOIS da resposta — não bloqueia o usuário.
"""

import json
import logging

from config.models import CognitiveRole, ModelRouter
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
      "category": "user_pref|tech_context|decision|pattern|project|general",
      "confidence": 0.7
    }}
  ],
  "response_summary": "resumo de 1-2 frases do que foi discutido"
}}

REGRAS:
- Extraia apenas fatos CONCRETOS e VERIFICÁVEIS na conversa
- Máximo 5 fatos por interação
- Categorias: user_pref (preferências), tech_context (stack/hardware),
  decision (escolhas feitas), pattern (comportamentos recorrentes),
  project (sobre projetos ativos), general (outros)
- Confiança 0.8+ para fatos explícitos, 0.5-0.7 para inferidos
- Se não há fatos relevantes, retorne lista vazia
- response_summary em português, máximo 2 frases
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
                    max_tokens=500,
                    temperature=0.0,
                    response_format="json",
                ),
                router=self.router,
                api_keys=self.api_keys,
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            data = json.loads(text.strip())
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
            return [], ""
