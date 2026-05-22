"""
Seeker.Bot — Utilitários compartilhados
src/core/utils.py

Funções usadas por múltiplos módulos (phases, skills, extractor).
"""

import json
import logging
import re

log = logging.getLogger("seeker.utils")

_MARKDOWN_FENCE_RE = re.compile(r"```(?:json)?\s*", re.IGNORECASE)


def parse_llm_json(text: str) -> dict | list:
    """
    Extrai e parseia JSON de resposta de LLM.

    Lida com:
    - JSON puro
    - JSON envolto em ```json ... ```
    - Texto antes/depois do JSON (ex: "Here is the result: {...}")
    - Arrays top-level [...]

    Raises:
        ValueError: se nenhum JSON válido for encontrado.
    """
    if not text or not text.strip():
        raise ValueError("Texto vazio — sem JSON para parsear.")

    # Remove fences de markdown
    clean = _MARKDOWN_FENCE_RE.sub("", text)
    if clean.endswith("```"):
        clean = clean[:-3]
    clean = clean.strip()

    # Tenta parse direto (caso mais comum)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # Encontra o delimitador de abertura mais cedo ({  ou [)
    idx_obj = clean.find("{")
    idx_arr = clean.find("[")

    if idx_obj == -1 and idx_arr == -1:
        raise ValueError(f"Nenhum JSON encontrado no texto: {clean[:100]}...")

    start_idx = -1
    # Decide se é objeto ou array baseado em qual vem primeiro
    if idx_arr != -1 and (idx_obj == -1 or idx_arr < idx_obj):
        start_idx = idx_arr
    else:
        start_idx = idx_obj

    candidate = clean[start_idx:]

    try:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(candidate)
        return obj
    except json.JSONDecodeError as e:
        raise ValueError(
            f"JSON inválido a partir da posição {start_idx}: {e}"
        ) from e
