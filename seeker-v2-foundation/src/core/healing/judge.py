"""
Seeker.Bot — Verification Gate
src/core/healing/judge.py

O juiz separado que valida evidências.

Princípio: o mesmo modelo que produz erros não consegue detectá-los.
O Verification Gate usa um modelo DIFERENTE do executor pra validar
claims antes da resposta sair pro usuário.

Regras:
  - O juiz SÓ LÊ, nunca modifica a resposta
  - O juiz roda num modelo diferente do que gerou a resposta
  - O juiz retorna: veredicto + claims duvidosas + confiança geral
  - Se a confiança geral < threshold, anexa aviso na resposta

Papel JUDGE no roteamento:
  Primário: Gemini 3 Flash (dataset Google)
  Fallback: Mistral (dataset europeu), Groq (dataset Meta)
  Nunca: NVIDIA Nemotron (é o executor padrão)
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum

from config.models import CognitiveRole, ModelRouter
from src.providers.base import LLMRequest, invoke_with_fallback

log = logging.getLogger("seeker.healing.judge")


class Verdict(str, Enum):
    APPROVED     = "approved"      # Resposta confiável, sem ressalvas
    CAUTIOUS     = "cautious"      # Maioria OK, mas tem pontos a verificar
    FLAGGED      = "flagged"       # Problemas significativos encontrados
    UNRELIABLE   = "unreliable"    # Resposta não deveria ser enviada como está


@dataclass
class FlaggedClaim:
    """Uma claim que o juiz considerou duvidosa."""
    claim: str
    issue: str           # O que está errado ou duvidoso
    severity: str        # "low", "medium", "high"
    suggestion: str      # O que fazer pra verificar


@dataclass
class JudgeVerdict:
    """Resultado completo da verificação."""
    verdict: Verdict
    confidence: float                               # 0.0-1.0
    flagged_claims: list[FlaggedClaim] = field(default_factory=list)
    reasoning: str = ""                             # Por que o juiz decidiu isso
    model_used: str = ""                            # Qual modelo julgou

    @property
    def has_flags(self) -> bool:
        return len(self.flagged_claims) > 0

    def to_warning(self) -> str:
        """Formata aviso para anexar à resposta se necessário."""
        if self.verdict == Verdict.APPROVED:
            return ""

        lines = []
        if self.verdict == Verdict.CAUTIOUS:
            lines.append("⚠️ **Verificação:** alguns pontos merecem checagem adicional:")
        elif self.verdict == Verdict.FLAGGED:
            lines.append("⚠️ **Atenção:** o verificador independente identificou problemas:")
        elif self.verdict == Verdict.UNRELIABLE:
            lines.append("🔴 **Aviso:** confiabilidade baixa nesta resposta:")

        for fc in self.flagged_claims:
            severity_icon = {"low": "·", "medium": "⚠️", "high": "🔴"}.get(fc.severity, "·")
            lines.append(f"  {severity_icon} {fc.issue}")

        if self.reasoning:
            lines.append(f"\n_{self.reasoning}_")

        return "\n".join(lines)

    def to_footer(self) -> str:
        """Badge curto pro rodapé da resposta."""
        icons = {
            Verdict.APPROVED: "✅",
            Verdict.CAUTIOUS: "⚠️",
            Verdict.FLAGGED: "⚠️⚠️",
            Verdict.UNRELIABLE: "🔴",
        }
        return f"{icons.get(self.verdict, '')} {self.confidence:.0%} confiança"


JUDGE_PROMPT = """Você é um verificador independente de informações. Sua função é
avaliar a qualidade e confiabilidade de uma resposta gerada por outro modelo de IA.

Você SÓ AVALIA — nunca modifica, nunca reescreve.

━━━ PERGUNTA ORIGINAL DO USUÁRIO ━━━
{user_input}

━━━ RESPOSTA GERADA (por outro modelo) ━━━
{response}

━━━ EVIDÊNCIAS DISPONÍVEIS ━━━
{evidence_context}

━━━ INSTRUÇÕES ━━━

Avalie a resposta nos seguintes critérios:
1. FACTICIDADE — as afirmações são verificáveis? Há dados inventados?
2. CONSISTÊNCIA — a resposta se contradiz internamente?
3. COMPLETUDE — há lacunas importantes que foram ignoradas?
4. VIÉS — a resposta favorece uma posição sem justificativa?
5. FONTES — claims são atribuídas ou são afirmações soltas?

