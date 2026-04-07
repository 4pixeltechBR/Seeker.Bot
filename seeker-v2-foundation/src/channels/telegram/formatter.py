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
import html


def md_to_telegram_html(text: str) -> str:
    """
    Converte Markdown → HTML compatível com Telegram.
    
    Processa nesta ordem (importa pra evitar conflitos):
    1. Protege blocos de código (não processa dentro deles)
    2. Escapa caracteres HTML especiais
    3. Converte patterns Markdown → HTML tags
    4. Restaura blocos de código
    """
    # ── 1. Extrai e protege blocos de código ──────────────
    code_blocks = []
    
    def protect_code_block(match):
        idx = len(code_blocks)
        lang = match.group(1) or ""
        code = match.group(2)
        code_blocks.append(f"<pre>{html.escape(code.strip())}</pre>")
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
        inline_codes.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00INLINE{idx}\x00"

    text = re.sub(r"`([^`]+)`", protect_inline, text)

    # ── 3. Escapa HTML no texto restante ──────────────────
    # Precisamos escapar <, >, & que não são nossas tags
    text = html.escape(text)

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

    # ── 6. Limpa artefatos ────────────────────────────────
    # Remove linhas vazias excessivas
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
