import os
import json
import logging
import requests
from datetime import datetime, timezone

log = logging.getLogger("seeker.x_search")

DEFAULT_XAI_BASE_URL = "https://api.x.ai/v1"
DEFAULT_X_SEARCH_MODEL = "grok-2-1212"

class XSearcher:
    """Implementa busca em tempo real no X/Twitter utilizando a Responses API da xAI (Grok)."""

    def __init__(self, pipeline):
        self.pipeline = pipeline

    def _get_api_key(self) -> str:
        return (
            self.pipeline.api_keys.get("xai")
            or os.getenv("XAI_API_KEY")
            or ""
        )

    async def search(
        self,
        query: str,
        allowed_handles: list[str] | None = None,
        excluded_handles: list[str] | None = None,
        from_date: str = "",
        to_date: str = "",
    ) -> str:
        """Realiza a busca usando a API Grok da xAI."""
        api_key = self._get_api_key()
        if not api_key:
            return "❌ Chave de API da xAI (XAI_API_KEY) não está configurada no ambiente."

        if not query or not query.strip():
            return "❌ A query de busca é obrigatória."

        base_url = os.getenv("XAI_BASE_URL", DEFAULT_XAI_BASE_URL).rstrip("/")
        model = os.getenv("X_SEARCH_MODEL", DEFAULT_X_SEARCH_MODEL)

        # Trata handles
        tool_def = {"type": "x_search"}
        if allowed_handles:
            # Remove arrobas (@) se houver
            tool_def["allowed_x_handles"] = [h.strip().lstrip("@") for h in allowed_handles if h.strip()]
        if excluded_handles:
            tool_def["excluded_x_handles"] = [h.strip().lstrip("@") for h in excluded_handles if h.strip()]
        
        # Trata datas (formato YYYY-MM-DD)
        if from_date.strip():
            tool_def["from_date"] = from_date.strip()
        if to_date.strip():
            tool_def["to_date"] = to_date.strip()

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": query.strip(),
                }
            ],
            "tools": [tool_def],
            "stream": False,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        log.info(f"[x_search] Enviando request para xAI (Grok). Model={model}, Query='{query}'")
        try:
            # Roda no threadpool do asyncio para não travar o loop do bot
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
            )
            response.raise_for_status()
            data = response.json()
            
            # Extrai a resposta textual
            choices = data.get("choices", [])
            if not choices:
                return "⚠️ Resposta vazia da API do Grok."
                
            assistant_message = choices[0].get("message", {})
            answer = assistant_message.get("content", "").strip()
            
            # Extrai citações ou referências de tweets que o Grok retornou na resposta se houver
            system_fingerprint = data.get("system_fingerprint", "")
            
            result_data = {
                "success": True,
                "answer": answer,
                "model": model,
                "system_fingerprint": system_fingerprint
            }
            
            # Formata um retorno amigável
            output = [
                f"### Resposta do Grok (X Search):",
                answer,
                f"\n*(Modelo: {model})*"
            ]
            return "\n".join(output)

        except requests.HTTPError as e:
            log.error(f"[x_search] Erro HTTP da API xAI: {e}", exc_info=True)
            res_val = getattr(e, "response", None)
            err_msg = res_val.text if res_val else str(e)
            return f"❌ Erro HTTP na API xAI: {err_msg[:400]}"
        except Exception as e:
            log.error(f"[x_search] Erro genérico no X Search: {e}", exc_info=True)
            return f"❌ Falha de comunicação com a API xAI: {e}"
import asyncio
