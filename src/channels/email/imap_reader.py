"""
Seeker.Bot — IMAP Reader
src/channels/email/imap_reader.py

Conecta via IMAP (async), busca emails não lidos (UNSEEN) 
e extrai o conteúdo para ser sumarizado pelo LLM.
"""

import asyncio
import logging
import os
import email
from email.header import decode_header
from datetime import datetime, timedelta

import aioimaplib

log = logging.getLogger("seeker.imap")


class IMAPReader:
    def __init__(self, host: str, user: str, password: str):
        self.host = host
        self.user = user
        self.password = password

    @classmethod
    def from_env(cls) -> "IMAPReader | None":
        host = os.getenv("IMAP_SERVER", "imap.gmail.com")
        user = os.getenv("SMTP_USER", "")
        password = os.getenv("IMAP_PASSWORD", os.getenv("SMTP_PASSWORD", ""))

        if not all([host, user, password]):
            log.warning("[imap] Credenciais não configuradas. IMAP desativado.")
            return None

        return cls(host, user, password)

    async def fetch_unread_emails(self, max_emails: int = 15) -> list[dict]:
        """Busca emails UNSEEN e extrai os dados essenciais."""
        try:
            # 60s timeout na inicializacao tcp tls
            client = aioimaplib.IMAP4_SSL(host=self.host, timeout=60.0)
            await asyncio.wait_for(client.wait_hello_from_server(), timeout=30.0)
        except (asyncio.TimeoutError, Exception) as e:
            log.warning(f"[imap] Falha na conexao (Timeout ou Auth): {e}")
            return []
            
        try:
            res, _ = await client.login(self.user, self.password)
            if res != 'OK':
                log.error(f"[imap] Falha no login: {res}")
                return []

            res, _ = await client.select("INBOX")
            if res != 'OK':
                log.error("[imap] Falha ao selecionar INBOX")
                return []

            # Busca emails não lidos
            res, data = await client.search('UNSEEN')
            
            raw_ids = data[0] if data else b''
            if isinstance(raw_ids, bytes):
                raw_ids = raw_ids.decode('utf-8', errors='ignore')
                
            if res != 'OK' or not raw_ids.strip():
                log.info("[imap] Nenhum email não lido encontrado.")
                return []

            # Os IDs vêm separados por espaço
            email_ids = raw_ids.split()
            
            # Pega os úlimos `max_emails`
            email_ids = email_ids[-max_emails:]
            log.info(f"[imap] Baixando {len(email_ids)} emails não lidos...")

            emails_data = []
            for b_id in email_ids:
                # Faz fetch do corpo RFC822
                res, fetch_data = await client.fetch(b_id, '(RFC822)')
                if res != 'OK':
                    continue

                # aioimaplib retorna dados do fetch em uma lista. O email cru geralmente está no índice 1 ou 2.
                raw_email = None
                for item in fetch_data:
                    if isinstance(item, tuple) and len(item) > 1:
                        raw_email = item[1]
                        break
                
                if not raw_email:
                    continue

                msg = email.message_from_bytes(raw_email)
                
                # Extrai metadados
                subject = self._decode_header(msg.get("Subject", "(Sem Assunto)"))
                sender = self._decode_header(msg.get("From", "(Desconhecido)"))
                date_str = msg.get("Date", "")
                
                # Extrai corpo plaintext
                body = self._extract_text_body(msg)

                emails_data.append({
                    "id": b_id.decode('utf-8') if isinstance(b_id, bytes) else str(b_id),
                    "subject": subject,
                    "sender": sender,
                    "date": date_str,
                    "body": body[:2000] # Limita tamanho para não estourar contexto do LLM
                })

            return emails_data

        except Exception as e:
            log.error(f"[imap] Erro durante o fetch: {e}", exc_info=True)
            return []
        finally:
            try:
                await client.logout()
            except Exception:
                pass

    def _decode_header(self, header_str: str) -> str:
        """Decodifica strings de cabeçalho de email (ex: =?utf-8?q?...)"""
        if not header_str:
            return ""
        decoded_parts = []
        for part, charset in decode_header(header_str):
            if isinstance(part, bytes):
                try:
                    decoded_parts.append(part.decode(charset or 'utf-8', errors='replace'))
                except:
                    decoded_parts.append(part.decode('latin1', errors='replace'))
            else:
                decoded_parts.append(part)
        return "".join(decoded_parts)

    def _extract_text_body(self, msg) -> str:
        """Extrai apenas a parte plaintext do email."""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        return part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                    except:
                        pass
        else:
            if msg.get_content_type() == "text/plain":
                try:
                    return msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='replace')
                except:
                    pass
        return "(Apenas conteúdo HTML ou anexos)"
