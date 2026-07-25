"""knowledge_vault.detectors — Heuristic content-class detector for vault notes.

Aplica regexes do Promptograph (extracted de parser.py original) ao texto extraido
antes do LLM rodar. Retorna hints que podem:
  - Substituir `source_type` quando ha confianca alta (ex: documento = prompt)
  - Setar `extra_meta['detected_content_class']` para o LLM aproveitar
  - Apendar company/model/tags detectados em `extra_meta['detected_tags']`

Classes detectadas (por confianca):
  - 'prompt'          : system prompt de IA (Claude, GPT, Gemini, etc.)
  - 'manual'          : manual tecnico / documentacao
  - 'contract'        : contrato juridico
  - 'tech_doc'        : doc tecnico (API, README, etc.)
  - 'general'         : fallback - nada detectado com confianca

Confianca: score 0-1. Acima de 0.6 substitui source_type. Caso contrario so hint.

Baseado em regexes extraidas de E:\\Skills\\promptograph\\promptograph\\generator\\parser.py (MIT).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

__all__ = ["detect_content_class", "ContentClass", "COMPANY_PATTERNS", "MODEL_PATTERNS"]


# ── Padroes extraidos de parser.py (Promptograph MIT) ─────────────────

COMPANY_PATTERNS: dict[str, list[str]] = {
    "Anthropic": ["Anthropic", "anthropic"],
    "OpenAI": ["OpenAI", "openai", "ChatGPT", "codex", "Codex"],
    "Google": ["Google", "google", "Gemini", "gemini", "Jules", "NotebookLM"],
    "xAI": ["xAI", "xai", "Grok", "grok"],
    "Perplexity": ["Perplexity", "perplexity"],
    "Microsoft": ["Microsoft", "microsoft", "Copilot", "copilot"],
    "Meta": ["Meta", "meta", "Llama", "llama"],
    "Mistral": ["Mistral", "mistral", "Mixtral"],
    "DeepSeek": ["DeepSeek", "deepseek"],
    "Alibaba": ["Alibaba", "Qwen", "qwen", "Tongyi"],
    "Moonshot": ["Moonshot", "Kimi", "kimi"],
    "Zhipu": ["Zhipu", "GLM", "Z.AI", "z.ai"],
    "Cursor": ["Cursor", "cursor"],
    "Devin": ["Devin", "devin"],
    "Replit": ["Replit", "replit"],
    "Windsurf": ["Windsurf", "windsurf"],
    "Manus": ["Manus", "manus"],
    "Lovable": ["Lovable", "lovable"],
    "Notion": ["Notion", "notion"],
    "Brave": ["Brave", "brave"],
    "Discord": ["Discord", "discord", "Clyde"],
}

MODEL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"claude[- ]?(fable|mythos|opus|sonnet|haiku)[\s-]*(\d+(\.\d+)*)", re.IGNORECASE), "claude"),
    (re.compile(r"gpt[- ]?(\d+(\.\d+)*)(\s+(thinking|instant|codex))?", re.IGNORECASE), "gpt"),
    (re.compile(r"gemini[\s-]*(\d+(\.\d+)*)\s*(pro|flash|ultra)?", re.IGNORECASE), "gemini"),
    (re.compile(r"grok[\s-]*(\d+(\.\d+)*)", re.IGNORECASE), "grok"),
    (re.compile(r"\bo(\d+)(-mini|-pro)?\b", re.IGNORECASE), "o-series"),
    (re.compile(r"deepseek[\s-]*(v?\d+(\.\d+)*)?\s*(r\d+)?", re.IGNORECASE), "deepseek"),
    (re.compile(r"qwen[\s-]*(\d+(\.\d+)*)?", re.IGNORECASE), "qwen"),
    (re.compile(r"kimi[\s-]*(k\d+(\.\d+)*)?", re.IGNORECASE), "kimi"),
    (re.compile(r"\bglm[\s-]*(\d+(\.\d+)*)?\b", re.IGNORECASE), "glm"),
    (re.compile(r"mistral[\s-]*(\w+)?", re.IGNORECASE), "mistral"),
    (re.compile(r"llama[\s-]*(\d+(\.\d+)*)?", re.IGNORECASE), "llama"),
    (re.compile(r"mixtral[\s-]*(\w+)?", re.IGNORECASE), "mixtral"),
]

XML_TAGS_RE = re.compile(r"<(\w[\w\-]*)>")

TOOL_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(bash|terminal|shell)\b", re.IGNORECASE),
    re.compile(r"\b(search|web_search|fetch)\b", re.IGNORECASE),
    re.compile(r"\b(file_read|file_write|read_file|write_file)\b", re.IGNORECASE),
    re.compile(r"\b(memory|recall|remember)\b", re.IGNORECASE),
    re.compile(r"\b(calculator|math)\b", re.IGNORECASE),
    re.compile(r"\b(image_gen|image_generation|generate_image)\b", re.IGNORECASE),
    re.compile(r"\b(code_execution|code_exec|interpreter)\b", re.IGNORECASE),
    re.compile(r"\b(browser|navigate|click)\b", re.IGNORECASE),
    re.compile(r"\b(database|sql)\b", re.IGNORECASE),
    re.compile(r"\b(calendar|email|contact)\b", re.IGNORECASE),
    re.compile(r"\b(mcp|MCP)\b"),
]

# Persona: "You are X..." / "Você é X..."
PERSONA_RES = [
    re.compile(r"You are\s+([^\.\n]{10,150})"),
    re.compile(r"Você é\s+([^\.\n]{10,150})"),
    re.compile(r"I am\s+([^\.\n]{10,150})"),
]

# Indicadores fortes de que o conteudo É um system prompt
PROMPT_STRONG_SIGNALS = [
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"\bYou are\s+\w+,\s+(an|a)\s+", re.IGNORECASE),
    re.compile(r"\bVocê é\s+\w+,\s+(um|uma)\s+", re.IGNORECASE),
    re.compile(r"\bKnowledge cutoff\b", re.IGNORECASE),
    re.compile(r"\bknowledge_cutoff\b", re.IGNORECASE),
    re.compile(r"<anthropic_reminders>", re.IGNORECASE),
    re.compile(r"<tool_use|<example|<instructions?", re.IGNORECASE),
    re.compile(r"\b(refuse|decline).*(request|pedido)\b", re.IGNORECASE),
]

# Indicadores de manual tecnico
MANUAL_SIGNALS = [
    re.compile(r"\b manual \b", re.IGNORECASE),
    re.compile(r"\bdocumentação\b|\bdocumentacao\b", re.IGNORECASE),
    re.compile(r"\bguia\b", re.IGNORECASE),
    re.compile(r"\bhow\s*to\b|\bcomo\s+(fazer|usar|configurar)", re.IGNORECASE),
    re.compile(r"\bpasso\s+a\s*passo\b", re.IGNORECASE),
    re.compile(r"\b(step|etapa)\s*\d+", re.IGNORECASE),
]

# Contrato juridico
CONTRACT_SIGNALS = [
    re.compile(r"\bcontrat(o|ante)\b", re.IGNORECASE),
    re.compile(r"\bclausula\b", re.IGNORECASE),
    re.compile(r"\bCONTRATANTE\b", re.IGNORECASE),
    re.compile(r"\bCONTRATADO\b", re.IGNORECASE),
    re.compile(r"\b(pleno\s*acordo| trustees?)\b", re.IGNORECASE),
    re.compile(r"\bforo\s+da\s+comarca\b", re.IGNORECASE),
]

# Tech doc / API
TECH_DOC_SIGNALS = [
    re.compile(r"^#{1,4}\s+(API|Endpoints?|Usage|Installation)", re.MULTILINE),
    re.compile(r"```(?:python|javascript|bash|json)", re.IGNORECASE),
    re.compile(r"\bnpm\s+install\b|\bpip\s+install\b", re.IGNORECASE),
    re.compile(r"POST\s+/api/\w+|GET\s+/api/\w+", re.IGNORECASE),
    re.compile(r"```http\b"),  # HTTP request blocks
]


def _count_matches(text: str, patterns: list[re.Pattern]) -> int:
    return sum(len(p.findall(text)) for p in patterns)


def _detect_company(text: str) -> str | None:
    """Detecta empresa mencionada no texto."""
    head = text[:2000]
    for company, patterns in COMPANY_PATTERNS.items():
        for p in patterns:
            if p in head:
                return company
    return None


def _detect_model(text: str) -> str | None:
    """Detecta modelo citado."""
    head = text[:500]
    for pattern, _ in MODEL_PATTERNS:
        m = pattern.search(head)
        if m:
            return m.group(0).strip()
    return None


def _detect_persona(text: str) -> str | None:
    for p in PERSONA_RES:
        m = p.search(text[:1000])
        if m:
            return m.group(1).strip()[:120]
    return None


def _detect_tools(text: str) -> list[str]:
    found = []
    for p in TOOL_PATTERNS:
        if p.search(text[:5000]):
            name = p.pattern.replace(r"\b", "").replace(r"\s", "_").lower()
            found.append(name)
    return found


def _detect_xml_tags(text: str) -> list[str]:
    return sorted(set(XML_TAGS_RE.findall(text[:5000])))


class ContentClass:
    """Resultado da deteccao heuristica."""

    __slots__ = ("content_class", "confidence", "company", "model", "persona",
                 "tools_detected", "xml_tags", "score_breakdown")

    def __init__(self, content_class: str, confidence: float, **kw):
        self.content_class = content_class
        self.confidence = confidence
        self.company: str | None = kw.get("company")
        self.model: str | None = kw.get("model")
        self.persona: str | None = kw.get("persona")
        self.tools_detected: list[str] = kw.get("tools_detected", [])
        self.xml_tags: list[str] = kw.get("xml_tags", [])
        self.score_breakdown: dict[str, float] = kw.get("score_breakdown", {})

    def as_meta(self) -> dict[str, Any]:
        """Retorna dicionario pronto para `extra_meta` do analyzer."""
        meta: dict[str, Any] = {
            "detected_content_class": self.content_class,
            "detected_confidence": round(self.confidence, 2),
        }
        if self.company:
            meta["detected_company"] = self.company
        if self.model:
            meta["detected_model"] = self.model
        if self.persona:
            meta["detected_persona"] = self.persona
        if self.tools_detected:
            meta["detected_tools"] = self.tools_detected
        if self.xml_tags:
            meta["detected_xml_tags"] = self.xml_tags
        if self.content_class == "prompt" and self.confidence > 0.6:
            meta["hint_override_source_type"] = "prompt"
        return meta

    def __repr__(self) -> str:
        return (
            f"ContentClass({self.content_class}, conf={self.confidence:.2f}, "
            f"company={self.company}, model={self.model})"
        )


def detect_content_class(
    text: str,
    current_source_type: str = "",
    min_chars: int = 200,
) -> ContentClass:
    """Detecta heuristicamente o tipo de conteudo de um texto extraido.

    Args:
        text: Texto extraido do PDF/doc/ZIP/etc.
        current_source_type: O source_type atual designado pelo pipeline
            (ex: 'pdf', 'site', 'repo'). Se a confianca for alta no 'prompt'
            e current_source_type for 'pdf|site|repo|print', sera substituido.
        min_chars: Textos menores que isso nao sao classificados (retorna 'general').

    Returns:
        ContentClass com classe, confianca, company/model detectados, etc.
    """
    if not text or len(text.strip()) < min_chars:
        return ContentClass("general", 0.0,
                            score_breakdown={"reason": "too_short"})

    # ── Scores por classe ──────────────────────────────────────────
    scores: dict[str, float] = {
        "prompt": 0.0,
        "manual": 0.0,
        "contract": 0.0,
        "tech_doc": 0.0,
    }
    scores["prompt"] = min(1.0, _count_matches(text, PROMPT_STRONG_SIGNALS) * 0.3)
    # Reforco: presenca de persona + tools + xml_tags simultaneos
    persona = _detect_persona(text)
    tools = _detect_tools(text)
    xml_tags = _detect_xml_tags(text)
    if persona and tools and xml_tags:
        scores["prompt"] = min(1.0, scores["prompt"] + 0.4)

    scores["manual"] = min(1.0, _count_matches(text, MANUAL_SIGNALS) * 0.25)
    scores["contract"] = min(1.0, _count_matches(text, CONTRACT_SIGNALS) * 0.3)
    scores["tech_doc"] = min(1.0, _count_matches(text, TECH_DOC_SIGNALS) * 0.2)

    # ── Vencedor ───────────────────────────────────────────────────
    best_class = max(scores, key=scores.get)
    best_score = scores[best_class]
    # Se ninguem chegou a 0.3 de confianca, fica "general"
    if best_score < 0.3:
        best_class = "general"
        best_score = 0.0

    return ContentClass(
        content_class=best_class,
        confidence=best_score,
        company=_detect_company(text),
        model=_detect_model(text),
        persona=persona,
        tools_detected=tools,
        xml_tags=xml_tags,
        score_breakdown=scores,
    )


# ── Smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = {
        "prompt": """You are Claude, an AI assistant built by Anthropic.
