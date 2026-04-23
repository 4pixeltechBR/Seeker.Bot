"""
Seeker.Bot — Evidence Arbitrage
src/core/evidence/arbitrage.py

O diferencial epistemológico que nenhum agente no mercado tem.

Conceito: rodar a mesma query em 2-3 modelos com dados de treino
diferentes e mapear onde as respostas DIVERGEM. A divergência é
o sinal — é onde a incerteza real mora.

V2: ClaimComparator agora usa embedding similarity (Gemini Embed 2)
com fallback para Jaccard. Claims como "suporta tool calling" vs
"has function calling support" são corretamente matcheadas.
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum

from config.models import ModelConfig, ModelRouter, CognitiveRole, build_default_router
from src.core.utils import parse_llm_json
from src.providers.base import (
    BaseProvider,
    LLMRequest,
    LLMResponse,
    create_provider,
)

log = logging.getLogger("seeker.evidence.arbitrage")


# ─────────────────────────────────────────────────────────────────────
# TIPOS
# ─────────────────────────────────────────────────────────────────────

class AgreementLevel(str, Enum):
    CONSENSUS    = "consensus"
    MAJORITY     = "majority"
    SPLIT        = "split"
    CONTRADICTION = "contradiction"


class VerificationDepth(int, Enum):
    UNVERIFIED       = 0
    CORROBORATED     = 1
    PRIMARY_VERIFIED = 2
    EMPIRICALLY_TESTED = 3

    @property
    def confidence_multiplier(self) -> float:
        return {0: 0.4, 1: 0.7, 2: 0.9, 3: 1.0}[self.value]


@dataclass
class Claim:
    text: str
    source_model: str
    source_provider: str
    confidence: float = 0.5
    verification_depth: VerificationDepth = VerificationDepth.UNVERIFIED
    supporting_models: list[str] = field(default_factory=list)
    contradicting_models: list[str] = field(default_factory=list)

    @property
    def effective_confidence(self) -> float:
        return min(1.0, self.confidence * self.verification_depth.confidence_multiplier)

    @property
    def id(self) -> str:
        return hashlib.md5(self.text.encode()).hexdigest()[:12]


@dataclass
class ConflictZone:
    topic: str
    claims: list[Claim]
    agreement_level: AgreementLevel
    needs_primary_source: bool = True
    resolution: str | None = None


@dataclass
class ArbitrageResult:
    query: str
    consensus_claims: list[Claim] = field(default_factory=list)
    conflict_zones: list[ConflictZone] = field(default_factory=list)
    raw_responses: dict[str, LLMResponse] = field(default_factory=dict)
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0
    models_consulted: list[str] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return len(self.conflict_zones) > 0

    @property
    def confidence_summary(self) -> dict[str, float]:
        result = {}
        if self.consensus_claims:
            result["consensus"] = sum(
                c.effective_confidence for c in self.consensus_claims
            ) / len(self.consensus_claims)
        if self.conflict_zones:
            all_conflict_claims = [
                c for zone in self.conflict_zones for c in zone.claims
            ]
            if all_conflict_claims:
                result["conflicts"] = sum(
                    c.effective_confidence for c in all_conflict_claims
                ) / len(all_conflict_claims)
        return result

    def to_summary(self) -> str:
        lines = [f"## Arbitragem: {self.query[:80]}"]
        lines.append(f"Modelos: {', '.join(self.models_consulted)}")
        lines.append(f"Custo: ${self.total_cost_usd:.4f} | Latência: {self.total_latency_ms}ms")
        lines.append("")

        if self.consensus_claims:
            lines.append(f"### Consenso ({len(self.consensus_claims)} claims)")
            for claim in self.consensus_claims:
                lines.append(f"  ✅ [{claim.effective_confidence:.0%}] {claim.text}")
            lines.append("")

        if self.conflict_zones:
            lines.append(f"### Conflitos ({len(self.conflict_zones)} zonas)")
            for zone in self.conflict_zones:
                resolved = " ✅" if zone.resolution else ""
                lines.append(f"  ⚠️ {zone.topic} [{zone.agreement_level.value}]{resolved}")
                for claim in zone.claims:
                    lines.append(f"    - [{claim.source_provider}] {claim.text}")
                if zone.resolution:
                    lines.append(f"    → {zone.resolution}")
                elif zone.needs_primary_source:
                    lines.append("    → Requer fonte primária para desempate")
            lines.append("")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# PROMPT DE EXTRAÇÃO DE CLAIMS
# ─────────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """Analise esta pergunta e responda com fatos verificáveis.

