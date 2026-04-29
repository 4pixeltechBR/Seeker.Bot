"""
KnowledgeVault Facade v2.0 — Orquestra todos os pipelines especializados.

Frentes:
- process_images(): Foto/Print → OCR + enriquecimento web → Obsidian
- process_audio_idea(): Áudio → Groq STT → IDEIA VICTOR → Obsidian
- process_youtube(): YouTube → Transcript + metadados ricos → Obsidian
- process_site(): Site → Scraping 15K + metadados página → Obsidian
- process_text(): Texto direto → Nota genérica → Obsidian
"""
import logging
from typing import List, Optional
from .vault_writer import ObsidianWriter
from .analyzer import KnowledgeAnalyzer
from .extractors import (
    extract_from_images,
    extract_from_youtube,
    extract_from_site,
    extract_from_audio,
)

log = logging.getLogger("seeker.knowledge_vault.facade")


class KnowledgeVault:
    def __init__(self, cascade_adapter, vlm_client=None, web_searcher=None):
        self.writer = ObsidianWriter()
        self.analyzer = KnowledgeAnalyzer(cascade_adapter)
        self.vlm_client = vlm_client
        self.web_searcher = web_searcher  # Injetado pelo bot para enriquecimento

    # ─────────────────────────────────────────────────────────────────
    # FOTO / PRINT → OCR + Enriquecimento Web
    # ─────────────────────────────────────────────────────────────────

    async def process_images(self, image_bytes_list: List[bytes], user_hint: str = "") -> str:
        """
        Foto/Print com /obsidian na legenda.
        Fluxo: VLM OCR → Busca web contextual → LLM → Obsidian
        """
        if not self.vlm_client:
            return "❌ VLM Client não configurado para OCR de imagem."

        try:
            ocr_text, extra_meta = await extract_from_images(
                image_bytes_list,
                self.vlm_client,
                web_searcher=self.web_searcher,
            )

            if user_hint:
                extra_meta["user_hint"] = user_hint

            note = await self.analyzer.analyze_and_tag(
                raw_text=ocr_text,
                source_type="print",
                extra_meta=extra_meta,
            )

            saved = self.writer.write_note(
                title=note.title,
                body=note.content_body,
                tags=note.tags,
                source_type="print",
            )

            tags_str = " ".join([f"#{t}" for t in note.tags[:5]])
            return (
                f"✅ <b>{note.title}</b>\n"
                f"📂 Inbox/ <code>{saved.name}</code>\n"
                f"🏷️ {tags_str}"
            )

        except Exception as e:
            log.error(f"[facade] Erro ao processar imagens: {e}", exc_info=True)
            return f"❌ Erro ao processar imagem: {str(e)[:150]}"

    # ─────────────────────────────────────────────────────────────────
    # ÁUDIO → IDEIA VICTOR (sempre)
    # ─────────────────────────────────────────────────────────────────

    async def process_audio_idea(self, audio_bytes: bytes) -> str:
        """
        Áudio enviado pelo Victor → sempre tratado como IDEIA VICTOR.
        Fluxo: Groq Whisper STT → LLM (prompt IDEIA) → Obsidian com tag ideia-victor
        """
        try:
            transcript = await extract_from_audio(audio_bytes)
            if not transcript or len(transcript.strip()) < 10:
                return "❌ Não consegui transcrever o áudio. Tente reenviar em formato OGG ou MP3."

            log.info(f"[facade] Áudio transcrito ({len(transcript)} chars) → processando como IDEIA VICTOR")

            note = await self.analyzer.analyze_and_tag(
                raw_text=transcript,
                source_type="ideia-victor",
            )

            saved = self.writer.write_note(
                title=note.title,
                body=note.content_body,
                tags=note.tags,
                source_type="ideia-victor",
            )

            tags_str = " ".join([f"#{t}" for t in note.tags[:5]])
            return (
                f"💡 <b>Ideia capturada!</b>\n\n"
                f"<b>{note.title}</b>\n\n"
                f"📂 Inbox/ <code>{saved.name}</code>\n"
                f"🏷️ {tags_str}"
            )

        except Exception as e:
            log.error(f"[facade] Erro ao processar áudio/ideia: {e}", exc_info=True)
            return f"❌ Erro ao processar áudio: {str(e)[:150]}"

    # ─────────────────────────────────────────────────────────────────
    # YOUTUBE → Transcript + Metadados ricos
    # ─────────────────────────────────────────────────────────────────

    async def process_youtube(self, url: str, user_hint: str = "") -> str:
        """
        Link do YouTube → transcrição + metadados ricos → Obsidian.
        """
        try:
            transcript, metadata = await extract_from_youtube(url)

            note = await self.analyzer.analyze_and_tag(
                raw_text=transcript,
                source_type="youtube",
                source_url=url,
                extra_meta=metadata,
            )

            # Frontmatter rico com metadados do vídeo
            extra_fm = {
                "canal": metadata.get("channel"),
                "duracao": self.analyzer._format_duration(metadata.get("duration")),
                "visualizacoes": metadata.get("view_count"),
                "publicado": metadata.get("upload_date"),
                "thumbnail": metadata.get("thumbnail"),
            }

            saved = self.writer.write_note(
                title=note.title,
                body=note.content_body,
                tags=note.tags,
                source_type="youtube",
                source_url=url,
                extra_frontmatter=extra_fm,
            )

            tags_str = " ".join([f"#{t}" for t in note.tags[:5]])
            channel = metadata.get("channel", "")
            duration = self.analyzer._format_duration(metadata.get("duration"))

            return (
                f"✅ <b>{note.title}</b>\n"
                f"📺 {channel}{f' · {duration}' if duration else ''}\n"
                f"📂 Inbox/ <code>{saved.name}</code>\n"
                f"🏷️ {tags_str}"
            )

        except Exception as e:
            log.error(f"[facade] Erro ao processar YouTube: {e}", exc_info=True)
            return f"❌ Erro ao processar YouTube: {str(e)[:150]}"

    # ─────────────────────────────────────────────────────────────────
    # SITE / ARTIGO → Scraping profundo + metadados
    # ─────────────────────────────────────────────────────────────────

    async def process_site(self, url: str, user_hint: str = "") -> str:
        """
        URL de site → scraping 15K chars + metadados da página → Obsidian.
        """
        try:
            page_text, page_metadata = await extract_from_site(url)

            if page_text.startswith("[Erro"):
                return f"❌ Não consegui acessar o site: {page_text}"

            note = await self.analyzer.analyze_and_tag(
                raw_text=page_text,
                source_type="site",
                source_url=url,
                extra_meta=page_metadata,
            )

            # Frontmatter rico com metadados da página
            extra_fm = {
                "autor": page_metadata.get("author"),
                "descricao_og": page_metadata.get("description"),
                "imagem_og": page_metadata.get("og_image"),
                "data_acesso": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
            }

            saved = self.writer.write_note(
                title=note.title,
                body=note.content_body,
                tags=note.tags,
                source_type="site",
                source_url=url,
                extra_frontmatter=extra_fm,
            )

            tags_str = " ".join([f"#{t}" for t in note.tags[:5]])
            author = page_metadata.get("author", "")

            return (
                f"✅ <b>{note.title}</b>\n"
                f"{'✍️ ' + author + chr(10) if author else ''}"
                f"📂 Inbox/ <code>{saved.name}</code>\n"
                f"🏷️ {tags_str}"
            )

        except Exception as e:
            log.error(f"[facade] Erro ao processar site: {e}", exc_info=True)
            return f"❌ Erro ao processar site: {str(e)[:150]}"

    # ─────────────────────────────────────────────────────────────────
    # TEXTO DIRETO → Nota genérica
    # ─────────────────────────────────────────────────────────────────

    async def process_text(self, text: str, user_hint: str = "") -> str:
        """
        /obsidian texto livre → nota genérica no Obsidian.
        """
        try:
            note = await self.analyzer.analyze_and_tag(
                raw_text=text,
                source_type="nota",
                user_hint=user_hint,
            )

            saved = self.writer.write_note(
                title=note.title,
                body=note.content_body,
                tags=note.tags,
                source_type="nota",
            )

            tags_str = " ".join([f"#{t}" for t in note.tags[:5]])
            return (
                f"✅ <b>{note.title}</b>\n"
                f"📂 Inbox/ <code>{saved.name}</code>\n"
                f"🏷️ {tags_str}"
            )

        except Exception as e:
            log.error(f"[facade] Erro ao processar texto: {e}", exc_info=True)
            return f"❌ Erro ao salvar nota: {str(e)[:150]}"

    # ─────────────────────────────────────────────────────────────────
    # Compatibilidade com código legado
    # ─────────────────────────────────────────────────────────────────

    async def process_audio(self, audio_bytes: bytes, user_hint: str = "") -> str:
        """Alias para process_audio_idea (áudio sempre é IDEIA VICTOR)."""
        return await self.process_audio_idea(audio_bytes)
