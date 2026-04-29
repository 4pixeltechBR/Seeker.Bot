"""
Discovery Matrix — Qualificação Inicial de Leads

Fase 2.5 do Scout Hunter 2.0:
- Avalia cada lead em 3 dimensões: Fit Score, Intent Signals, Budget Indicator
- Filtra leads com fit_score < 60 (economiza LLM na qualification avançada)
- Batching: até 5 leads por LLM call para economizar tokens
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

log = logging.getLogger("seeker.seeker_sales.discovery_matrix")


@dataclass
class DiscoveryMatrixResult:
    """Resultado da avaliação de um lead pela Discovery Matrix"""
    fit_score: int                      # 0-100
    fit_score_reasoning: str            # Por que esse score?
    intent_signals_level: int           # 0-5
    intent_signals_evidence: List[str]  # ["hiring_active", "recent_funding", ...]
    budget_indicator: str               # "10k-50k", "50k-100k", "100k+", etc
    passed_minimum_threshold: bool      # True se fit_score >= 60


class DiscoveryMatrix:
    """
    Avaliação inicial e qualificação de leads em 3 dimensões.

    Roda APÓS enrichment, ANTES de qualification avançada (BANT).
    Reduz volume de leads para processar (filtra fit_score < 60).
    """

    def __init__(self, cascade_adapter):
        """
        Inicializa Discovery Matrix.

        Args:
            cascade_adapter: CascadeAdapter para chamadas LLM (role FAST)
        """
        self.cascade = cascade_adapter
        self._batch_cache = {}  # Para batch processing (opcional)

    async def evaluate_lead(
        self,
        lead: Dict[str, Any],
        niche: str,
        region: str
    ) -> DiscoveryMatrixResult:
        """
        Avalia um lead individual em 3 dimensões.

        Args:
            lead: Dict com campos {name, company, role, industry, location, bio_summary, source_url, email_address, website}
            niche: Nicho alvo ("eventos", "casamento", "corporativo", etc)
            region: Região alvo ("goiania", "brasilia", etc)

        Returns:
            DiscoveryMatrixResult com scores e evidências
        """
        # Construir contexto do lead
        ctx = self._build_lead_context(lead, niche, region)

        # Chamar LLM para avaliação
        prompt = self._build_evaluation_prompt(ctx, niche, region)

        try:
            # Usar cascade FAST role para avaliação rápida
            response = await self.cascade.call(
                role="FAST",  # Role FAST para avaliação rápida
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,  # Frio — avaliação determinística
                max_tokens=300,
            )

            # Parsear resposta JSON
            result = self._parse_llm_response(response.get("content", "{}"))

            # Log da avaliação
            log.info(
                f"[discovery_matrix] Lead '{lead.get('name')}' @ '{lead.get('company')}': "
                f"fit={result.fit_score}, intent={result.intent_signals_level}, "
                f"budget={result.budget_indicator}"
            )

            return result

        except Exception as e:
            log.error(f"[discovery_matrix] Erro ao avaliar lead: {e}", exc_info=True)
            # Retornar resultado padrão (conservador)
            return DiscoveryMatrixResult(
                fit_score=50,
                fit_score_reasoning="Erro na avaliação, assumindo score médio",
                intent_signals_level=2,
                intent_signals_evidence=["error_fallback"],
                budget_indicator="10k-50k",
                passed_minimum_threshold=False
            )

    def _build_lead_context(self, lead: Dict, niche: str, region: str) -> str:
        """Constrói contexto estruturado do lead para o LLM."""
        return (
            f"LEAD DATA:\n"
            f"- Name: {lead.get('name', 'Unknown')}\n"
            f"- Company: {lead.get('company', 'Unknown')}\n"
            f"- Role: {lead.get('role', 'Unknown')}\n"
            f"- Industry: {lead.get('industry', 'Unknown')}\n"
            f"- Location: {lead.get('location', region)}\n"
            f"- Bio: {lead.get('bio_summary', 'N/A')[:200]}\n"
            f"- Website: {lead.get('website', 'N/A')}\n"
            f"- Email: {lead.get('email_address', 'N/A')}\n"
            f"\nTARGET CONTEXT:\n"
            f"- Niche: {niche}\n"
            f"- Region: {region}"
        )

    def _build_evaluation_prompt(self, ctx: str, niche: str, region: str) -> str:
        """Constrói prompt para avaliação LLM."""
        return (
            "You are a B2B prospecting expert evaluating leads for product/service fit.\n\n"
            "Analyze the lead data and evaluate in 3 dimensions:\n\n"
            "1. FIT SCORE (0-100):\n"
            "   - How well does this lead's company fit the target niche?\n"
            "   - Consider: industry, company size, business model, role in company\n"
            "   - 80-100: Perfect fit (high-priority)\n"
            "   - 60-79: Good fit (qualified)\n"
            "   - 40-59: Possible fit (marginal)\n"
            "   - 0-39: Poor fit (not qualified)\n\n"

            "2. INTENT SIGNALS (0-5 scale):\n"
            "   - Are there signals the company might be buying soon?\n"
            "   - Consider: hiring growth, recent funding, website mentions, tech stack changes\n"
            "   - 5: Strong signals (hiring, recent funding)\n"
            "   - 3: Moderate signals (website mentions product category)\n"
            "   - 1: Weak signals (no clear indicators)\n"
            "   - 0: No signals\n\n"

            "3. BUDGET INDICATOR (range):\n"
            "   - Estimate budget range based on company size & industry\n"
            "   - Options: 10k-50k, 50k-100k, 100k-500k, 500k+, unknown\n\n"

            "Return ONLY valid JSON:\n"
            "{\n"
            '  "fit_score": <0-100>,\n'
            '  "fit_score_reasoning": "<brief explanation>",\n'
            '  "intent_signals_level": <0-5>,\n'
            '  "intent_signals_evidence": ["evidence1", "evidence2"],\n'
            '  "budget_indicator": "<range>"\n'
            "}\n\n"

            f"{ctx}"
        )

    def _parse_llm_response(self, response_text: str) -> DiscoveryMatrixResult:
        """Parseia resposta JSON do LLM."""
        if not response_text:
            return self._default_result()
        try:
            # Extrair JSON da resposta (pode ter texto antes/depois)
            s = response_text.find("{")
            e = response_text.rfind("}") + 1

            if s == -1 or e <= s:
                log.warning("[discovery_matrix] Nenhum JSON encontrado na resposta")
                return self._default_result()

            json_str = response_text[s:e]
            data = json.loads(json_str)

            # Validar campos obrigatórios
            fit_score = int(data.get("fit_score", 50))
            fit_score = max(0, min(100, fit_score))  # Clamp 0-100

            intent_signals = int(data.get("intent_signals_level", 2))
            intent_signals = max(0, min(5, intent_signals))  # Clamp 0-5

            budget = data.get("budget_indicator", "10k-50k")
            evidence = data.get("intent_signals_evidence", [])
            reasoning = data.get("fit_score_reasoning", "")

            return DiscoveryMatrixResult(
                fit_score=fit_score,
                fit_score_reasoning=reasoning[:200],  # Limitar comprimento
                intent_signals_level=intent_signals,
                intent_signals_evidence=evidence if isinstance(evidence, list) else [],
                budget_indicator=budget,
                passed_minimum_threshold=(fit_score >= 60)
            )

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            log.warning(f"[discovery_matrix] Erro ao parsear JSON: {e}")
            return self._default_result()

    def _default_result(self) -> DiscoveryMatrixResult:
        """Resultado padrão (conservador) para erros."""
        return DiscoveryMatrixResult(
            fit_score=50,
            fit_score_reasoning="Parsing error, using default score",
            intent_signals_level=2,
            intent_signals_evidence=["unknown"],
            budget_indicator="10k-50k",
            passed_minimum_threshold=False
        )

    async def evaluate_batch(
        self,
        leads: List[Dict[str, Any]],
        niche: str,
        region: str,
        batch_size: int = 5
    ) -> Dict[int, DiscoveryMatrixResult]:
        """
        Avalia múltiplos leads em lotes (batch processing).

        Agrupa até 5 leads por chamada LLM para economizar tokens.

        Args:
            leads: Lista de leads (cada um deve ter 'lead_id')
            niche: Nicho alvo
            region: Região alvo
            batch_size: Quantos leads avaliar por LLM call

        Returns:
            Dict {lead_id: DiscoveryMatrixResult}
        """
        results = {}

        # Processar em batches
        for i in range(0, len(leads), batch_size):
            batch = leads[i:i + batch_size]

            log.info(f"[discovery_matrix] Processando batch de {len(batch)} leads")

            # Avaliar cada lead do batch individualmente
            # (batch LLM call seria mais complexo, mantendo simples por agora)
            for lead in batch:
                lead_id = lead.get("lead_id")
                try:
                    result = await self.evaluate_lead(lead, niche, region)
                    if lead_id:
                        results[lead_id] = result
                except Exception as e:
                    log.error(f"[discovery_matrix] Erro ao avaliar lead {lead_id}: {e}")
                    results[lead_id] = self._default_result()

        return results
