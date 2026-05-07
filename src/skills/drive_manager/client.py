"""
Seeker.Bot — Google Drive Client
src/skills/drive_manager/client.py

Wrapper assíncrono sobre a Google Drive API v3.
Suporta: listar, criar pasta, upload, download, deletar, mover, buscar.

Autenticação: OAuth2 com token persistido em data/google_token.json.
Na primeira execução, envia o link de autorização via Telegram.
"""

import asyncio
import io
import logging
import os
from typing import Callable, Awaitable

log = logging.getLogger("seeker.drive")

# Escopos — acesso total ao Drive do usuário
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Paths de credenciais
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CREDENTIALS_PATH = os.path.join(_ROOT, "config", "credentials.json.json")
TOKEN_PATH = os.path.join(_ROOT, "data", "google_token.json")


class DriveClient:
    """
    Cliente Google Drive com autenticação OAuth2.

    Uso:
        client = DriveClient()
        await client.authenticate(send_link_fn)  # só na 1ª vez
        files = await client.list_folder()
    """

    def __init__(self):
        self._service = None  # googleapiclient resource

    # ─────────────────────────────────────────────────────────────────
    # AUTH
    # ─────────────────────────────────────────────────────────────────

    async def authenticate(self, send_link: Callable[[str], Awaitable[None]] | None = None) -> bool:
        """
        Autentica com Google OAuth2.

        Se já houver token salvo e válido, reutiliza.
        Se não, inicia o flow de autorização e chama send_link() com a URL.
        O usuário clica no link, autoriza, e cola o código de volta no bot.

        Returns True se autenticado com sucesso.
        """
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            log.error("[drive] Dependências não instaladas. Execute: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
            return False

        creds = None

        # Tenta carregar token salvo
        if os.path.exists(TOKEN_PATH):
            try:
                creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
            except Exception as e:
                log.warning(f"[drive] Token inválido, renovando: {e}")
                creds = None

        # Renova token expirado silenciosamente
        if creds and creds.expired and creds.refresh_token:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, creds.refresh, Request())
                self._save_token(creds)
                log.info("[drive] Token renovado com sucesso")
            except Exception as e:
                log.warning(f"[drive] Falha ao renovar token: {e}")
                creds = None

        # Primeiro acesso — precisa do flow OAuth
        if not creds or not creds.valid:
            if not os.path.exists(CREDENTIALS_PATH):
                log.error(f"[drive] credentials.json não encontrado em {CREDENTIALS_PATH}")
                if send_link:
                    await send_link("❌ <b>Google Drive</b>: arquivo <code>credentials.json.json</code> não encontrado em <code>config/</code>.")
                return False

            try:
                loop = asyncio.get_event_loop()

                # Gera a URL de autorização sem abrir browser
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
                flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"

                auth_url, _ = flow.authorization_url(prompt="consent")

                log.info(f"[drive] URL de autorização gerada")

                if send_link:
                    msg = (
                        "🔐 <b>Google Drive — Autorização Necessária</b>\n\n"
                        "Clique no link abaixo para autorizar o Seeker a acessar seu Drive:\n\n"
                        f'<a href="{auth_url}">👉 Autorizar Google Drive</a>\n\n'
                        "Após autorizar, <b>cole aqui o código</b> que o Google mostrar."
                    )
                    await send_link(msg)

                # Guarda o flow para ser completado quando o usuário enviar o código
                self._pending_flow = flow
                return False  # Ainda não autenticado — aguarda código do usuário

            except Exception as e:
                log.error(f"[drive] Erro no flow OAuth: {e}", exc_info=True)
                return False

        # Autenticação bem-sucedida
        self._service = self._build_service(creds)
        log.info("[drive] Autenticado com sucesso")
        return True

    async def complete_auth(self, code: str) -> bool:
        """
        Completa o fluxo OAuth com o código fornecido pelo usuário.
        Salva o token e inicializa o serviço.
        """
        try:
            from googleapiclient.discovery import build

            if not hasattr(self, "_pending_flow") or self._pending_flow is None:
                log.warning("[drive] Nenhum flow pendente para completar")
                return False

            loop = asyncio.get_event_loop()
            flow = self._pending_flow

            # Troca o código pelo token — roda em thread para não bloquear o loop
            await loop.run_in_executor(None, flow.fetch_token, None, None, code.strip())

            creds = flow.credentials
            self._save_token(creds)
            self._service = self._build_service(creds)
            self._pending_flow = None

            log.info("[drive] Autenticação completada e token salvo")
            return True

        except Exception as e:
            log.error(f"[drive] Erro ao completar auth: {e}", exc_info=True)
            return False

    def _save_token(self, creds) -> None:
        """Salva token serializado em TOKEN_PATH."""
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    def _build_service(self, creds):
        """Constrói o resource da Drive API v3."""
        from googleapiclient.discovery import build
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def is_authenticated(self) -> bool:
        return self._service is not None

    def has_pending_auth(self) -> bool:
        return hasattr(self, "_pending_flow") and self._pending_flow is not None

    # ─────────────────────────────────────────────────────────────────
    # OPERAÇÕES
    # ─────────────────────────────────────────────────────────────────

    async def list_folder(self, folder_id: str = "root", page_size: int = 30) -> list[dict]:
        """
        Lista arquivos e pastas dentro de folder_id.
        Retorna lista de dicts com: id, name, mimeType, size, modifiedTime.
        """
        self._require_auth()
        loop = asyncio.get_event_loop()

        def _run():
            query = f"'{folder_id}' in parents and trashed = false"
            fields = "files(id, name, mimeType, size, modifiedTime, parents)"
            result = self._service.files().list(
                q=query,
                pageSize=page_size,
                fields=fields,
                orderBy="folder,name",
            ).execute()
            return result.get("files", [])

        return await loop.run_in_executor(None, _run)

    async def create_folder(self, name: str, parent_id: str = "root") -> dict:
        """Cria uma pasta. Retorna o item criado (id, name)."""
        self._require_auth()
        loop = asyncio.get_event_loop()

        def _run():
            meta = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            return self._service.files().create(body=meta, fields="id, name").execute()

        return await loop.run_in_executor(None, _run)

    async def upload_file(self, local_path: str, folder_id: str = "root", filename: str | None = None) -> dict:
        """
        Faz upload de arquivo local para o Drive.
        Retorna o item criado (id, name, webViewLink).
        """
        self._require_auth()
        import mimetypes
        from googleapiclient.http import MediaFileUpload

        loop = asyncio.get_event_loop()
        fname = filename or os.path.basename(local_path)
        mime, _ = mimetypes.guess_type(local_path)
        mime = mime or "application/octet-stream"

        def _run():
            meta = {"name": fname, "parents": [folder_id]}
            media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
            return self._service.files().create(
                body=meta,
                media_body=media,
                fields="id, name, webViewLink",
            ).execute()

        return await loop.run_in_executor(None, _run)

    async def upload_bytes(self, data: bytes, filename: str, folder_id: str = "root", mimetype: str = "application/octet-stream") -> dict:
        """Upload de bytes em memória (ex: arquivo recebido via Telegram)."""
        self._require_auth()
        from googleapiclient.http import MediaIoBaseUpload

        loop = asyncio.get_event_loop()

        def _run():
            meta = {"name": filename, "parents": [folder_id]}
            media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mimetype, resumable=True)
            return self._service.files().create(
                body=meta,
                media_body=media,
                fields="id, name, webViewLink",
            ).execute()

        return await loop.run_in_executor(None, _run)

    async def download_file(self, file_id: str) -> tuple[bytes, str]:
        """
        Baixa um arquivo do Drive.
        Retorna (bytes do arquivo, nome do arquivo).
        """
        self._require_auth()
        from googleapiclient.http import MediaIoBaseDownload

        loop = asyncio.get_event_loop()

        def _run():
            # Busca metadados
            meta = self._service.files().get(fileId=file_id, fields="name, mimeType").execute()
            name = meta.get("name", "arquivo")

            # Download do conteúdo
            request = self._service.files().get_media(fileId=file_id)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return buf.getvalue(), name

        return await loop.run_in_executor(None, _run)

    async def delete(self, file_id: str, permanent: bool = False) -> bool:
        """
        Move para lixeira (permanent=False) ou deleta permanentemente.
        Retorna True se sucesso.
        """
        self._require_auth()
        loop = asyncio.get_event_loop()

        def _run():
            if permanent:
                self._service.files().delete(fileId=file_id).execute()
            else:
                self._service.files().update(
                    fileId=file_id,
                    body={"trashed": True},
                ).execute()
            return True

        return await loop.run_in_executor(None, _run)

    async def move(self, file_id: str, new_parent_id: str) -> dict:
        """Move arquivo/pasta para nova pasta. Retorna item atualizado."""
        self._require_auth()
        loop = asyncio.get_event_loop()

        def _run():
            # Busca parents atuais
            meta = self._service.files().get(fileId=file_id, fields="parents").execute()
            old_parents = ",".join(meta.get("parents", []))
            return self._service.files().update(
                fileId=file_id,
                addParents=new_parent_id,
                removeParents=old_parents,
                fields="id, name, parents",
            ).execute()

        return await loop.run_in_executor(None, _run)

    async def search(self, query: str, page_size: int = 20) -> list[dict]:
        """Busca arquivos pelo nome. Retorna lista de resultados."""
        self._require_auth()
        loop = asyncio.get_event_loop()

        def _run():
            safe_query = query.replace("'", "\\'")
            q = f"name contains '{safe_query}' and trashed = false"
            result = self._service.files().list(
                q=q,
                pageSize=page_size,
                fields="files(id, name, mimeType, size, modifiedTime)",
            ).execute()
            return result.get("files", [])

        return await loop.run_in_executor(None, _run)

    async def get_info(self, file_id: str) -> dict:
        """Retorna metadados completos de um arquivo/pasta."""
        self._require_auth()
        loop = asyncio.get_event_loop()

        def _run():
            return self._service.files().get(
                fileId=file_id,
                fields="id, name, mimeType, size, modifiedTime, parents, webViewLink, createdTime, owners",
            ).execute()

        return await loop.run_in_executor(None, _run)

    # ─────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────

    def _require_auth(self):
        if not self._service:
            raise RuntimeError("DriveClient não autenticado. Chame authenticate() primeiro.")
