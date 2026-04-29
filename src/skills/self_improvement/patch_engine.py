"""
S.A.R.A Patch Engine
src/skills/self_improvement/patch_engine.py

Aplica patches no formato search/replace gerados pelo LLM.
Este formato é mais robusto que unified diff porque:
  - Não depende de números de linha (que LLMs erram frequentemente)
  - É tolerante a pequenas diferenças de whitespace
  - É legível e auditável pelo humano no approval flow
"""

import difflib
import logging

log = logging.getLogger("seeker.self_improvement.patch")


class PatchError(Exception):
    """Erro ao aplicar um patch search/replace."""


def _normalize_whitespace(text: str) -> str:
    """Normaliza espaços no início/fim de cada linha para comparação fuzzy."""
    return "\n".join(line.rstrip() for line in text.splitlines())


def apply_changes(source: str, changes: list[dict]) -> str:
    """
    Aplica uma lista de mudanças search/replace no código fonte.

    Cada item de `changes` deve ter:
      - "search": bloco de código original a ser substituído
      - "replace": bloco de código corrigido

    Estratégia:
      1. Tenta match exato (mais rápido)
      2. Tenta match após normalizar whitespace de fim de linha
      3. Falha com PatchError descritivo se não encontrar

    Args:
        source: código fonte original completo
        changes: lista de dicts com "search" e "replace"

    Returns:
        Código fonte com todas as mudanças aplicadas

    Raises:
        PatchError: se algum bloco "search" não for encontrado no source
    """
    result = source

    for i, change in enumerate(changes):
        search = change.get("search", "").strip("\n")
        replace = change.get("replace", "").strip("\n")

        if not search:
            log.warning(f"[patch] Mudança #{i+1} tem 'search' vazio — ignorando")
            continue

        # 1. Match exato
        if search in result:
            result = result.replace(search, replace, 1)
            log.debug(f"[patch] Mudança #{i+1}: match exato aplicado")
            continue

        # 2. Match com normalização de trailing whitespace
        norm_result = _normalize_whitespace(result)
        norm_search = _normalize_whitespace(search)

        if norm_search in norm_result:
            # Reconstrói substituindo na versão original usando índices
            idx = norm_result.find(norm_search)
            # Mapeia posição no texto normalizado para o original (linha a linha)
            lines_orig = result.splitlines(keepends=True)
            lines_norm = norm_result.splitlines(keepends=True)
            search_lines = norm_search.splitlines()

            # Encontra linha de início
            start_line = norm_result[:idx].count("\n")
            end_line = start_line + len(search_lines)

            before = "".join(lines_orig[:start_line])
            after = "".join(lines_orig[end_line:])
            result = before + replace + ("\n" if not replace.endswith("\n") else "") + after
            log.debug(f"[patch] Mudança #{i+1}: match com normalização aplicado (linha {start_line})")
            continue

        # 3. Falha com contexto útil
        # Gera diff para ajudar no debug
        ratio = difflib.SequenceMatcher(None, norm_search, norm_result[:len(norm_search)*2]).ratio()
        raise PatchError(
            f"Mudança #{i+1}: bloco 'search' não encontrado no arquivo fonte. "
            f"Similaridade máxima: {ratio:.0%}. "
            f"Search (primeiras 3 linhas): {search[:150]!r}"
        )

    return result


def generate_diff_preview(original: str, patched: str, filename: str = "arquivo.py") -> str:
    """
    Gera um diff unificado legível entre original e corrigido.
    Usado para mostrar o preview no Telegram antes da aprovação.
    """
    original_lines = original.splitlines(keepends=True)
    patched_lines = patched.splitlines(keepends=True)

    diff = difflib.unified_diff(
        original_lines,
        patched_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=3,  # linhas de contexto
    )
    return "".join(list(diff)[:60])  # Limita a 60 linhas para o Telegram
