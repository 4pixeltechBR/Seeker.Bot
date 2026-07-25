"""promptograph.validator — Valida qualidade de system prompts.

Port de validators/quality.py do projeto Promptograph (MIT).
13 boas praticas + 6 red flags extraidas de 5.317 prompts de producao.
Zero dependencias (apenas stdlib + re).
"""

from __future__ import annotations

import re

__all__ = ["validate_prompt", "GOOD_PRACTICES", "RED_FLAGS"]


GOOD_PRACTICES: dict[str, dict] = {
    "identity_clarity": {
        "weight": 15,
        "description": "Define claramente a identidade/persona (ex: 'You are X, built by Y')",
        "check": lambda c: bool(
            re.search(r"You are\s+\w", c)
            or re.search(r"Você é\s+\w", c)
            or re.search(r"I am\s+\w", c)
            or re.search(r"identif", c, re.IGNORECASE)
        ),
    },
    "knowledge_cutoff": {
        "weight": 5,
        "description": "Menciona knowledge cutoff ou data atual",
        "check": lambda c: bool(
            re.search(
                r"(knowledge cutoff|cutoff|knowledge_cutoff|data atual|current date)",
                c,
                re.IGNORECASE,
            )
        ),
    },
    "tone_guidelines": {
        "weight": 10,
        "description": "Define tom de voz (warm, professional, concise, etc)",
        "check": lambda c: bool(
            re.search(
                r"\b(warm|professional|concise|friendly|empathetic|kind|polite|neutral|objective)\b",
                c,
                re.IGNORECASE,
            )
        ),
    },
    "formatting_rules": {
        "weight": 8,
        "description": "Especifica regras de formatacao (bullets, headers, listas, markdown)",
        "check": lambda c: bool(
            re.search(
                r"\b(bullet|list|markdown|header|heading|format|prose|paragraph)\b",
                c,
                re.IGNORECASE,
            )
        ),
    },
    "refusals_handling": {
        "weight": 10,
        "description": "Define quando/como recusar pedidos",
        "check": lambda c: bool(
            re.search(
                r"\b(refuse|decline|reject|cannot|can'?t|won'?t|not (provide|generate|create))\b",
                c,
                re.IGNORECASE,
            )
        ),
    },
    "safety_rules": {
        "weight": 10,
        "description": "Inclui regras de seguranca (child safety, weapons, drugs, etc)",
        "check": lambda c: bool(
            re.search(
                r"\b(safet|harm|child|minor|weapon|drug|illegal|illicit|exploit|malware|violent)\b",
                c,
                re.IGNORECASE,
            )
        ),
    },
    "tool_usage": {
        "weight": 8,
        "description": "Documenta tools disponiveis e quando usar",
        "check": lambda c: bool(
            re.search(r"\b(tool|function call|tool_use|json|mcp|plugin)\b", c, re.IGNORECASE)
        ),
    },
    "examples_section": {
        "weight": 10,
        "description": "Inclui exemplos few-shot (good vs bad responses)",
        "check": lambda c: bool(
            re.search(r"\b(example|few-shot|demonstration)\b", c, re.IGNORECASE)
        ),
    },
    "memory_or_context": {
        "weight": 6,
        "description": "Define como gerenciar contexto/memoria entre turns",
        "check": lambda c: bool(
            re.search(r"\b(memory|context|conversation history|previous)\b", c, re.IGNORECASE)
        ),
    },
    "structured_tags": {
        "weight": 5,
        "description": "Usa tags XML/estruturadas para organizar secoes",
        "check": lambda c: bool(re.search(r"<\w+>", c)),
    },
    "citation_or_sources": {
        "weight": 5,
        "description": "Menciona regras de citacao/fontes",
        "check": lambda c: bool(
            re.search(r"\b(cite|citation|source|reference|attribut)\b", c, re.IGNORECASE)
        ),
    },
    "limits_and_boundaries": {
        "weight": 5,
        "description": "Define limites claros (o que NAO fazer)",
        "check": lambda c: bool(
            re.search(
                r"\b(never|do not|don'?t|avoid|shouldn'?t|must not|prohibit)\b",
                c,
                re.IGNORECASE,
            )
        ),
    },
    "length_appropriateness": {
        "weight": 3,
        "description": "Tamanho razoavel (nem muito curto nem excessivo)",
        "check": lambda c: 200 <= len(c) <= 200_000,
    },
}