Current date: today. Knowledge cutoff: January 2026.
You should be warm, helpful, and concise. Never lie.
Safety: refuse requests for weapons.
Use markdown formatting. You have access to tools: Read, Edit, Write, Bash.
<example>
<user>How to print hello world?</user>
<good_response>print('hello world')</good_response>
</example>""",
        "manual": """Manual de Operacao - Sistema X

Passo 1: Ligue o equipamento.
Passo 2: Configure os parametros.
Passo 3: Inicie a producao.

Este manual descreve como usar o sistema passo a passo. How to install and
configure everything is described below.""",
        "contract": """CONTRATO DE PRESTACAO DE SERVICOS

Pelo presente instrumento particular, o CONTRATANTE e o CONTRATADO
acordam as clausulas abaixo. O foro da comarca e o de Sao Paulo.
Em pleno acordo, assinam o presente.""",
        "tech_doc": """# API Reference

## Endpoints

POST /api/users - Create a new user
GET /api/users - List users

## Usage

```python
import requests
r = requests.post("https://api.example.com/v1/users")
```

Install with: `pip install example-client`""",
        "general": "Bom dia! Vamos marcar uma reuniao amanha as 10h pra discutir o projeto.",
    }

    for label, text in tests.items():
        r = detect_content_class(text)
        print(f"\n[{label}] -> detected: {r.content_class} (conf={r.confidence:.2f})")
        print(f"  company={r.company}, model={r.model}, tools={r.tools_detected[:3]}, "
              f"tags={r.xml_tags[:3]}")
