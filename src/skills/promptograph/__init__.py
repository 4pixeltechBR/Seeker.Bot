"""promptograph skill — validacao, geracao e (futuro) browse de system prompts.

Port do projeto Promptograph (MIT, github.com/4pixeltechBR/promptograph).
Baseado em 5.317 prompts reais de producao (Anthropic, OpenAI, Google, etc).

Modulos:
- validator: 13 boas praticas + 6 red flags (score 0-100%, grade A+ a F)
- builder:    5 presets (Claude/GPT/Cursor/Perplexity/Devin) + templates modulares
"""

from __future__ import annotations

from src.skills.promptograph.validator import validate_prompt, GOOD_PRACTICES, RED_FLAGS
from src.skills.promptograph.builder import build_prompt, PRESET_TEMPLATES, TEMPLATES

__all__ = [
    "validate_prompt",
    "GOOD_PRACTICES",
    "RED_FLAGS",
    "build_prompt",
    "PRESET_TEMPLATES",
    "TEMPLATES",
]
