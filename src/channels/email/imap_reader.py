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
            log.error(
                f"[imap] ❌ Credenciais incompletas IMAP:\n"
                f"  IMAP_SERVER: {host or 'NÃO CONFIGURADO'}\n"
                f"  SMTP_USER: {user or 'NÃO CONFIGURADO'}\n"
                f"  IMAP_PASSWORD: {'✓ configurado' if password else '❌ NÃO CONFIGURADO'}\n"
                f"Nota: Se Gmail, use 'App Password', não a senha comum!"
            )
            return None

        log.info(f"[imap] ✓ Credentials OK: user={user}, host={host}")
        return cls(host, user, password)

    async def fetch_unread_emails(self, max_emails: int = 15) -> list[dict]:
        """Busca emails UNSEEN e extrai os dados essenciais."""
        try:
            log.info(f"[imap] Conectando a {self.host}:{self.user}...")
            # 60s timeout na inicializacao tcp tls
            client = aioimaplib.IMAP4_SSL(host=self.host, timeout=60.0)
            await asyncio.wait_for(client.wait_hello_from_server(), timeout=30.0)
            log.info("[imap] ✓ Conectado ao servidor IMAP")
        except (asyncio.TimeoutError, Exception) as e:
            log.error(f"[imap] ❌ Falha na conexão (Timeout ou Auth): {e}", exc_info=True)
            return []

        try:
            log.info(f"[imap] Autenticando como {self.user}...")
            res, _ = await client.login(self.user, self.password)
            if res != 'OK':
                log.error(f"[imap] ❌ Falha no login: {res}", exc_info=True)
                return []
            log.info("[imap] ✓ Autenticado com sucesso")

            log.info("[imap] Selecionando INBOX...")
            res, _ = await client.select("INBOX")
            if res != 'OK':
                log.error("[imap] ❌ Falha ao selecionar INBOX", exc_info=True)
                return []
            log.info("[imap] ✓ INBOX selecionado")

            # Busca emails não lidos
            log.info("[imap] Procurando emails UNSEEN...")
            res, data = await client.search('UNSEEN')

            raw_ids = data[0] if data else b''
            if isinstance(raw_ids, bytes):
                raw_ids = raw_ids.decode('utf-8', errors='ignore')

            if res != 'OK':
                log.error(f"[imap] ❌ Falha na busca UNSEEN: {res}", exc_info=True)
                return []

            if not raw_ids.strip():
                log.info("[imap] ✓ Nenhum email não lido encontrado (INBOX vazio)")
                return []

            log.info(f"[imap] ✓ Encontrados emails não lidos: {raw_ids.strip()}")

            # Os IDs vêm separados por espaço
            email_ids = raw_ids.split()

            # Pega os últimos `max_emails`
            email_ids = email_ids[-max_emails:]
            log.info(f"[imap] 📥 Baixando {len(email_ids)} emails não lidos do INBOX...")

            emails_data = []
            for b_id in email_ids:
                # Faz fetch do corpo sem marcar como lido (PEEK)
                res, fetch_data = await client.fetch(b_id, '(BODY.PEEK[])')
                if res != 'OK':
                    continue

                # aioimaplib retorna: [b'<ID> FETCH (BODY[] {N}', bytearray(<email>), b')']
                # O email bruto está no item[1] como bytearray (não tuple).
                # Suporte a tuple mantido para compatibilidade com outras versões.
                raw_email = None
                for item in fetch_data:
                    if isinstance(item, (bytes, bytearray)) and len(item) > 100:
                        # Descarta a linha de metadata (ex: b'836 FETCH (BODY[] {82349}')
                        decoded = item if isinstance(item, bytes) else bytes(item)
                        if b'Delivered-To' in decoded or b'From:' in decoded or b'Subject:' in decoded or b'MIME' in decoded:
                            raw_email = decoded
                            break
                    elif isinstance(item, tuple) and len(item) > 1:
                        # Formato alternativo (algumas versões do aioimaplib)
                        raw_email = item[1] if isinstance(item[1], bytes) else bytes(item[1])
                        break

                if not raw_email:
                    # Fallback: usa item[1] diretamente se existir e for bytearray/bytes
                    if len(fetch_data) > 1 and isinstance(fetch_data[1], (bytes, bytearray)):
                        raw_email = bytes(fetch_data[1]) if isinstance(fetch_data[1], bytearray) else fetch_data[1]

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

            log.info(f"[imap] ✅ Retornando {len(emails_data)} emails processados")
            return emails_data

        except Exception as e:
            log.error(f"[imap] ❌ Erro durante o fetch: {e}", exc_info=True)
            return []
        finally:
            try:
                await client.logout()
                log.debug("[imap] Desconectado do servidor IMAP")
            except Exception:
                # Windows ProactorEventLoop lança AttributeError 'NoneType'.send
                # no cleanup do SSL após o event loop fechar — é noise, não erro real.
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
                except (UnicodeDecodeError, LookupError) as e:
                    log.debug(f"[imap] Charset fallback (charset={charset}): {e}")
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
                    except (UnicodeDecodeError, AttributeError, TypeError) as e:
                        log.debug(f"[imap] Falha ao extrair parte plaintext: {e}")
                        continue
        else:
            if msg.get_content_type() == "text/plain":
                try:
                    return msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='replace')
                except (UnicodeDecodeError, AttributeError, TypeError) as e:
                    log.debug(f"[imap] Falha ao extrair body simples: {e}")
        return "(Apenas conteúdo HTML ou anexos)"
