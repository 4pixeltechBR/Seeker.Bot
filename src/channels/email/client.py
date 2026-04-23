"""
Seeker.Bot — Email Client
src/channels/email/client.py

Client SMTP assíncrono para notificações e cold emails.
Usa aiosmtplib para não bloquear o event loop.

Configuração via .env:
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=seu@gmail.com
    SMTP_PASSWORD=app-password-do-gmail
    EMAIL_RECIPIENTS=voce@email.com,outro@email.com
"""

import logging
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

log = logging.getLogger("seeker.email")


class EmailClient:
    """
    Client SMTP async. Gmail-friendly (usa App Password).
    
    Uso:
        client = EmailClient.from_env()
        await client.send(
            to=["dest@email.com"],
            subject="[Seeker] Hot Lead",
            body_html="<b>Dossiê...</b>"
        )
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        from_name: str = "Seeker.Bot",
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_name = from_name
        self.from_address = f"{from_name} <{user}>"

    @classmethod
    def from_env(cls) -> "EmailClient | None":
        """Cria client a partir de variáveis de ambiente. Retorna None se não configurado."""
        host = os.getenv("SMTP_HOST", "")
        port = int(os.getenv("SMTP_PORT", "587"))
        user = os.getenv("SMTP_USER", "")
        password = os.getenv("SMTP_PASSWORD", "")

        if not all([host, user, password]):
            log.info("[email] SMTP não configurado — notificações por email desativadas.")
            return None

        log.info(f"[email] SMTP configurado: {user}@{host}:{port}")
        return cls(host=host, port=port, user=user, password=password)

    async def send(
        self,
        to: list[str],
        subject: str,
        body_html: str,
        body_text: str | None = None,
    ) -> bool:
        """
        Envia email HTML.
        body_text é fallback plaintext (gerado automaticamente se None).
        """
        msg = MIMEMultipart("alternative")
        msg["From"] = self.from_address
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject

        # Plaintext fallback
        if body_text is None:
            import re
            body_text = re.sub(r"<[^>]+>", "", body_html)

        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        try:
            await aiosmtplib.send(
                msg,
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                use_tls=False,
                start_tls=True,
            )
            log.info(f"[email] Enviado: '{subject}' → {to}")
            return True
        except Exception as e:
            log.error(f"[email] Falha ao enviar '{subject}': {e}", exc_info=True)
            return False

    async def health_check(self) -> bool:
        """Testa conexão SMTP sem enviar."""
        try:
            smtp = aiosmtplib.SMTP(
                hostname=self.host, port=self.port, use_tls=False
            )
            await smtp.connect()
            await smtp.starttls()
            await smtp.login(self.user, self.password)
            await smtp.quit()
            return True
        except Exception as e:
            log.error(f"[email] Health check falhou: {e}", exc_info=True)
            return False
