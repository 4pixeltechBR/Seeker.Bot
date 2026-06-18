import os
import logging
import requests
import asyncio

log = logging.getLogger("seeker.ms_graph")

class MSGraphClient:
    """Cliente para a API do Microsoft Graph (Outlook/OneDrive) integrado ao Seeker.Bot."""

    def __init__(self, pipeline):
        self.pipeline = pipeline

    async def _get_access_token(self) -> str | None:
        """Tenta obter o access token da Microsoft usando chaves de ambiente."""
        # 1. Se houver token de acesso estático configurado direto, usa ele
        static_token = os.getenv("MICROSOFT_ACCESS_TOKEN", "")
        if static_token:
            return static_token

        # 2. Caso contrário, tenta autenticação OAuth2 via Client Credentials do Azure AD
        client_id = os.getenv("MICROSOFT_CLIENT_ID", "")
        client_secret = os.getenv("MICROSOFT_CLIENT_SECRET", "")
        tenant_id = os.getenv("MICROSOFT_TENANT_ID", "common")

        if not client_id or not client_secret:
            log.warning("[ms_graph] Credenciais do Microsoft Graph não configuradas no ambiente.")
            return None

        url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        payload = {
            "client_id": client_id,
            "scope": "https://graph.microsoft.com/.default",
            "client_secret": client_secret,
            "grant_type": "client_credentials"
        }

        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                lambda: requests.post(url, data=payload, timeout=20)
            )
            res.raise_for_status()
            data = res.json()
            return data.get("access_token")
        except Exception as e:
            log.error(f"[ms_graph] Falha na obtenção do token OAuth: {e}", exc_info=True)
            return None

    async def send_email(self, to: str, subject: str, body: str) -> str:
        """Envia um e-mail através da API do Outlook."""
        token = await self._get_access_token()
        if not token:
            return "❌ Autenticação com Microsoft Graph falhou. Configure MICROSOFT_ACCESS_TOKEN ou MICROSOFT_CLIENT_ID/SECRET."

        # Se for autenticação corporativa (app-only), precisamos de um user ID/email de remetente
        sender_email = os.getenv("MICROSOFT_SENDER_EMAIL", "")
        if sender_email:
            url = f"https://graph.microsoft.com/v1.0/users/{sender_email}/sendMail"
        else:
            url = "https://graph.microsoft.com/v1.0/me/sendMail"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        email_payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "Text",
                    "content": body
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to
                        }
                    }
                ]
            },
            "saveToSentItems": "true"
        }

        log.info(f"[ms_graph] Enviando e-mail para '{to}' com assunto '{subject}'...")
        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                lambda: requests.post(url, json=email_payload, headers=headers, timeout=30)
            )
            # Envio bem-sucedido retorna 202 Accepted
            if res.status_code in (200, 202):
                log.info("[ms_graph] E-mail enviado com sucesso.")
                return f"✅ E-mail enviado com sucesso para {to}."
            else:
                res.raise_for_status()
                return f"❌ Erro ao enviar e-mail: HTTP {res.status_code}"
        except Exception as e:
            log.error(f"[ms_graph] Falha ao invocar Graph sendMail: {e}", exc_info=True)
            res_val = getattr(e, "response", None)
            err_details = res_val.text if res_val else str(e)
            return f"❌ Falha ao enviar e-mail via Graph API: {err_details[:300]}"
