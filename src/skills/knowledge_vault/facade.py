"""
KnowledgeVault Facade - Ponto de entrada simplificado para o bot
"""
import logging
from typing import List, Optional
from .vault_writer import ObsidianWriter
from .analyzer import KnowledgeAnalyzer
from .extractors import extract_from_images, extract_from_youtube, extract_from_site, extract_from_audio

log = logging.getLogger("seeker.knowledge_vault.facade")

class KnowledgeVault:
    def __init__(self, cascade_adapter, vlm_client=None):
        self.writer = ObsidianWriter()
        self.analyzer = KnowledgeAnalyzer(cascade_adapter)
        self.vlm_client = vlm_client

    async def process_images(self, image_bytes_list: List[bytes], user_hint: str = "") -> str:
        """Processa prints/fotos para o Obsidian."""
        if not self.vlm_client:
            return "❌ VLM Client não configurado para processamento de imagem."
            
        try:
            raw_text = await extract_from_images(image_bytes_list, self.vlm_client)
            note_data = await self.analyzer.analyze_and_tag(raw_text, "print", user_hint=user_hint)
            
            # Escreve no cofre
            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="print"
            )
            
            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva: {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar imagens: {e}")
            return f"❌ Erro ao processar imagens: {str(e)[:100]}"

    async def process_youtube(self, url: str, user_hint: str = "") -> str:
        """Processa link do YouTube para o Obsidian."""
        try:
            transcript, metadata = await extract_from_youtube(url)
            note_data = await self.analyzer.analyze_and_tag(transcript, "youtube", source_url=url, user_hint=user_hint)
            
            # Sobrescreve título com o do YouTube se o LLM não gerar um melhor
            final_title = note_data.title if len(note_data.title) > 10 else metadata["title"]
            
            self.writer.write_note(
                title=final_title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="youtube",
                source_url=url
            )
            
            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva (YouTube): {final_title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar YouTube: {e}")
            return f"❌ Erro ao processar YouTube: {str(e)[:100]}"

    async def process_site(self, url: str, user_hint: str = "") -> str:
        """Processa site genérico para o Obsidian."""
        try:
            raw_text = await extract_from_site(url)
            note_data = await self.analyzer.analyze_and_tag(raw_text, "site", source_url=url, user_hint=user_hint)
            
            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="site",
                source_url=url
            )
            
            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva (Site): {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar site: {e}")
            return f"❌ Erro ao processar site: {str(e)[:100]}"

    async def process_audio(self, audio_bytes: bytes, user_hint: str = "") -> str:
        """Processa transcrição de áudio para o Obsidian."""
        try:
            transcript = await extract_from_audio(audio_bytes)
            if not transcript:
                return "❌ Falha na transcrição do áudio."
                
            note_data = await self.analyzer.analyze_and_tag(transcript, "audio", user_hint=user_hint)
            
            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="audio"
            )
            
            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva (Áudio): {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar áudio: {e}")
            return f"❌ Erro ao processar áudio: {str(e)[:100]}"
