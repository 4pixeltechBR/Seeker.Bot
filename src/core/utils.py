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


def _try_recover_truncated_json(fragment: str) -> "dict | list | None":
    """
    Tenta recuperar JSON truncado fechando chaves/colchetes pendentes.
    Útil quando o LLM atinge max_tokens no meio de uma resposta grande.
    Retorna None se não conseguir.
    """
    stack = []
    in_string = False
    escape_next = False

    for ch in fragment:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()

    if not stack:
        return None  # JSON já fechado — recovery não necessário

    # Fecha os delimitadores pendentes na ordem inversa
    candidate = fragment.rstrip() + "".join(reversed(stack))
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def parse_llm_json(text: str) -> "dict | list":
    """
    Extrai e parseia JSON de resposta de LLM.

    Lida com:
    - JSON puro
    - JSON envolto em ```json ... ```
    - Texto antes/depois do JSON
    - Arrays top-level [...]
    - JSON truncado por max_tokens (recovery automático com fechamento de delimitadores)

    Raises:
        ValueError: se nenhum JSON válido for encontrado nem recuperado.
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

    # Localiza abertura de objeto ou array
    idx_obj = clean.find("{")
    idx_arr = clean.find("[")

    if idx_obj == -1 and idx_arr == -1:
        raise ValueError(f"Nenhum JSON encontrado no texto: {clean[:100]}...")

    if idx_arr != -1 and (idx_obj == -1 or idx_arr < idx_obj):
        start_char, end_char = "[", "]"
        start_idx = idx_arr
    else:
        start_char, end_char = "{", "}"
        start_idx = idx_obj

    end_idx = clean.rfind(end_char)

    # Tenta slice normal
    if end_idx > start_idx:
        candidate = clean[start_idx:end_idx + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # JSON truncado — tenta recovery fechando os delimitadores abertos
    fragment = clean[start_idx:]
    recovered = _try_recover_truncated_json(fragment)
    if recovered is not None:
        log.warning(
            "[utils] JSON truncado recuperado — resposta provavelmente cortada por max_tokens. "
            "Verifique o campo full_code para completude."
        )
        return recovered

    raise ValueError(
        f"JSON malformado e irrecuperável ('{start_char}' sem fechamento). "
        f"Resposta truncada — aumente max_tokens ou reduza o payload enviado ao LLM."
    )
