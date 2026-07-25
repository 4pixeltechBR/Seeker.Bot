"""scripts/promptograph_mcp_server.py — MCP server stdio para o Promptograph.

Expoe 4 tools via MCP (Model Context Protocol):
  - promptograph_search(query, company?, model?, limit?) -> busca prompts indexados
  - promptograph_validate(content) -> pontua 0-100%, nota A+ a F
  - promptograph_generate(spec_json) -> gera prompt de preset ou custom
  - promptograph_stats() -> estatisticas do indice (5317 prompts)

Usa FastMCP para simplicidade. Roda via stdio transport (mesmo padrao
filesystem/github servers no config/mcp_servers.json).

Source: index_filtered.json copiado de E:\\Skills\\promptograph\\promptograph\\data\\
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

# Path setup — adiciona src ao sys.path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from mcp.server.fastmcp import FastMCP

from src.skills.promptograph import build_prompt, validate_prompt, PRESET_TEMPLATES

log = logging.getLogger("seeker.mcp.promptograph")
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

# ── Carrega indice ──────────────────────────────────────────────────────

_INDEX_PATH = _ROOT / "data" / "promptograph" / "index_filtered.json"
_INDEX: list[dict] = []
if _INDEX_PATH.exists():
    try:
        _INDEX = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        log.info(f"[promptograph-mcp] Carregado {len(_INDEX)} prompts de {_INDEX_PATH}")
    except Exception as e:
        log.error(f"[promptograph-mcp] Falha ao carregar {e}")
else:
    log.warning(f"[promptograph-mcp] {_INDEX_PATH} nao existe")


# ── FastMCP ───────────────────────────────────────────────────────────

mcp = FastMCP("promptograph")


@mcp.tool()
def promptograph_search(query: str, company: str = "", model: str = "", limit: int = 20) -> str:
    """Busca prompts indexados no catalogo de 5.317 prompts reais de producao.

    Args:
        query: Texto pra buscar (no filename, persona, preview)
        company: Filtra por empresa (Anthropic, OpenAI, Google, xAI, Cursor, etc)
        model: Filtra por modelo (ex: claude-opus-4.5, gpt-5)
        limit: Max de resultados (default 20, max 100)

    Returns:
        JSON com lista de prompts: id, filename, company, model, tokens, persona
    """
    limit = max(1, min(int(limit), 100))
    q_lower = query.lower().strip()
    results = []
    for p in _INDEX:
        # Filtro por empresa
        if company and p.get("company", "").lower() != company.lower():
            continue
        # Filtro por modelo
        if model and model.lower() not in p.get("model", "").lower():
            continue
        # Busca textual em filename + persona + preview
        if q_lower:
            haystack = " ".join([
                p.get("filename", ""),
                p.get("persona", ""),
                p.get("preview", ""),
            ]).lower()
            if q_lower not in haystack:
                continue
        results.append({
            "id": p.get("id", ""),
            "filename": p.get("filename", ""),
            "company": p.get("company", ""),
            "model": p.get("model", ""),
            "tokens": p.get("tokens_estimate", 0),
            "persona": p.get("persona", "")[:120],
        })
        if len(results) >= limit:
            break
    return json.dumps({"total": len(results), "results": results}, ensure_ascii=False)


@mcp.tool()
def promptograph_validate(content: str) -> str:
    """Valida um system prompt contra 13 boas praticas + 6 red flags.

    Args:
        content: Texto completo do system prompt

    Returns:
        JSON com: score (0-100), grade (A+ a F), passed, failed, warnings, stats
    """
    result = validate_prompt(content)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def promptograph_generate(preset_name: str = "", spec_json: str = "") -> str:
    """Gera um system prompt a partir de um preset ou spec customizada.

    Args:
        preset_name: Nome de preset (claude_coding_agent, gpt5_assistant,
                     cursor_style_coding, perplexity_search, devin_autonomous)
        spec_json: JSON com spec customizada (sobrescreve preset).
                   Keys: name, role_description, company, model, family, tone,
                         formatting, safety, tools, memory, refusals,
                         include_examples

    Returns:
        JSON com: prompt (texto gerado), score, grade, chars, tokens
    """
    if preset_name and preset_name in PRESET_TEMPLATES:
        spec = dict(PRESET_TEMPLATES[preset_name]["spec"])
    else:
        spec = {}
    if spec_json:
        try:
            custom = json.loads(spec_json)
            spec.update(custom)
        except Exception as e:
            return json.dumps({"error": f"spec_json invalido: {e}"}, ensure_ascii=False)
    if not spec:
        return json.dumps({
            "error": "Especifique preset_name ou spec_json. "
                     "Presets: " + ", ".join(PRESET_TEMPLATES.keys())
        }, ensure_ascii=False)
    prompt = build_prompt(spec)
    val = validate_prompt(prompt)
    return json.dumps({
        "prompt": prompt,
        "score": val["score"],
        "grade": val["grade"],
        "chars": len(prompt),
        "tokens": len(prompt) // 4,
    }, ensure_ascii=False)


@mcp.tool()
def promptograph_stats() -> str:
    """Estatisticas do catalogo de 5.317 prompts indexados.

    Returns:
        JSON com: total, by_company, by_model (top 10), total_tokens
    """
    from collections import Counter
    by_company = Counter(p.get("company", "?") for p in _INDEX)
    by_model = Counter(p.get("model", "?") for p in _INDEX)
    total_tokens = sum(p.get("tokens_estimate", 0) for p in _INDEX)
    return json.dumps({
        "total": len(_INDEX),
        "by_company": dict(by_company.most_common()),
        "by_model_top10": dict(by_model.most_common(10)),
        "total_tokens_estimate": total_tokens,
    }, ensure_ascii=False)


@mcp.resource("promptograph://presets")
def list_presets() -> str:
    """Lista presets disponiveis com descricao."""
    out = {}
    for name, p in PRESET_TEMPLATES.items():
        out[name] = p["description"]
    return json.dumps(out, ensure_ascii=False, indent=2)


@mcp.prompt()
def review_prompt(content: str) -> str:
    """Prompt pra pedir uma revisao critica de um system prompt.

    Args:
        content: O system prompt a ser revisado
    """
    return (
        f"Por favor revise o seguinte system prompt como um especialista "
        f"em engenharia de prompts. Avalie: clareza, completude, potencial "
        f"vulnerabilidade a injection, redundancias, e sugestoes de melhoria.\n\n"
        f"### System Prompt\n\n{content}\n\n"
        f"### Fim\n\n"
        f"De sua analise em formato markdown com topicos: Score, Problemas, "
        f"Sugestoes, Notas."
    )


@mcp.prompt()
def compare_prompts(left: str, right: str) -> str:
    """Prompt pra comparar 2 system prompts lado a lado."""
    return (
        f"Compare estes 2 system prompts e diga qual e melhor e por quê. "
        f"Critere: clareza, seguranca, eficacia.\n\n"
        f"## Prompt A\n\n{left}\n\n## Prompt B\n\n{right}\n\n"
        f"Resposta em markdown."
    )


if __name__ == "__main__":
    mcp.run()
