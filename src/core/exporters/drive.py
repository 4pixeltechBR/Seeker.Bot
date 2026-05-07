import os
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

log = logging.getLogger("seeker.exporter.drive")


class GoogleDriveExporter:
    """
    Exportador via API do Google Drive (Service Account).
    Garante que os Dossiês e o Radar de Eventos estejam sempre no Drive para NotebookLM.
    """

    def __init__(self, service_account_path: str, folder_id: str):
        self.service_account_path = service_account_path
        self.folder_id = folder_id
        self.service = None
        self._authenticate()

    def _authenticate(self):
        try:
            if not os.path.exists(self.service_account_path):
                log.error(
                    f"[drive] Arquivo de credenciais não encontrado: {self.service_account_path}"
                )
                return

            creds = service_account.Credentials.from_service_account_file(
                self.service_account_path,
                scopes=["https://www.googleapis.com/auth/drive"],
            )
            self.service = build("drive", "v3", credentials=creds)
            log.info("[drive] Autenticado com sucesso")
        except Exception as e:
            log.error(f"[drive] Falha na autenticação: {e}")

    def upload_file(self, local_path: str, mime_type: str = "application/pdf") -> str:
        """Sobe um arquivo para a pasta configurada. Retorna o file_id."""
        if not self.service:
            log.warning("[drive] Serviço não inicializado. Upload cancelado.")
            return ""

        if not os.path.exists(local_path):
            log.warning(f"[drive] Arquivo local não encontrado: {local_path}")
            return ""

        filename = os.path.basename(local_path)

        try:
            # Verifica se já existe um arquivo com o mesmo nome para evitar duplicatas (opcional)
            # Para o Seeker, vamos permitir duplicatas ou versionamento do próprio Drive

            file_metadata = {"name": filename, "parents": [self.folder_id]}
            media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)

            file = (
                self.service.files()
                .create(
                    body=file_metadata,
                    media_body=media,
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute()
            )

            file_id = file.get("id")
            log.info(f"[drive] Upload concluído: {filename} (ID: {file_id})")
            return file_id

        except Exception as e:
            log.error(f"[drive] Erro no upload de {filename}: {e}")
            return ""

    def find_file_by_name(self, filename: str) -> str:
        """Busca um arquivo pelo nome na pasta específica. Retorna o ID."""
        if not self.service:
            return ""
        try:
            query = f"name = '{filename}' and '{self.folder_id}' in parents and trashed = false"
            results = (
                self.service.files().list(q=query, fields="files(id, name)").execute()
            )
            files = results.get("files", [])
            return files[0]["id"] if files else ""
        except Exception as e:
            log.error(f"[drive] Erro ao buscar {filename}: {e}")
            return ""

    def update_file(
        self, file_id: str, local_path: str, mime_type: str = "application/pdf"
    ):
        """Atualiza o conteúdo de um arquivo existente."""
        if not self.service or not file_id:
            return
        try:
            media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
            self.service.files().update(
                fileId=file_id, media_body=media, supportsAllDrives=True
            ).execute()
            log.info(f"[drive] Arquivo atualizado (ID: {file_id})")
        except Exception as e:
            log.error(f"[drive] Erro ao atualizar {file_id}: {e}")

    def upload_content(
        self, content: str, filename: str, mime_type: str = "text/csv"
    ) -> str:
        """Cria um arquivo no Drive a partir de uma string."""
        if not self.service:
            return ""

        # Salva temporariamente
        temp_path = os.path.join("data", filename)
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)

        file_id = self.upload_file(temp_path, mime_type)

        # Limpa
        try:
            os.remove(temp_path)
        except:
            pass

        return file_id