PERGUNTA: {query}

Responda APENAS em JSON válido, sem markdown. Formato:
{{
  "claims": [
    {{
      "text": "afirmação factual específica e verificável",
      "confidence": 0.85,
      "category": "categoria temática curta"
    }}
  ]
}}

REGRAS:
- Cada claim deve ser uma afirmação ATÔMICA (um fato por claim)
- Inclua a confiança que você tem na afirmação (0.0 a 1.0)
- Agrupe claims em categorias temáticas
- Máximo 10 claims — priorize os mais relevantes
- Se não tem certeza de algo, diga e dê confiança baixa
- NÃO invente dados — se não sabe, omita
"""


# ─────────────────────────────────────────────────────────────────────
# COMPARADOR DE CLAIMS V2 — Embedding + Jaccard fallback
# ─────────────────────────────────────────────────────────────────────

class ClaimComparator:
    """
    V2: Embedding similarity via GeminiEmbedder com fallback Jaccard.
    
    ANTES (V1 Jaccard):
      "API suporta tool calling" vs "Model has function calling support"
      → 0.08 → NÃO MATCH → falso conflito
    
    DEPOIS (V2 Embedding):
      → 0.89 → MATCH → consenso correto
    
    Custo: ~30 embed calls por arbitragem (10 claims × 3 modelos).
    Com 100 RPM no Gemini Embed, consome 30/100 slots. Aceitável.
    """

    def __init__(
        self,
        embedder=None,
        text_threshold: float = 0.45,
        embed_threshold: float = 0.70,
    ):
        self.embedder = embedder
        self.text_threshold = text_threshold
        self.embed_threshold = embed_threshold

    async def find_matches(
        self,
        claims_a: list[Claim],
        claims_b: list[Claim],
    ) -> list[tuple[Claim, Claim, float]]:
        """
        Encontra pares semânticos entre dois conjuntos de claims.
        Batch embeddings pra eficiência (1 call por texto, não por par).
        """
        threshold = self.embed_threshold if self.embedder else self.text_threshold

        # Batch embed para reduzir round-trips
        vecs_a = None
        vecs_b = None
        if self.embedder:
            try:
                texts_a = [c.text for c in claims_a]
                texts_b = [c.text for c in claims_b]
                vecs_a = await self.embedder.embed_batch(texts_a)
                vecs_b = await self.embedder.embed_batch(texts_b)
            except Exception as e:
                log.warning(f"[comparator] Embedding batch falhou, usando Jaccard: {e}")
                vecs_a = vecs_b = None

        matches = []
        for i, ca in enumerate(claims_a):
            best_match = None
            best_score = 0.0

            for j, cb in enumerate(claims_b):
                # Tenta embedding primeiro
                if vecs_a and vecs_b and vecs_a[i] and vecs_b[j]:
                    from src.core.memory.embeddings import GeminiEmbedder
                    score = GeminiEmbedder.cosine_similarity(vecs_a[i], vecs_b[j])
                else:
                    score = self._jaccard_similarity(ca.text, cb.text)

                if score > best_score:
                    best_score = score
                    best_match = cb

            if best_match and best_score >= threshold:
                matches.append((ca, best_match, best_score))

        return matches

    def find_unmatched(
        self,
        claims: list[Claim],
        matched_ids: set[str],
    ) -> list[Claim]:
        """Claims que não encontraram par em outro modelo."""
        return [c for c in claims if c.id not in matched_ids]

    def _jaccard_similarity(self, text_a: str, text_b: str) -> float:
        """Fallback: Jaccard sobre tokens normalizados."""
        tokens_a = self._tokenize(text_a)
        tokens_b = self._tokenize(text_b)
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)

    def _tokenize(self, text: str) -> set[str]:
        words = text.lower().split()
        stopwords = {
            "o", "a", "os", "as", "de", "do", "da", "dos", "das",
            "em", "no", "na", "um", "uma", "e", "é", "que", "para",
            "com", "por", "the", "is", "of", "and", "to", "in", "a",
            "for", "on", "with", "at", "an", "it", "its",
        }
        return {w for w in words if len(w) > 2 and w not in stopwords}


# ─────────────────────────────────────────────────────────────────────
# O ARBITRADOR
# ─────────────────────────────────────────────────────────────────────

class EvidenceArbitrage:
    """
    Triangulação epistemológica automatizada.
    
    Fluxo:
    1. Recebe uma query
    2. Dispara em paralelo para N modelos (providers diferentes)
    3. Extrai claims atômicas de cada resposta
    4. Compara claims entre modelos (embedding V2)
    5. Classifica: consenso / maioria / split / contradição
    6. Retorna ArbitrageResult com zonas de conflito marcadas
    """

    def __init__(
        self,
        router: ModelRouter,
        api_keys: dict[str, str],
        min_models: int = 2,
        similarity_threshold: float = 0.45,
        embedder=None,
    ):
        self.router = router
        self.api_keys = api_keys
        self.min_models = min_models
        self.comparator = ClaimComparator(
            embedder=embedder,
            text_threshold=similarity_threshold,
        )

    async def arbitrate(self, query: str) -> ArbitrageResult:
        """Executa a arbitragem completa."""
        start = time.perf_counter()

        models = self._select_models()
        if len(models) < self.min_models:
            raise RuntimeError(
                f"Precisa de no mínimo {self.min_models} providers, "
                f"mas só {len(models)} disponíveis"
            )

        log.info(
            f"[arbitrage] Query: '{query[:60]}...' | "
            f"Modelos: {[m.display_name for m in models]}"
        )

        # Dispara em paralelo
        tasks = [self._query_model(model, query) for model in models]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Processa resultados
        model_claims: dict[str, list[Claim]] = {}
        raw_responses: dict[str, LLMResponse] = {}
        total_cost = 0.0

        for model, result in zip(models, results):
            if isinstance(result, Exception):
                log.warning(f"[arbitrage] {model.display_name} falhou: {result}")
                continue
            response, claims = result
            model_claims[model.display_name] = claims
            raw_responses[model.display_name] = response
            total_cost += response.cost_usd

        if len(model_claims) < self.min_models:
            raise RuntimeError(
                f"Apenas {len(model_claims)} modelos responderam, "
                f"mínimo necessário: {self.min_models}"
            )

        # Compara claims (ASYNC agora — embeddings)
        consensus, conflicts = await self._analyze_agreement(model_claims)

        total_latency = int((time.perf_counter() - start) * 1000)

        result = ArbitrageResult(
            query=query,
            consensus_claims=consensus,
            conflict_zones=conflicts,
            raw_responses=raw_responses,
            total_cost_usd=total_cost,
            total_latency_ms=total_latency,
            models_consulted=list(model_claims.keys()),
        )

        log.info(
            f"[arbitrage] Completo | "
            f"{len(consensus)} consensos, {len(conflicts)} conflitos | "
            f"${total_cost:.4f} | {total_latency}ms"
        )

        return result

    def _select_models(self) -> list[ModelConfig]:
        return self.router.get_all_for_arbitrage()[:3]

    async def _query_model(
        self,
        model: ModelConfig,
        query: str,
    ) -> tuple[LLMResponse, list[Claim]]:
        provider = create_provider(model, self.api_keys)
        try:
            request = LLMRequest(
                messages=[{
                    "role": "user",
                    "content": EXTRACTION_PROMPT.format(query=query),
                }],
                max_tokens=2000,
                temperature=0.0,
                response_format="json",
            )
            response = await provider.complete(request)
            claims = self._parse_claims(response, model)
            return response, claims
        finally:
            await provider.close()

    def _parse_claims(
        self,
        response: LLMResponse,
        model: ModelConfig,
    ) -> list[Claim]:
        try:
            data = parse_llm_json(response.text)
            raw_claims = data.get("claims", [])
            claims = []
            for rc in raw_claims:
                claim = Claim(
                    text=rc.get("text", ""),
                    source_model=model.model_id,
                    source_provider=model.provider,
                    confidence=float(rc.get("confidence", 0.5)),
                )
                if claim.text:
                    claims.append(claim)
            return claims
        except (ValueError, KeyError, TypeError) as e:
            log.warning(f"[arbitrage] Falha ao parsear claims de {model.display_name}: {e}")
            return [Claim(
                text=response.text[:500],
                source_model=model.model_id,
                source_provider=model.provider,
                confidence=0.3,
            )]

    async def _analyze_agreement(
        self,
        model_claims: dict[str, list[Claim]],
    ) -> tuple[list[Claim], list[ConflictZone]]:
        """
        Compara claims entre todos os pares de modelos.
        ASYNC agora — embedding similarity usa API.
        """
        model_names = list(model_claims.keys())
        if len(model_names) < 2:
            claims = list(model_claims.values())[0] if model_claims else []
            return claims, []

        # Encontra matches entre pares
        all_claims: dict[str, Claim] = {}
        matched_ids: set[str] = set()

        for i in range(len(model_names)):
            for j in range(i + 1, len(model_names)):
                name_a, name_b = model_names[i], model_names[j]
                claims_a = model_claims[name_a]
                claims_b = model_claims[name_b]

                # ASYNC — embeddings
                matches = await self.comparator.find_matches(claims_a, claims_b)

                for claim_a, claim_b, score in matches:
                    matched_ids.add(claim_a.id)
                    matched_ids.add(claim_b.id)

                    if claim_a.id not in all_claims:
                        all_claims[claim_a.id] = Claim(
                            text=claim_a.text,
                            source_model=claim_a.source_model,
                            source_provider=claim_a.source_provider,
                            confidence=claim_a.confidence,
                            verification_depth=VerificationDepth.CORROBORATED,
                            supporting_models=[name_a],
                        )

                    merged = all_claims[claim_a.id]
                    if name_b not in merged.supporting_models:
                        merged.supporting_models.append(name_b)
                    merged.confidence = min(
                        1.0,
                        max(claim_a.confidence, claim_b.confidence) * 1.15,
                    )

        # Separa consenso de conflito
        consensus = []
        conflict_claims_by_category: dict[str, list[Claim]] = {}

        for claim in all_claims.values():
            if len(claim.supporting_models) >= len(model_names) - 1:
                claim.verification_depth = VerificationDepth.CORROBORATED
                consensus.append(claim)

        for name in model_names:
            unmatched = self.comparator.find_unmatched(
                model_claims[name], matched_ids
            )
            for claim in unmatched:
                category = self._extract_topic(claim.text)
                if category not in conflict_claims_by_category:
                    conflict_claims_by_category[category] = []
                conflict_claims_by_category[category].append(claim)

        conflicts = []
        for topic, claims in conflict_claims_by_category.items():
            providers = {c.source_provider for c in claims}
            if len(providers) > 1:
                level = AgreementLevel.CONTRADICTION
            elif len(claims) > 1:
                level = AgreementLevel.SPLIT
            else:
                level = AgreementLevel.MAJORITY
                for c in claims:
                    c.confidence *= 0.6
                    consensus.append(c)
                continue

            conflicts.append(ConflictZone(
                topic=topic,
                claims=claims,
                agreement_level=level,
                needs_primary_source=level in (
                    AgreementLevel.CONTRADICTION,
                    AgreementLevel.SPLIT,
                ),
            ))

        return consensus, conflicts

    def _extract_topic(self, text: str) -> str:
        words = [
            w for w in text.lower().split()
            if len(w) > 3 and w not in {
                "para", "como", "quando", "onde", "qual",
                "este", "esta", "esse", "essa", "mais",
                "that", "this", "with", "from", "have",
            }
        ]
        return " ".join(words[:4]) if words else "geral"
