"""
Seeker.Bot — Crawl4AI structured extraction layer
src/skills/event_radar/crawl_extract.py

Wrapper que recebe HTML já capturado pelo StealthBrowser e extrai dados
estruturados via LLM local (Ollama) usando Crawl4AI como motor.

Por que não substituir o StealthBrowser:
  - O StealthBrowser já tem stealth UA, cookie/popup dismissal para sites
    brasileiros, retry com backoff, throttle. É melhor que o crawler do
    Crawl4AI para prefeituras/gov.br.
  - Crawl4AI brilha como layer de extração estruturada, não fetcher.

Arquitetura:
  StealthBrowser → HTML bruto → Crawl4AI.arun("raw://") → schema validation

Não importa Crawl4AI no topo — lazy load para o módulo carregar limpo em
ambientes sem crawl4ai instalado (CI, testes, etc).
"""

import logging
from typing import Optional

from pydantic import BaseModel

log = logging.getLogger("seeker.event_radar.crawl_extract")


def _crawl4ai_available() -> bool:
    """Verifica se crawl4ai está disponível sem importar (evita poluir logs)."""
    try:
        import importlib.util
        return importlib.util.find_spec("crawl4ai") is not None
    except Exception:
        return False


async def extract_structured(
    html: str,
    schema: type[BaseModel],
    instruction: str,
    model: str = "ollama/qwen3.5:4b",
    max_tokens: int = 2048,
) -> Optional[list[BaseModel]]:
    """
    Extrai uma lista de objetos estruturados a partir de HTML usando LLM.

    Args:
        html: HTML cru (pode vir do StealthBrowser.extract_html()).
        schema: classe Pydantic com os campos a extrair (model_json_schema()).
        instruction: instrução em PT-BR descrevendo o que extrair.
        model: tag LiteLLM. Default Ollama local. Para Cerebras use
               "cerebras/llama-3.3-70b". Para Gemini "gemini/gemini-2.5-flash".
        max_tokens: limite de saída.

    Returns:
        Lista de instâncias do schema (validadas) ou None se Crawl4AI
        indisponível ou extração falhou.
    """
    if not _crawl4ai_available():
        log.warning("[crawl_extract] crawl4ai não instalado — pulando extração")
        return None

    try:
        from crawl4ai import AsyncWebCrawler
        from crawl4ai.extraction_strategy import LLMExtractionStrategy
        from crawl4ai.async_configs import LLMConfig
    except ImportError as e:
        log.warning(f"[crawl_extract] crawl4ai import falhou: {e}")
        return None

    try:
        # Estratégia LLM com schema JSON do Pydantic
        strategy = LLMExtractionStrategy(
            llm_config=LLMConfig(provider=model),
            schema=schema.model_json_schema(),
            extraction_type="schema",
            instruction=instruction,
            chunk_token_threshold=4000,
            apply_chunking=True,
            input_format="html",
            extra_args={"max_tokens": max_tokens, "temperature": 0.0},
        )

        # Usa raw:// scheme para passar HTML in-memory (sem nova request)
        url = f"raw://{html}"

        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(url=url, extraction_strategy=strategy)

        if not result.success or not result.extracted_content:
            log.info(
                f"[crawl_extract] extração vazia (success={result.success})"
            )
            return []

        import json
        raw = result.extracted_content
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as e:
                log.warning(f"[crawl_extract] JSON inválido: {e}")
                return []

        # raw pode ser list ou dict {"items": [...]} dependendo da estratégia
        items = raw if isinstance(raw, list) else raw.get("items", [raw])

        validated: list[BaseModel] = []
        for it in items:
            try:
                validated.append(schema(**it))
            except Exception as e:
                log.debug(f"[crawl_extract] item rejeitado: {e}")
                continue

        log.info(
            f"[crawl_extract] extraídos {len(validated)} de {len(items)} candidatos"
        )
        return validated

    except Exception as e:
        log.warning(f"[crawl_extract] falha: {e}", exc_info=True)
        return None


# ─────────────────────────────────────────────────────────────────────
# Schema padrão para eventos do EventRadar
# ─────────────────────────────────────────────────────────────────────


class EventoExtraido(BaseModel):
    """Schema para eventos públicos extraídos de páginas de prefeituras."""
    nome: str
    data_estimada: str
    cidade: str
    local: Optional[str] = None
    tipo: Optional[str] = None  # festa, rodeio, expo, religioso, cultural


async def extrair_eventos(
    html: str,
    cidade: str,
    uf: str = "GO",
    model: str = "ollama/qwen3.5:4b",
) -> list[EventoExtraido]:
    """
    Convenience wrapper: extrai eventos de uma página de prefeitura.
    """
    instruction = (
        f"Você é o extrator de eventos do Seeker.Bot. Analise o HTML "
        f"e identifique TODOS os eventos públicos da cidade de {cidade} ({uf}) "
        f"em 2026: festas, rodeios, exposições agropecuárias, festas religiosas, "
        f"aniversários da cidade, festivais culturais, carnaval, reveillon.\n"
        f"Para cada evento, extraia: nome, data_estimada (texto livre, pode ser "
        f"'Junho 2026' ou '15-18 de julho de 2026'), cidade (sempre '{cidade}'), "
        f"local (se mencionado), tipo (festa|rodeio|expo|religioso|cultural)."
    )
    result = await extract_structured(
        html=html,
        schema=EventoExtraido,
        instruction=instruction,
        model=model,
    )
    return result or []
