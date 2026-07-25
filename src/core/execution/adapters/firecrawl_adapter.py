"""
Firecrawl Adapter — registra a ferramenta de scraping de páginas web como tool portada.
Extrai conteúdo limpo em Markdown de uma URL específica via Firecrawl API.
Plano gratuito: 1.000 créditos/mês (1 crédito = 1 página raspada).
"""

import os
import logging
import asyncio

log = logging.getLogger("seeker.execution.adapters.firecrawl")

_tag = "FIRECRAWL"
_prompt_desc = (
    "[FIRECRAWL: \"url\"] — Extrai o conteúdo limpo (Markdown) de uma página web específica. "
    "Use quando precisar ler documentação, artigos, posts de blog ou qualquer página na íntegra. "
    "O conteúdo retornado já vem sem menus, anúncios e ruído HTML. "
    "Este é o modo scrape — ideal para páginas estáticas. Se a página exigir login, cliques ou formulários, "
    "avise o usuário que a página requer interação. "
    "Exemplo: [FIRECRAWL: \"https://docs.firecrawl.dev/api-reference\"]"
)


async def _firecrawl_executor(arg: str, response_text: str = "") -> str:
    """
    Executor do Firecrawl.
    Recebe uma URL, faz scrape via Firecrawl API e retorna o conteúdo em Markdown.
    """
    url = arg.strip().strip('"').strip("'")
    if not url:
        return "❌ URL vazia. Forneça uma URL válida para extrair o conteúdo."

    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key or api_key.startswith("fc-") and "YOUR" in api_key:
        return "❌ Chave da API Firecrawl não configurada. Adicione FIRECRAWL_API_KEY no .env"

    try:
        from firecrawl import FirecrawlApp
    except ImportError as e:
        log.error(f"[firecrawl_adapter] firecrawl-py não instalado: {e}")
        return f"❌ Dependência firecrawl-py não instalada. Execute: pip install firecrawl-py"

    try:
        app = FirecrawlApp(api_key=api_key)

        # Firecrawl faz chamadas HTTP síncronas — rodamos em thread pool
        # Sintaxe firecrawl-py v4.30+: scrape(url, formats=["markdown"])
        result = await asyncio.to_thread(
            app.scrape,
            url,
            formats=["markdown"]
        )

        content = getattr(result, "markdown", None) if result else None
        if content:
            # Trunca se for absurdamente grande (evita estourar contexto do LLM)
            max_len = 60000
            if len(content) > max_len:
                truncated = content[:max_len]
                return (
                    f"📝 <b>Conteúdo extraído de {url}</b> (truncado por limite de contexto):\n\n"
                    f"{truncated}\n\n"
                    f"[Conteúdo truncado — página original tem {len(content)} caracteres]"
                )
            return f"📝 <b>Conteúdo extraído de {url}</b>:\n\n{content}"

        return (
            f"⚠️ A página {url} foi acessada, mas nenhum conteúdo em Markdown pôde ser extraído. "
            "Pode ser uma página dinâmica (SPA), paywall ou erro de carregamento."
        )

    except Exception as e:
        # Crucial para agentes: nunca quebre o loop. Retorna erro como texto.
        log.error(f"[firecrawl_adapter] Erro ao acessar {url}: {e}", exc_info=True)
        error_msg = str(e)
        # Detecta erros comuns para dar feedback útil ao LLM
        if "402" in error_msg or "credits" in error_msg.lower():
            return f"❌ Erro 402 / créditos esgotados no Firecrawl ao acessar {url}."
        if "404" in error_msg:
            return f"❌ Página não encontrada (404): {url}."
        if "403" in error_msg or "Forbidden" in error_msg:
            return f"❌ Acesso negado (403) ou paywall detectado em {url}."
        return f"❌ Erro ao acessar {url}. Detalhes: {error_msg}"


def register():
    from src.core.execution.adapters.manager import register_adapter
    register_adapter(
        "firecrawl",
        _tag,
        _prompt_desc,
        _firecrawl_executor,
        examples=[
            '[FIRECRAWL: "https://docs.python.org/3/library/asyncio.html"]',
            '[FIRECRAWL: "https://blog.example.com/post-123"]',
            '[FIRECRAWL]',
        ],
    )
    log.info("Adaptador Firecrawl registrado com sucesso.")
