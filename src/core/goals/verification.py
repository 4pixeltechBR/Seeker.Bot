"""
Seeker.Bot — Verification Worker
src/core/goals/verification.py

Separa "gerar" de "verificar" — pattern do Claude Code.
"Verification means proving the code works, not confirming it exists."

Aplicado ao Revenue Hunter:
antes de notificar um HOT LEAD, faz busca direcionada para cruzar:
- O alvo existe mesmo? (prefeitura, sindicato, paróquia)
- O trigger é recente? (edital ativo, evento confirmado)
- O decisor está no cargo? (nomeação não foi revogada)

Se a verificação falhar, degrada o score e marca como "não verificado".
"""

import logging
from src.providers.base import LLMRequest, invoke_with_fallback
from src.core.search.web import WebSearcher
from config.models import ModelRouter, CognitiveRole

log = logging.getLogger("seeker.verification")

VERIFY_PROMPT = """Você é um verificador de leads de vendas. Sua tarefa é CRUZAR informações.

ATENÇÃO: O ano atual é {current_year}. Leads focados em anos anteriores (ex: {last_year}) são INVÁLIDOS e devem ser sumariamente pontuados com score < 30 e marcados como verified=false.

LEAD ORIGINAL:
- Alvo: {target}
- Trigger: {trigger}
- Score: {score}/100

RESULTADOS DA BUSCA DE VERIFICAÇÃO:
{verification_context}

Avalie CRITICAMENTE:
1. O alvo existe e é ativo? (site oficial, CNPJ, endereço)
2. O trigger é EXTREMAMENTE recente (últimos 90 dias do ano {current_year}) e NÃO é notícia reciclada?
3. Há evidência de que o evento/licitação/nomeação ainda está vigente?

Responda APENAS JSON:
{{
  "verified": true/false,
  "confidence": <0.0 a 1.0>,
  "reasoning": "<1 linha justificando. Se for de anos anteriores, afirme 'Notícia de anos anteriores, lead frio'>",
  "red_flags": ["<flag1>", "<flag2>"],
  "adjusted_score": <score ajustado 0-100>
}}
"""


class VerificationWorker:
    """
    Verifica leads antes da notificação.
    Busca web direcionada + LLM como juiz de verificação.
    """

    def __init__(
        self,
        searcher: WebSearcher,
        model_router: ModelRouter,
        api_keys: dict[str, str],
        min_confidence: float = 0.4,
    ):
        self.searcher = searcher
        self.model_router = model_router
        self.api_keys = api_keys
        self.min_confidence = min_confidence

    async def verify_lead(
        self, target: str, trigger: str, score: int
    ) -> dict:
        """
        Verifica um lead via busca direcionada + LLM.

        Returns:
            dict com keys: verified, confidence, reasoning, red_flags, adjusted_score
            Em caso de falha, retorna resultado não-verificado com score original.
        """
        try:
            from datetime import date
            current_year = date.today().year

            # Busca direcionada ao alvo específico
            queries = [
                f'"{target}" site oficial',
                f'"{target}" "{trigger}" {current_year}',
            ]

            all_results = []
            for q in queries:
                try:
                    res = await self.searcher.search(q, max_results=3)
                    if res.results:
                        all_results.extend(res.results)
                except Exception:
                    continue

            if not all_results:
                log.info(f"[verify] Sem resultados de verificação para {target}")
                return self._unverified_result(score, "Sem dados de verificação")

            # Monta contexto de verificação
            verification_context = "\n".join(
                f"- [{r.title[:60]}] {r.snippet[:150]}"
                for r in all_results[:6]
            )

            # LLM como juiz
            prompt = VERIFY_PROMPT.format(
                target=target,
                trigger=trigger,
                score=score,
                verification_context=verification_context,
                current_year=current_year,
                last_year=current_year - 1,
            )

            req = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                system="Verificador crítico. Responda APENAS JSON válido.",
                temperature=0.1,
            )

            resp = await invoke_with_fallback(
                CognitiveRole.JUDGE, req,
                self.model_router, self.api_keys,
            )

            # Parse
            text = resp.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]

            import json
            result = json.loads(text.strip())

            # Valida campos mínimos
            result.setdefault("verified", False)
            result.setdefault("confidence", 0.5)
            result.setdefault("reasoning", "")
            result.setdefault("red_flags", [])
            result.setdefault("adjusted_score", score)
            result["cost_usd"] = resp.cost_usd

            log.info(
                f"[verify] {target}: verified={result['verified']} "
                f"conf={result['confidence']:.0%} "
                f"score={score}→{result['adjusted_score']} "
                f"flags={result['red_flags']}"
            )

            return result

        except Exception as e:
            log.warning(f"[verify] Falha na verificação de {target}: {e}")
            return self._unverified_result(score, f"Erro: {e}")

    def _unverified_result(self, original_score: int, reason: str) -> dict:
        """Resultado fallback quando verificação falha."""
        return {
            "verified": False,
            "confidence": 0.0,
            "reasoning": reason,
            "red_flags": ["Verificação não executada"],
            "adjusted_score": original_score,
            "cost_usd": 0.0,
        }
