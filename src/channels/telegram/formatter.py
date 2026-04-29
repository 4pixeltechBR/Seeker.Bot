"""
Seeker.Bot — Telegram Formatter
src/channels/telegram/formatter.py

Converte Markdown (output dos LLMs) → HTML do Telegram.

O Telegram suporta um subset limitado de HTML:
  <b>bold</b>  <i>italic</i>  <code>inline</code>
  <pre>code block</pre>  <s>strikethrough</s>
  <a href="url">link</a>

Os LLMs retornam Markdown: **bold**, *italic*, `code`, ```blocks```.
Este módulo faz a ponte.
"""

import re
import html as html_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.pipeline import PipelineResult



MAX_MSG_LENGTH = 4096


def format_cost_line(result: "PipelineResult") -> str:
    """Formata o rodapé de custo/latência de uma resposta do pipeline."""
    parts = []
    if result.total_cost_usd > 0:
        parts.append(f"${result.total_cost_usd:.4f}")
    parts.append(f"{result.total_latency_ms}ms")
    parts.append(f"{result.llm_calls} calls")
    if result.facts_used > 0:
        parts.append(f"🧠 {result.facts_used} fatos")
    if result.arbitrage and result.arbitrage.has_conflicts:
        parts.append(f"⚠️ {len(result.arbitrage.conflict_zones)} conflitos")
    if result.verdict:
        parts.append(result.verdict.to_footer())
    return " · ".join(parts)


def split_message(text: str, max_length: int = MAX_MSG_LENGTH) -> list[str]:
    """Split a long Telegram message into chunks that respect the 4096-char limit.

    Prefers splitting on double newlines, then single newlines, then hard-cuts.
    """
    if len(text) <= max_length:
        return [text]
    parts = []
    remaining = text
    while remaining:
        if len(remaining) <= max_length:
            parts.append(remaining)
            break
        cut = remaining.rfind("\n\n", 0, max_length)
        if cut == -1 or cut < max_length // 2:
            cut = remaining.rfind("\n", 0, max_length)
        if cut == -1 or cut < max_length // 2:
            cut = max_length
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return parts


# Tags que o Telegram aceita (para sanitização)
_ALLOWED_TAGS = {"b", "i", "s", "u", "code", "pre", "a"}
_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>")


def _sanitize_html(text: str) -> str:
    """
    Remove/escapa tags HTML que o Telegram não suporta.
    Mantém apenas: b, i, s, u, code, pre, a.
    """
    def _replace_tag(match):
        closing = match.group(1)
        tag = match.group(2).lower()
        attrs = match.group(3)
        if tag in _ALLOWED_TAGS:
            if tag == "a" and not closing:
                return f"<a{attrs}>"
            return f"<{closing}{tag}>"
        # Tag não suportada → escapa
        return html_module.escape(match.group(0))
    
    return _TAG_RE.sub(_replace_tag, text)


def _balance_tags(text: str) -> str:
    """
    Garante que todas as tags abertas sejam fechadas.
    Evita o erro 'Unexpected end tag' do Telegram.
    """
    stack = []
    for match in _TAG_RE.finditer(text):
        closing = match.group(1)
        tag = match.group(2).lower()
        if tag not in _ALLOWED_TAGS:
            continue
        if tag == "br":
            continue
        if not closing:
            stack.append(tag)
        else:
            # Fecha a tag mais recente que bate
            for i in range(len(stack) - 1, -1, -1):
                if stack[i] == tag:
                    stack.pop(i)
                    break
    
    # Fecha tags restantes na ordem inversa
    for tag in reversed(stack):
        text += f"</{tag}>"
    
    return text


def md_to_telegram_html(text: str) -> str:
    """
    Converte Markdown → HTML compatível com Telegram.
    
    Processa nesta ordem (importa pra evitar conflitos):
    1. Protege blocos de código (não processa dentro deles)
    2. Escapa caracteres HTML especiais
    3. Converte patterns Markdown → HTML tags
    4. Restaura blocos de código
    5. Sanitiza tags não suportadas
    6. Balanceia tags abertas/fechadas
    """
    # ── 1. Extrai e protege blocos de código ──────────────
    code_blocks = []
    
    def protect_code_block(match):
        idx = len(code_blocks)
        lang = match.group(1) or ""
        code = match.group(2)
        code_blocks.append(f"<pre>{html_module.escape(code.strip())}</pre>")
        return f"\x00CODEBLOCK{idx}\x00"

    # Blocos ``` ... ```
    text = re.sub(
        r"```(\w*)\n?(.*?)```",
        protect_code_block,
        text,
        flags=re.DOTALL,
    )

    # ── 2. Protege inline code ────────────────────────────
    inline_codes = []
    
    def protect_inline(match):
        idx = len(inline_codes)
        inline_codes.append(f"<code>{html_module.escape(match.group(1))}</code>")
        return f"\x00INLINE{idx}\x00"

    text = re.sub(r"`([^`]+)`", protect_inline, text)

    # ── 3. Escapa HTML no texto restante ──────────────────
    text = html_module.escape(text)

    # ── 4. Converte Markdown → HTML ──────────────────────
    
    # **bold** → <b>bold</b> (precisa vir antes de *italic*)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    
    # *italic* → <i>italic</i> (mas não dentro de palavras como file*name)
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"<i>\1</i>", text)
    
    # ~~strikethrough~~ → <s>strikethrough</s>
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Headings: ### Title → <b>Title</b> (Telegram não tem h1/h2/h3)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Links: [text](url) → <a href="url">text</a>
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )

    # ── 5. Restaura código protegido ──────────────────────
    for idx, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{idx}\x00", block)

    for idx, inline in enumerate(inline_codes):
        text = text.replace(f"\x00INLINE{idx}\x00", inline)

    # ── 6. Sanitiza e balanceia ───────────────────────────
    text = _sanitize_html(text)
    text = _balance_tags(text)

    # ── 7. Limpa artefatos ────────────────────────────────
    # Remove linhas vazias excessivas
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
