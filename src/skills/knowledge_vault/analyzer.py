"""
Analyzer v2.0 — Roteamento por tipo de fonte, markdown especializado.
"""
import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from .prompts import (
    ANALYSIS_PROMPT_SYSTEM, ANALYSIS_PROMPT_USER,
    IDEA_PROMPT_SYSTEM, IDEA_PROMPT_USER,
    YOUTUBE_PROMPT_SYSTEM, YOUTUBE_PROMPT_USER,
    SITE_PROMPT_SYSTEM, SITE_PROMPT_USER,
    OCR_ENRICH_PROMPT_SYSTEM, OCR_ENRICH_PROMPT_USER,
)
from .vault_searcher import VaultSearcher

log = logging.getLogger("seeker.knowledge_vault.analyzer")


@dataclass
class NoteData:
    title: str
    summary: str
    tags: List[str]
    key_insights: List[str]
    category: str
    related_topics: List[str]
    content_body: str = ""  # Final markdown body
    source_type: str = ""   # Preservado para o writer usar prefixos


class KnowledgeAnalyzer:
    def __init__(self, cascade_adapter):
        self.cascade = cascade_adapter
        self.vault_searcher = VaultSearcher()

    # ── Dispatcher ────────────────────────────────────────────────────

    async def analyze_and_tag(
        self,
        raw_text: str,
        source_type: str,
        source_url: str = "",
        user_hint: str = "",
        extra_meta: dict = None,
    ) -> NoteData:
        """
        Dispatcher central. Roteia para o prompt especializado por source_type.
        """
        extra_meta = extra_meta or {}

        if source_type == "ideia-victor":
            return await self._analyze_idea(raw_text)
        elif source_type == "youtube":
            return await self._analyze_youtube(raw_text, source_url, extra_meta)
        elif source_type == "site":
            return await self._analyze_site(raw_text, source_url, extra_meta)
        elif source_type in ("print", "ocr"):
            return await self._analyze_ocr(raw_text, extra_meta)
        else:
            # Fallback genérico (nota de texto, etc.)
            return await self._analyze_generic(raw_text, source_type, source_url, user_hint)

    # ── Especialistas ─────────────────────────────────────────────────

    async def _analyze_idea(self, raw_text: str) -> NoteData:
        """Desenvolvedor de ideias do Victor."""
        prompt_user = IDEA_PROMPT_USER.format(raw_text=raw_text[:6000])
        data = await self._call_llm(IDEA_PROMPT_SYSTEM, prompt_user)

        # Garante tag obrigatória
        tags = data.get("tags", [])
        if "ideia-victor" not in tags:
            tags.insert(0, "ideia-victor")

        note = NoteData(
            title=data.get("title", "Ideia sem título"),
            summary=data.get("summary", ""),
            tags=tags,
            key_insights=data.get("key_insights", []),
            category="Ideia",
            related_topics=data.get("related_topics", []),
            source_type="ideia-victor",
        )
        note.content_body = self._build_idea_body(note)
        return note

    async def _analyze_youtube(self, raw_text: str, source_url: str, meta: dict) -> NoteData:
        """Curador de vídeos do YouTube."""
        prompt_user = YOUTUBE_PROMPT_USER.format(
            raw_text=raw_text[:10000],
            source_url=source_url,
            video_title=meta.get("title", "Desconhecido"),
            channel=meta.get("channel", "Desconhecido"),
            duration=self._format_duration(meta.get("duration")),
        )
        data = await self._call_llm(YOUTUBE_PROMPT_SYSTEM, prompt_user)

        note = NoteData(
            title=data.get("title", meta.get("title", "Vídeo sem título")),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            key_insights=data.get("key_insights", []),
            category=data.get("category", "Vídeo"),
            related_topics=data.get("related_topics", []),
            source_type="youtube",
        )
        note.content_body = self._build_youtube_body(note, source_url, meta)
        return note

    async def _analyze_site(self, raw_text: str, source_url: str, meta: dict) -> NoteData:
        """Pesquisador web para artigos."""
        prompt_user = SITE_PROMPT_USER.format(
            raw_text=raw_text[:12000],
            source_url=source_url,
            page_title=meta.get("title", ""),
            author=meta.get("author", "Desconhecido"),
            description=meta.get("description", ""),
        )
        data = await self._call_llm(SITE_PROMPT_SYSTEM, prompt_user)

        note = NoteData(
            title=data.get("title", meta.get("title", "Artigo sem título")),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            key_insights=data.get("key_insights", []),
            category=data.get("category", "Artigo"),
            related_topics=data.get("related_topics", []),
            source_type="site",
        )
        note.content_body = self._build_site_body(note, source_url, meta)
        return note

    async def _analyze_ocr(self, raw_text: str, meta: dict) -> NoteData:
        """Analisa imagem com enriquecimento web opcional."""
        web_context = meta.get("web_context", "")
        
        if web_context:
            prompt_user = OCR_ENRICH_PROMPT_USER.format(
                ocr_text=raw_text[:6000],
                web_context=web_context[:3000],
            )
            data = await self._call_llm(OCR_ENRICH_PROMPT_SYSTEM, prompt_user)
        else:
            # Sem contexto web, usa o genérico
            data = await self._call_llm(
                ANALYSIS_PROMPT_SYSTEM,
                ANALYSIS_PROMPT_USER.format(
                    source_type="print",
                    source_url="",
                    user_hint="",
                    raw_text=raw_text[:8000],
                )
            )

        note = NoteData(
            title=data.get("title", "Print sem título"),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            key_insights=data.get("key_insights", []),
            category=data.get("category", "Print"),
            related_topics=data.get("related_topics", []),
            source_type="print",
        )
        note.content_body = self._build_generic_body(note)
        return note

    async def _analyze_generic(self, raw_text: str, source_type: str, source_url: str, user_hint: str) -> NoteData:
        """Fallback genérico."""
        prompt_user = ANALYSIS_PROMPT_USER.format(
            source_type=source_type,
            source_url=source_url,
            user_hint=user_hint,
            raw_text=raw_text[:8000],
        )
        data = await self._call_llm(ANALYSIS_PROMPT_SYSTEM, prompt_user)

        note = NoteData(
            title=data.get("title", "Nota sem título"),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            key_insights=data.get("key_insights", []),
            category=data.get("category", "Geral"),
            related_topics=data.get("related_topics", []),
            source_type=source_type,
        )
        note.content_body = self._build_generic_body(note)
        return note

    # ── LLM Call ──────────────────────────────────────────────────────

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> dict:
        """Chama o cascade adapter e parseia o JSON retornado."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = ""
        try:
            response_dict = await self.cascade.call(role="fast", messages=messages)
            response = response_dict.get("content", "") if isinstance(response_dict, dict) else ""

            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]

            return json.loads(cleaned.strip())

        except json.JSONDecodeError as e:
            log.error(f"[analyzer] JSON inválido do LLM: {e}. Response: {response[:200]}")
            # Fallback defensivo — o LLM retornou texto explicativo em vez de JSON
            # (ex: VLM falhou e o LLM não tem OCR real para processar)
            return {
                "title": "Nota sem título",
                "summary": response[:500] if response else "Conteúdo não pôde ser extraído.",
                "tags": [],
                "key_insights": [],
                "category": "Geral",
                "related_topics": [],
            }
        except Exception as e:
            log.error(f"[analyzer] Erro na chamada LLM: {e}")
            raise

    # ── Markdown Builders ─────────────────────────────────────────────

    def _build_idea_body(self, note: NoteData) -> str:
        lines = [f"## 💡 A Ideia\n{note.summary}\n"]

        if note.key_insights:
            lines.append("## 📋 Desenvolvimento")
            for insight in note.key_insights:
                lines.append(f"- {insight}")
            lines.append("")

        if note.related_topics:
            lines.append("## 🔗 Conexões")
            for topic in note.related_topics:
                lines.append(f"- [[{topic}]]")
            lines.append("")

        connections = self._find_connections(note)
        if connections:
            lines.append("## 📚 Notas Relacionadas no Cofre")
            for conn in connections:
                lines.append(f"- [[{conn}]]")
            lines.append("")

        return "\n".join(lines)

    def _build_youtube_body(self, note: NoteData, source_url: str, meta: dict) -> str:
        lines = []

        # Box de metadados
        channel = meta.get("channel", "Desconhecido")
        duration = self._format_duration(meta.get("duration"))
        views = meta.get("view_count")
        published = meta.get("upload_date", "")
        if published and len(published) == 8:
            published = f"{published[6:8]}/{published[4:6]}/{published[0:4]}"

        lines.append("## 📺 Sobre o Vídeo")
        lines.append(f"- 📺 **Canal:** {channel}")
        if duration:
            lines.append(f"- ⏱️ **Duração:** {duration}")
        if views:
            lines.append(f"- 👁️ **Visualizações:** {views:,}".replace(",", "."))
        if published:
            lines.append(f"- 📅 **Publicado em:** {published}")
        lines.append(f"- 🔗 **URL:** {source_url}")
        lines.append("")

        lines.append(f"## 🎯 Resumo\n{note.summary}\n")

        if note.key_insights:
            lines.append("## 💡 Insights Chave")
            for insight in note.key_insights:
                lines.append(f"- {insight}")
            lines.append("")

        if note.related_topics:
            lines.append("## 📚 Fontes e Referências Citadas")
            for topic in note.related_topics:
                lines.append(f"- {topic}")
            lines.append("")

        connections = self._find_connections(note)
        if connections:
            lines.append("## 🔗 Notas Relacionadas no Cofre")
            for conn in connections:
                lines.append(f"- [[{conn}]]")
            lines.append("")

        return "\n".join(lines)

    def _build_site_body(self, note: NoteData, source_url: str, meta: dict) -> str:
        lines = []

        author = meta.get("author", "")
        description = meta.get("description", "")

        lines.append("## 📰 Contexto do Artigo")
        if author:
            lines.append(f"- ✍️ **Autor:** {author}")
        lines.append(f"- 🔗 **Fonte:** {source_url}")
        if description:
            lines.append(f"- 📄 **Descrição:** {description}")
        lines.append("")

        lines.append(f"## 🎯 Pontos Principais\n{note.summary}\n")

        if note.key_insights:
            lines.append("## 💡 O que aprendi")
            for insight in note.key_insights:
                lines.append(f"- {insight}")
            lines.append("")

        if note.related_topics:
            lines.append("## 🔗 Fontes Citadas no Artigo")
            for topic in note.related_topics:
                lines.append(f"- {topic}")
            lines.append("")

        connections = self._find_connections(note)
        if connections:
            lines.append("## 📚 Notas Relacionadas no Cofre")
            for conn in connections:
                lines.append(f"- [[{conn}]]")
            lines.append("")

        return "\n".join(lines)

    def _build_generic_body(self, note: NoteData) -> str:
        lines = [f"## Resumo Executivo\n{note.summary}\n"]

        if note.key_insights:
            lines.append("## 💡 Insights Chave")
            for insight in note.key_insights:
                lines.append(f"- {insight}")
            lines.append("")

        if note.related_topics:
            lines.append(f"**Tópicos Relacionados:** {', '.join(note.related_topics)}\n")

        connections = self._find_connections(note)
        if connections:
            lines.append("## 🔗 Conexões (Segundo Cérebro)")
            for conn in connections:
                lines.append(f"- [[{conn}]]")
            lines.append("")

        return "\n".join(lines)

    # ── Helpers ───────────────────────────────────────────────────────

    def _find_connections(self, note: NoteData) -> List[str]:
        """Busca notas relacionadas no cofre via tags."""
        try:
            related_notes = []
            for tag in note.tags[:3]:  # Limita busca para as 3 primeiras tags
                found = self.vault_searcher.search(tag, max_results=2)
                for f_note in found:
                    if f_note.title.lower() != note.title.lower():
                        related_notes.append(f_note.title)
            seen = set()
            return [x for x in related_notes if not (x in seen or seen.add(x))][:5]
        except Exception as e:
            log.warning(f"[analyzer] Erro ao buscar conexões: {e}")
            return []

    def _format_duration(self, seconds) -> str:
        """Formata duração em segundos para mm:ss ou hh:mm:ss."""
        if not seconds:
            return ""
        try:
            seconds = int(seconds)
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            if h:
                return f"{h}h{m:02d}m{s:02d}s"
            return f"{m}:{s:02d}"
        except Exception:
            return str(seconds)
