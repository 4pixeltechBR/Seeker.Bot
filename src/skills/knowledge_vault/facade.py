"""
KnowledgeVault Facade - Ponto de entrada simplificado para o bot
"""

import logging
from typing import List, Dict
from .vault_writer import ObsidianWriter
from .vault_searcher import VaultSearcher
from .analyzer import KnowledgeAnalyzer
from .prompts import COFRE_SYNTHESIS_SYSTEM, COFRE_SYNTHESIS_USER
from .extractors import (
    extract_from_images,
    extract_from_youtube,
    extract_from_site,
    extract_from_audio,
    fetch_github_readme,
    fetch_github_metadata,
    extract_from_zip,
    extract_from_mht,
)

log = logging.getLogger("seeker.knowledge_vault.facade")


class KnowledgeVault:
    def __init__(self, cascade_adapter, vlm_client=None, web_searcher=None, inbox_path=None):
        self.cascade = cascade_adapter
        self.vlm_client = vlm_client
        self.web_searcher = web_searcher
        if inbox_path:
            self.writer = ObsidianWriter(inbox_path=inbox_path)
        else:
            self.writer = ObsidianWriter()
        self.analyzer = KnowledgeAnalyzer(cascade_adapter)
        self.searcher = VaultSearcher()

    async def process_images(
        self, image_bytes_list: List[bytes], user_hint: str = ""
    ) -> str:
        """Processa prints/fotos para o Obsidian."""
        if not self.vlm_client:
            return "❌ VLM Client não configurado para processamento de imagem."

        try:
            raw_text = await extract_from_images(image_bytes_list, self.vlm_client)
            note_data = await self.analyzer.analyze_and_tag(
                raw_text, "print", user_hint=user_hint
            )

            # Escreve no cofre
            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="print",
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
            note_data = await self.analyzer.analyze_and_tag(
                transcript, "youtube", source_url=url, user_hint=user_hint
            )

            # Sobrescreve título com o do YouTube se o LLM não gerar um melhor
            final_title = (
                note_data.title if len(note_data.title) > 10 else metadata["title"]
            )

            self.writer.write_note(
                title=final_title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="youtube",
                source_url=url,
            )

            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return (
                f"✅ **Nota salva (YouTube): {final_title}**\n📂 Inbox/\n🏷️ {tags_str}"
            )
        except Exception as e:
            log.error(f"[facade] Erro ao processar YouTube: {e}")
            return f"❌ Erro ao processar YouTube: {str(e)[:100]}"

    async def process_site(self, url: str, user_hint: str = "") -> str:
        """Processa site genérico para o Obsidian."""
        try:
            raw_text = await extract_from_site(url)
            note_data = await self.analyzer.analyze_and_tag(
                raw_text, "site", source_url=url, user_hint=user_hint
            )

            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="site",
                source_url=url,
            )

            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return (
                f"✅ **Nota salva (Site): {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
            )
        except Exception as e:
            log.error(f"[facade] Erro ao processar site: {e}")
            return f"❌ Erro ao processar site: {str(e)[:100]}"

    # ─────────────────────────────────────────────────────────────────────
    # Novos métodos (Sprint 12.1 — Completar Cofre)
    # ─────────────────────────────────────────────────────────────────────

    def _derive_query(self, text: str, title: str = "") -> str:
        """Extrai query para pesquisa web: usa título ou primeiras 12 palavras."""
        if title and len(title.strip()) > 3:
            return title.strip()
        words = text.split()[:12]
        return " ".join(words).strip() or "pesquisa"

    async def _research(self, query: str, max_queries: int = 3) -> str:
        """
        Pesquisa bounded: 1 principal + até 2 derivadas.
        Se web_searcher indisponível, retorna "".
        """
        if not self.web_searcher:
            return ""

        try:
            queries = [query]
            if len(query) > 5:
                queries.append(f"{query} tutorial")
                queries.append(f"{query} o que é")
            queries = queries[:max_queries]

            context_parts = []
            for q in queries:
                try:
                    resp = await self.web_searcher.search(q, max_results=3)
                    if resp.results:
                        context_parts.append(resp.to_context(max_results=3))
                except Exception as e:
                    log.debug(f"[facade._research] Falha em '{q}': {e}")

            web_context = "\n\n".join(context_parts)
            return web_context[:3000] if web_context else ""
        except Exception as e:
            log.warning(f"[facade._research] Pesquisa web falhou: {e}")
            return ""

    async def process_text(self, text: str, user_hint: str = "") -> str:
        """Processa texto/ideia para o Obsidian."""
        try:
            query = self._derive_query(text)
            web_context = await self._research(query)

            note_data = await self.analyzer.analyze_and_tag(
                text, "ideia-victor", user_hint=user_hint,
                extra_meta={"web_context": web_context}
            )

            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="ideia-victor",
            )

            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva: {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar texto: {e}")
            return f"❌ Erro ao salvar nota: {str(e)[:100]}"

    async def process_audio_idea(self, audio_bytes: bytes) -> str:
        """Processa áudio como ideia para o Obsidian."""
        try:
            transcript = await extract_from_audio(audio_bytes)
            if not transcript:
                return "❌ Falha na transcrição do áudio."

            return await self.process_text(transcript, user_hint="(via áudio)")
        except Exception as e:
            log.error(f"[facade] Erro ao processar áudio-ideia: {e}")
            return f"❌ Erro ao processar áudio: {str(e)[:100]}"

    async def process_url(self, url: str, user_hint: str = "") -> str:
        """Roteador centralizado de URL."""
        if "youtube.com" in url or "youtu.be" in url:
            return await self.process_youtube(url, user_hint)
        elif "github.com/" in url:
            return await self.process_repo(url, user_hint)
        else:
            return await self.process_site(url, user_hint)

    async def process_repo(self, url: str, user_hint: str = "") -> str:
        """Processa repositório GitHub para o Obsidian."""
        try:
            import re
            match = re.search(r"github\.com/([^/]+)/([^/\?]+)", url)
            if not match:
                return "❌ URL do GitHub inválida."

            owner, repo = match.groups()

            # Fetch README (tenta múltiplos nomes/locais)
            raw_text = await fetch_github_readme(owner, repo)
            if not raw_text:
                raw_text = "[README não encontrado ou vazio]"

            # Metadados da API (stars, language, description, homepage, topics)
            api_meta = await fetch_github_metadata(owner, repo)

            # Pesquisa web sobre o repo
            query = f"{owner} {repo} github"
            web_context = await self._research(query)

            # Enriquece raw_text com metadados no topo
            if api_meta:
                meta_lines = []
                if api_meta.get("description"):
                    meta_lines.append(f"**Descrição:** {api_meta['description']}")
                if api_meta.get("language"):
                    meta_lines.append(f"**Linguagem:** {api_meta['language']}")
                if api_meta.get("stars", 0) > 0:
                    meta_lines.append(f"**⭐ Stars:** {api_meta['stars']:,}")
                if api_meta.get("topics"):
                    meta_lines.append(f"**Tópicos:** {', '.join(api_meta['topics'][:5])}")
                if api_meta.get("homepage"):
                    meta_lines.append(f"**Homepage:** {api_meta['homepage']}")

                if meta_lines:
                    raw_text = "\n".join(meta_lines) + "\n\n" + raw_text

            extra_meta = {
                "web_context": web_context,
                "repo_owner": owner,
                "repo_name": repo,
            }

            note_data = await self.analyzer.analyze_and_tag(
                raw_text, "repo", source_url=url, user_hint=user_hint,
                extra_meta=extra_meta
            )

            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="repo",
                source_url=url,
            )

            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva (Repo): {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar repo: {e}")
            return f"❌ Erro ao processar repositório: {str(e)[:100]}"

    async def process_pdf(self, pdf_bytes: bytes, user_hint: str = "") -> str:
        """Processa PDF para o Obsidian."""
        try:
            from .extractors import extract_from_pdf

            raw_text = await extract_from_pdf(pdf_bytes, self.vlm_client)
            if not raw_text:
                return "❌ Falha ao extrair conteúdo do PDF."

            query = self._derive_query(raw_text)
            web_context = await self._research(query)

            note_data = await self.analyzer.analyze_and_tag(
                raw_text, "pdf", user_hint=user_hint,
                extra_meta={"web_context": web_context}
            )

            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="pdf",
            )

            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva (PDF): {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar PDF: {e}")
            return f"❌ Erro ao processar PDF: {str(e)[:100]}"

    async def process_zip(self, zip_bytes: bytes, user_hint: str = "") -> str:
        """Processa arquivos de um ZIP consolidando-os em uma nota única do Obsidian."""
        try:
            raw_text = await extract_from_zip(zip_bytes, self.vlm_client)
            if not raw_text:
                return "❌ Falha ao extrair conteúdo do ZIP."

            query = self._derive_query(raw_text)
            web_context = await self._research(query)

            note_data = await self.analyzer.analyze_and_tag(
                raw_text, "zip", user_hint=user_hint,
                extra_meta={"web_context": web_context}
            )

            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="zip",
            )

            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva (ZIP): {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar ZIP: {e}")
            return f"❌ Erro ao processar ZIP: {str(e)[:100]}"

    async def process_mht(self, mht_bytes: bytes, user_hint: str = "") -> str:
        """Processa arquivo MHT convertendo para markdown e salvando no Obsidian."""
        try:
            raw_text = await extract_from_mht(mht_bytes)
            if not raw_text:
                return "❌ Falha ao extrair conteúdo do MHT."

            query = self._derive_query(raw_text)
            web_context = await self._research(query)

            note_data = await self.analyzer.analyze_and_tag(
                raw_text, "mht", user_hint=user_hint,
                extra_meta={"web_context": web_context}
            )

            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="mht",
            )

            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva (MHT): {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar MHT: {e}")
            return f"❌ Erro ao processar MHT: {str(e)[:100]}"

    async def search_and_answer(self, query: str, max_results: int = 5) -> str:
        """
        Busca no cofre via TF-IDF e sintetiza uma resposta com o LLM,
        citando as notas usadas. Se a síntese falhar, degrada para a
        lista simples de notas encontradas.
        """
        notes = self.searcher.search(query, max_results=max_results)
        if not notes:
            return f"🔍 Nenhuma nota encontrada para: *{query}*"

        context_parts = []
        for note in notes:
            tags_str = ", ".join(note.tags)
            context_parts.append(
                f"[Nota: {note.title}] (Tags: {tags_str})\n{note.body[:1000]}"
            )
        context = "\n\n".join(context_parts)

        sources_lines = []
        for note in notes:
            tags_str = " ".join([f"#{t}" for t in note.tags])
            sources_lines.append(f"📄 **{note.title}** — {tags_str}\n🔗 {note.path.name}")
        sources_block = "\n\n".join(sources_lines)

        try:
            response_dict = await self.cascade.call(
                role="fast",
                messages=[
                    {"role": "system", "content": COFRE_SYNTHESIS_SYSTEM},
                    {
                        "role": "user",
                        "content": COFRE_SYNTHESIS_USER.format(query=query, context=context),
                    },
                ],
            )
            answer = (
                response_dict.get("content", "").strip()
                if isinstance(response_dict, dict)
                else ""
            )
        except Exception as e:
            log.warning(f"[facade.search_and_answer] Síntese LLM falhou: {e}")
            answer = ""

        if not answer:
            return f"🔍 **Resultados no Cofre para: {query}**\n\n{sources_block}"

        return (
            f"🔍 **Cofre — {query}**\n\n"
            f"{answer}\n\n"
            f"━━━ Fontes ━━━\n{sources_block}"
        )

    # ─────────────────────────────────────────────────────────────────────
    # WhatsApp v3.12 Phase 1b/1c — novos processadores
    # ─────────────────────────────────────────────────────────────────────

    async def process_docx(self, docx_bytes: bytes, user_hint: str = "") -> str:
        """Processa DOCX: extrai texto, analisa e grava no cofre."""
        try:
            from .extractors import extract_from_docx
            text = await extract_from_docx(docx_bytes)
            if not text or text.startswith("["):
                return f"❌ Falha ao extrair DOCX: {text}"

            if self.cascade is None:
                path = self.writer.write_note(
                    title=user_hint or "Documento DOCX",
                    body=text,
                    tags=["docx"],
                    source_type="docx",
                )
                tags_str = " ".join([f"#{t}" for t in ["docx"]])
                return f"✅ **Nota salva (DOCX): {path.stem}**\n📂 {path.parent}\n🏷️ {tags_str}"

            query = self._derive_query(text)
            web_context = await self._research(query)
            note_data = await self.analyzer.analyze_and_tag(
                text, "docx", user_hint=user_hint,
                extra_meta={"web_context": web_context}
            )
            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="docx",
            )
            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva (DOCX): {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar DOCX: {e}")
            return f"❌ Erro ao processar DOCX: {str(e)[:100]}"

    async def process_xlsx(self, xlsx_bytes: bytes, user_hint: str = "") -> str:
        """Processa XLSX: extrai sheets, analisa e grava no cofre."""
        try:
            from .extractors import extract_from_xlsx
            text = await extract_from_xlsx(xlsx_bytes)
            if not text or text.startswith("["):
                return f"❌ Falha ao extrair XLSX: {text}"

            if self.cascade is None:
                path = self.writer.write_note(
                    title=user_hint or "Planilha XLSX",
                    body=text,
                    tags=["xlsx"],
                    source_type="xlsx",
                )
                return f"✅ **Nota salva (XLSX): {path.stem}**\n📂 {path.parent}"

            query = self._derive_query(text)
            web_context = await self._research(query)
            note_data = await self.analyzer.analyze_and_tag(
                text, "xlsx", user_hint=user_hint,
                extra_meta={"web_context": web_context}
            )
            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="xlsx",
            )
            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva (XLSX): {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar XLSX: {e}")
            return f"❌ Erro ao processar XLSX: {str(e)[:100]}"

    async def process_pptx(self, pptx_bytes: bytes, user_hint: str = "") -> str:
        """Processa PPTX: extrai slides, analisa e grava no cofre."""
        try:
            from .extractors import extract_from_pptx
            text = await extract_from_pptx(pptx_bytes)
            if not text or text.startswith("["):
                return f"❌ Falha ao extrair PPTX: {text}"

            if self.cascade is None:
                path = self.writer.write_note(
                    title=user_hint or "Apresentação PPTX",
                    body=text,
                    tags=["pptx"],
                    source_type="pptx",
                )
                return f"✅ **Nota salva (PPTX): {path.stem}**\n📂 {path.parent}"

            query = self._derive_query(text)
            web_context = await self._research(query)
            note_data = await self.analyzer.analyze_and_tag(
                text, "pptx", user_hint=user_hint,
                extra_meta={"web_context": web_context}
            )
            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="pptx",
            )
            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva (PPTX): {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar PPTX: {e}")
            return f"❌ Erro ao processar PPTX: {str(e)[:100]}"

    async def process_vcard(self, vcf_bytes: bytes, user_hint: str = "") -> str:
        """Processa vCard: parseia, gera nota markdown e grava no cofre."""
        try:
            from .extractors import extract_from_vcard
            text = await extract_from_vcard(vcf_bytes)
            if not text or text.startswith("["):
                return f"❌ Falha ao parsear vCard: {text}"

            if self.cascade is None:
                path = self.writer.write_note(
                    title=user_hint or "Contato vCard",
                    body=text,
                    tags=["vcard", "contato"],
                    source_type="vcard",
                )
                return f"✅ **Nota salva (vCard): {path.stem}**\n📂 {path.parent}"

            note_data = await self.analyzer.analyze_and_tag(
                text, "vcard", user_hint=user_hint
            )
            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="vcard",
            )
            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva (vCard): {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar vCard: {e}")
            return f"❌ Erro ao processar vCard: {str(e)[:100]}"

    async def process_location(
        self, lat: float, lon: float, name: str = "", address: str = ""
    ) -> str:
        """Processa localização (lat/lon): reverse-geocoding + nota no cofre."""
        try:
            from .extractors import reverse_geocode
            if not address:
                try:
                    address = reverse_geocode(lat, lon)
                except Exception as e:
                    log.debug(f"[facade] reverse_geocode falhou: {e}")
                    address = f"{lat:.4f}, {lon:.4f}"

            title_name = name or address or f"{lat:.4f},{lon:.4f}"
            body = (
                f"# {title_name}\n\n"
                f"- **Latitude**: {lat}\n"
                f"- **Longitude**: {lon}\n"
                f"- **Endereço**: {address}\n"
            )

            path = self.writer.write_note(
                title=f"Localização: {title_name}",
                body=body,
                tags=["localização", "whatsapp"],
                source_type="location",
            )
            return f"✅ **Localização salva: {path.stem}**\n📂 {path.parent}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar localização: {e}")
            return f"❌ Erro ao processar localização: {str(e)[:100]}"

    async def process_video(self, video_bytes: bytes, user_hint: str = "") -> str:
        """Processa vídeo: extrai transcrição (e frames) e grava no cofre."""
        try:
            from .extractors import extract_from_video
            text = await extract_from_video(video_bytes, vlm_client=self.vlm_client)
            if not text or text.startswith("["):
                return f"❌ Falha ao extrair conteúdo do vídeo: {text}"

            if self.cascade is None:
                path = self.writer.write_note(
                    title=user_hint or "Vídeo",
                    body=text,
                    tags=["vídeo"],
                    source_type="video",
                )
                return f"✅ **Nota salva (Vídeo): {path.stem}**\n📂 {path.parent}"

            query = self._derive_query(text)
            web_context = await self._research(query)
            note_data = await self.analyzer.analyze_and_tag(
                text, "video", user_hint=user_hint,
                extra_meta={"web_context": web_context}
            )
            self.writer.write_note(
                title=note_data.title,
                body=note_data.content_body,
                tags=note_data.tags,
                source_type="video",
            )
            tags_str = " ".join([f"#{t}" for t in note_data.tags])
            return f"✅ **Nota salva (Vídeo): {note_data.title}**\n📂 Inbox/\n🏷️ {tags_str}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar vídeo: {e}")
            return f"❌ Erro ao processar vídeo: {str(e)[:100]}"

    async def process_sticker(self, source_label: str = "Sticker") -> str:
        """Registra um sticker (sem texto extraível) como nota-marcador."""
        try:
            body = (
                f"🎨 **{source_label}** — ignorado (sticker não contém "
                f"texto extraível).\n"
            )
            path = self.writer.write_note(
                title=f"Sticker: {source_label}",
                body=body,
                tags=["sticker", "whatsapp"],
                source_type="sticker",
            )
            return f"✅ **Sticker registrado: {path.stem}**\n📂 {path.parent}"
        except Exception as e:
            log.error(f"[facade] Erro ao registrar sticker: {e}")
            return f"❌ Erro ao registrar sticker: {str(e)[:100]}"

    async def process_poll(
        self, question: str, options: list, votes: dict | None = None
    ) -> str:
        """Processa enquete do WhatsApp: grava dados crus como tabela markdown."""
        try:
            votes = votes or {}
            total = sum(
                v for v in votes.values() if isinstance(v, (int, float))
            )
            lines = [
                f"# Enquete: {question}",
                "",
                "| Opção | Votos |",
                "|---|---|",
            ]
            for i, opt in enumerate(options):
                v = votes.get(str(i), votes.get(opt, 0))
                if not isinstance(v, (int, float)):
                    v = 0
                pct = f" ({v / total * 100:.0f}%)" if total > 0 else ""
                lines.append(f"| {opt} | {v}{pct} |")
            if total > 0:
                lines.append(f"\n**Total**: {int(total)} votos")
            body = "\n".join(lines)
            path = self.writer.write_note(
                title=f"Enquete: {question[:60]}",
                body=body,
                tags=["enquete", "whatsapp", "poll"],
                source_type="poll",
            )
            return f"✅ **Enquete salva: {path.stem}**\n📂 {path.parent}"
        except Exception as e:
            log.error(f"[facade] Erro ao processar enquete: {e}")
            return f"❌ Erro ao processar enquete: {str(e)[:100]}"