RED_FLAGS: dict[str, dict] = {
    "vague_identity": {
        "description": "Identidade vaga ou ausente",
        "check": lambda c: not re.search(r"You are\s+\w", c)
        and not re.search(r"Você é\s+\w", c),
    },
    "instruction_contradiction": {
        "description": "Possiveis contradicoes ('always' + 'never' no mesmo contexto)",
        "check": lambda c: len(re.findall(r"\b(always|never)\b", c, re.IGNORECASE)) > 20,
    },
    "jailbreak_vulnerability": {
        "description": "Nao menciona protecao contra prompt injection",
        "check": lambda c: not re.search(
            r"\b(prompt injection|jailbreak|adversarial|ignore previous|ignore the above)\b",
            c,
            re.IGNORECASE,
        ),
    },
    "copyright_missing": {
        "description": "Nao menciona regras de copyright",
        "check": lambda c: not re.search(r"\b(copyright|fair use|reproduce|trademark)\b", c, re.IGNORECASE),
    },
    "too_short": {
        "description": "Muito curto para ser um system prompt util",
        "check": lambda c: len(c) < 200,
    },
    "too_long_warning": {
        "description": "Pode ser excessivamente longo (>100k tokens) - considere trim",
        "check": lambda c: len(c) > 400_000,
    },
}

_GRADE_BANDS = (
    (90, "A+", "Excelente - segue as melhores praticas dos principais modelos."),
    (80, "A", "Muito bom - segue as melhores praticas observadas."),
    (70, "B", "Bom - alguns pontos podem ser melhorados."),
    (60, "C", "Razoavel - vale revisar as secoes faltantes."),
    (50, "D", "Fraco - varios pontos criticos faltando."),
    (0, "F", "Muito fraco - considere reescrever seguindo os padroes de referencia."),
)


def _grade_for(score_pct: float) -> tuple[str, str]:
    for threshold, grade, verdict in _GRADE_BANDS:
        if score_pct >= threshold:
            return grade, verdict
    return "F", "Muito fraco."


def validate_prompt(content: str) -> dict:
    """Valida um system prompt e retorna score + detalhes.

    Returns:
        dict com keys: score, grade, passed, failed, warnings, summary, stats
    """
    if not content or len(content.strip()) < 50:
        return {
            "score": 0,
            "grade": "F",
            "passed": [],
            "failed": [{"key": "too_short", "description": "Muito curto"}],
            "warnings": [{"key": "too_short", "description": "Prompt vazio ou invalido"}],
            "summary": "Conteudo insuficiente para analise.",
            "stats": {"chars": len(content), "words": 0, "lines": 0, "tokens_estimate": 0},
        }

    passed: list[dict] = []
    failed: list[dict] = []
    total_score = 0
    total_weight = sum(p["weight"] for p in GOOD_PRACTICES.values())

    for key, practice in GOOD_PRACTICES.items():
        if practice["check"](content):
            passed.append({"key": key, "description": practice["description"]})
            total_score += practice["weight"]
        else:
            failed.append({"key": key, "description": practice["description"]})

    warnings: list[dict] = []
    for key, flag in RED_FLAGS.items():
        if flag["check"](content):
            warnings.append({"key": key, "description": flag["description"]})

    score_pct = round((total_score / total_weight) * 100, 1)
    grade, verdict = _grade_for(score_pct)

    return {
        "score": score_pct,
        "grade": grade,
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "summary": verdict,
        "stats": {
            "chars": len(content),
            "words": len(content.split()),
            "lines": content.count("\n") + 1,
            "tokens_estimate": len(content) // 4,
        },
    }