Retorne APENAS JSON válido, sem markdown:
{{
  "verdict": "approved|cautious|flagged|unreliable",
  "confidence": 0.85,
  "flagged_claims": [
    {{
      "claim": "a afirmação específica que é duvidosa",
      "issue": "por que é duvidosa — em 1 frase",
      "severity": "low|medium|high",
      "suggestion": "como verificar — em 1 frase"
    }}
  ],
  "reasoning": "resumo de 1-2 frases da avaliação geral"
}}

REGRAS:
- Se a resposta é sólida e bem fundamentada: verdict "approved", confidence 0.8+
- Se tem 1-2 pontos menores: "cautious", confidence 0.6-0.8
- Se tem afirmações não verificáveis ou dados que parecem inventados: "flagged", 0.4-0.6
- Se a resposta é fundamentalmente problemática: "unreliable", <0.4
- flagged_claims pode ser lista vazia se tudo estiver OK
- Seja rigoroso mas justo — não flagge opiniões como erros factuais
- Considere as evidências disponíveis ao julgar
"""


class VerificationGate:
    """
    Juiz independente que valida respostas antes de enviar ao usuário.
    
    Uso:
        gate = VerificationGate(router, api_keys)
        verdict = await gate.verify(user_input, response_text, evidence)
        if verdict.has_flags:
            response_text += "\n\n" + verdict.to_warning()
    """

    def __init__(
        self,
        router: ModelRouter,
        api_keys: dict[str, str],
        confidence_threshold: float = 0.6,
    ):
        self.router = router
        self.api_keys = api_keys
        self.threshold = confidence_threshold

    async def verify(
        self,
        user_input: str,
        response_text: str,
        evidence_context: str = "",
    ) -> JudgeVerdict:
        """
        Verifica uma resposta usando modelo independente.
        
        O modelo JUDGE é propositalmente diferente do executor —
        diversidade de dados de treino é o que dá valor à verificação.
        """
        try:
            # Trunca pra não explodir o contexto
            response_truncated = response_text[:3000]
            evidence_truncated = evidence_context[:2000] if evidence_context else "Sem evidências adicionais."

            result = await invoke_with_fallback(
                role=CognitiveRole.JUDGE,
                request=LLMRequest(
                    messages=[{
                        "role": "user",
                        "content": JUDGE_PROMPT.format(
                            user_input=user_input[:500],
                            response=response_truncated,
                            evidence_context=evidence_truncated,
                        ),
                    }],
                    max_tokens=800,
                    temperature=0.0,
                    response_format="json",
                ),
                router=self.router,
                api_keys=self.api_keys,
            )

            verdict = self._parse_verdict(result.text)
            verdict.model_used = result.model

            log.info(
                f"[judge] Veredicto: {verdict.verdict.value} | "
                f"Confiança: {verdict.confidence:.0%} | "
                f"Flags: {len(verdict.flagged_claims)} | "
                f"Modelo: {verdict.model_used}"
            )

            return verdict

        except Exception as e:
            log.warning(f"[judge] Verificação falhou: {e}")
            # Fallback: aprova com confiança moderada
            return JudgeVerdict(
                verdict=Verdict.CAUTIOUS,
                confidence=0.6,
                reasoning=f"Verificação indisponível: {str(e)[:100]}",
            )

    def _parse_verdict(self, raw: str) -> JudgeVerdict:
        """Parseia o JSON do juiz."""
        try:
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]

            data = json.loads(text.strip())

            # Parse flagged claims
            flags = []
            for fc in data.get("flagged_claims", []):
                if isinstance(fc, dict) and fc.get("claim"):
                    flags.append(FlaggedClaim(
                        claim=fc.get("claim", "")[:200],
                        issue=fc.get("issue", "")[:200],
                        severity=fc.get("severity", "low"),
                        suggestion=fc.get("suggestion", "")[:200],
                    ))

            # Parse verdict
            verdict_str = data.get("verdict", "cautious").lower()
            try:
                verdict = Verdict(verdict_str)
            except ValueError:
                verdict = Verdict.CAUTIOUS

            return JudgeVerdict(
                verdict=verdict,
                confidence=min(1.0, max(0.0, float(data.get("confidence", 0.5)))),
                flagged_claims=flags,
                reasoning=data.get("reasoning", "")[:300],
                model_used="",
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            log.warning(f"[judge] Falha ao parsear veredicto: {e}")
            return JudgeVerdict(
                verdict=Verdict.CAUTIOUS,
                confidence=0.5,
                reasoning=f"Parse do veredicto falhou: {str(e)[:100]}",
            )

    def should_warn(self, verdict: JudgeVerdict) -> bool:
        """Decide se deve anexar aviso na resposta."""
        return (
            verdict.verdict != Verdict.APPROVED
            or verdict.confidence < self.threshold
        )
