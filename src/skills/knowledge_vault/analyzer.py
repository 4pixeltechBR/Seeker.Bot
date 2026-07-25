"""
Analyzer v2.0 — Roteamento por tipo de fonte, markdown especializado.
"""

import json
import logging
from typing import List
from dataclasses import dataclass
from .detectors import detect_content_class
from .prompts import (
    ANALYSIS_PROMPT_SYSTEM,
    ANALYSIS_PROMPT_USER,
    IDEA_PROMPT_SYSTEM,
    IDEA_PROMPT_USER,
    YOUTUBE_PROMPT_SYSTEM,
    YOUTUBE_PROMPT_USER,
    SITE_PROMPT_SYSTEM,
    SITE_PROMPT_USER,
    OCR_ENRICH_PROMPT_SYSTEM,
    OCR_ENRICH_PROMPT_USER,
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
    source_type: str = ""  # Preservado para o writer usar prefixos


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

        Antes de rotear, aplica heuristicas deterministas em raw_text via
        detectors.detect_content_class(). Se confianca for alta (>0.6) e
        source_type for de documento, substitui para 'prompt'. Em qualquer
        caso, enriquece extra_meta com detected_company/model/tools/tags.
        """
        extra_meta = extra_meta or {}

        # ── Deteccao heuristica pre-LLM (Fase 4 Promptograph) ──
        if raw_text and len(raw_text) > 200:
            try:
                detection = detect_content_class(raw_text, source_type)
                detected_meta = detection.as_meta()
                # Merge nao-destrutivo: detector so adiciona chaves novas
                for k, v in detected_meta.items():
                    if k not in extra_meta:
                        extra_meta[k] = v
                # Override de source_type para prompts com confianca alta
                if (
                    detection.content_class == "prompt"
                    and detection.confidence > 0.6
                    and source_type in ("pdf", "site", "repo", "print", "ocr", "text")
                ):
                    source_type = "prompt"
                    logging.getLogger(__name__).info(
                        f"[analyzer] source_type override -> 'prompt' "
                        f"(conf={detection.confidence:.2f}, company={detection.company})"
                    )
            except Exception as e:
                logging.getLogger(__name__).debug(
                    f"[analyzer] detector falhou (seguindo normal): {e}"
                )

        if source_type == "ideia-victor":
            return await self._analyze_idea(raw_text, extra_meta)
        elif source_type == "prompt":
            # Override pela detector heuristica - roteia como prompt de IA
            return await self._analyze_prompt(raw_text, extra_meta)
        elif source_type == "youtube":
            return await self._analyze_youtube(raw_text, source_url, extra_meta)
        elif source_type == "site":
            return await self._analyze_site(raw_text, source_url, extra_meta)
        elif source_type == "repo":
            return await self._analyze_repo(raw_text, source_url, extra_meta)
        elif source_type == "pdf":
            return await self._analyze_pdf(raw_text, extra_meta)
        elif source_type in ("print", "ocr"):
            return await self._analyze_ocr(raw_text, extra_meta)
        else:
            # Fallback generico (nota de texto, etc.)
            return await self._analyze_generic(
                raw_text, source_type, source_url, user_hint, extra_meta
            )

    # ── Especialistas ─────────────────────────────────────────────────

    async def _analyze_idea(self, raw_text: str, meta: dict = None) -> NoteData:
        """Desenvolvedor de ideias."""
        meta = meta or {}
        web_context = meta.get("web_context", "")
        web_snippet = f"\n\nOBS. DO CONTEXTO WEB:\n{web_context}" if web_context else ""

        prompt_user = IDEA_PROMPT_USER.format(raw_text=raw_text[:6000] + web_snippet)
        data = await self._call_llm(IDEA_PROMPT_SYSTEM, prompt_user)

        tags = data.get("tags", [])
        if "ideia-victor" not in tags:
            tags.insert(0, "ideia-victor")

        note = NoteData(
            title=data.get("title", "Ideia sem titulo"),
            summary=data.get("summary", ""),
            tags=tags,
            key_insights=data.get("key_insights", []),
            category="Ideia",
            related_topics=data.get("related_topics", []),
            source_type="ideia-victor",
        )
        note.content_body = self._build_idea_body(note, web_context)
        return note

    async def _analyze_youtube(
        self, raw_text: str, source_url: str, meta: dict
    ) -> NoteData:
        """Curador de videos do YouTube."""
        web_context = meta.get("web_context", "")
        web_snippet = f"\n\nOBS. DO CONTEXTO WEB:\n{web_context}" if web_context else ""

        prompt_user = YOUTUBE_PROMPT_USER.format(
            raw_text=raw_text[:10000] + web_snippet,
            source_url=source_url,
            video_title=meta.get("title", "Desconhecido"),
            channel=meta.get("channel", "Desconhecido"),
            duration=self._format_duration(meta.get("duration")),
        )
        data = await self._call_llm(YOUTUBE_PROMPT_SYSTEM, prompt_user)

        note = NoteData(
            title=data.get("title", meta.get("title", "Video sem titulo")),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            key_insights=data.get("key_insights", []),
            category=data.get("category", "Video"),
            related_topics=data.get("related_topics", []),
            source_type="youtube",
        )
        note.content_body = self._build_youtube_body(note, source_url, meta, web_context)
        return note

    async def _analyze_site(
        self, raw_text: str, source_url: str, meta: dict
    ) -> NoteData:
        """Pesquisador web para artigos."""
        web_context = meta.get("web_context", "")
        web_snippet = f"\n\nOBS. DO CONTEXTO WEB:\n{web_context}" if web_context else ""

        prompt_user = SITE_PROMPT_USER.format(
            raw_text=raw_text[:12000] + web_snippet,
            source_url=source_url,
            page_title=meta.get("title", ""),
            author=meta.get("author", "Desconhecido"),
            description=meta.get("description", ""),
        )
        data = await self._call_llm(SITE_PROMPT_SYSTEM, prompt_user)

        note = NoteData(
            title=data.get("title", meta.get("title", "Artigo sem titulo")),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            key_insights=data.get("key_insights", []),
            category=data.get("category", "Artigo"),
            related_topics=data.get("related_topics", []),
            source_type="site",
        )
        note.content_body = self._build_site_body(note, source_url, meta, web_context)
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
            data = await self._call_llm(
                ANALYSIS_PROMPT_SYSTEM,
                ANALYSIS_PROMPT_USER.format(
                    source_type="print",
                    source_url="",
                    user_hint="",
                    raw_text=raw_text[:8000],
                ),
            )

        note = NoteData(
            title=data.get("title", "Print sem titulo"),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            key_insights=data.get("key_insights", []),
            category=data.get("category", "Print"),
            related_topics=data.get("related_topics", []),
            source_type="print",
        )
        note.content_body = self._build_generic_body(note)
        return note

    async def _analyze_generic(
        self, raw_text: str, source_type: str, source_url: str, user_hint: str, extra_meta: dict = None
    ) -> NoteData:
        """Fallback generico."""
        extra_meta = extra_meta or {}
        web_context = extra_meta.get("web_context", "")
        web_snippet = f"\n\nOBS. DO CONTEXTO WEB:\n{web_context}" if web_context else ""

        prompt_user = ANALYSIS_PROMPT_USER.format(
            source_type=source_type,
            source_url=source_url,
            user_hint=user_hint,
            raw_text=raw_text[:8000] + web_snippet,
        )
        data = await self._call_llm(ANALYSIS_PROMPT_SYSTEM, prompt_user)

        note = NoteData(
            title=data.get("title", "Nota sem titulo"),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            key_insights=data.get("key_insights", []),
            category=data.get("category", "Geral"),
            related_topics=data.get("related_topics", []),
            source_type=source_type,
        )
        note.content_body = self._build_generic_body(note, web_context)
        return note

    async def _analyze_repo(self, raw_text: str, source_url: str, meta: dict) -> NoteData:
        """Analista de repositórios GitHub."""
        web_context = meta.get("web_context", "")
        web_snippet = f"\n\nOBS. DO CONTEXTO WEB:\n{web_context}" if web_context else ""
        repo_owner = meta.get("repo_owner", "")
        repo_name = meta.get("repo_name", "")

        prompt_user = SITE_PROMPT_USER.format(
            raw_text=raw_text[:12000] + web_snippet,
            source_url=source_url,
            page_title=f"{repo_owner}/{repo_name}",
            author=repo_owner or "Desconhecido",
            description="Repositório GitHub",
        )
        data = await self._call_llm(SITE_PROMPT_SYSTEM, prompt_user)

        note = NoteData(
            title=data.get("title", f"{repo_owner}/{repo_name}"),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            key_insights=data.get("key_insights", []),
            category=data.get("category", "Repositório"),
            related_topics=data.get("related_topics", []),
            source_type="repo",
        )
        note.content_body = self._build_site_body(note, source_url, meta, web_context)
        return note

    async def _analyze_pdf(self, raw_text: str, meta: dict) -> NoteData:
        """Analista de PDFs."""
        web_context = meta.get("web_context", "")
        web_snippet = f"\n\nOBS. DO CONTEXTO WEB:\n{web_context}" if web_context else ""

        prompt_user = ANALYSIS_PROMPT_USER.format(
            source_type="pdf",
            source_url="",
            user_hint="",
            raw_text=raw_text[:12000] + web_snippet,
        )
        data = await self._call_llm(ANALYSIS_PROMPT_SYSTEM, prompt_user)

        note = NoteData(
            title=data.get("title", "PDF sem titulo"),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            key_insights=data.get("key_insights", []),
            category=data.get("category", "Documento"),
            related_topics=data.get("related_topics", []),
            source_type="pdf",
        )
        note.content_body = self._build_generic_body(note, web_context)
        return note

    async def _analyze_prompt(self, raw_text: str, meta: dict) -> NoteData:
        """Analista especial para system prompts de IA detectados pela heuristica.

        Aproveita os detected_company/model/tools/tags ja setados em extra_meta
        pelo detectors.detect_content_class(). O LLM continua responsavel por
        title/summary/key_insights, mas ja recebe o contexto e tem hint de
        category='Prompt de IA'.
        """
        detected_company = meta.get("detected_company", "")
        detected_model = meta.get("detected_model", "")
        detected_tools = meta.get("detected_tools", [])
        detected_tags = meta.get("detected_xml_tags", [])
        detected_persona = meta.get("detected_persona", "")
        confidence = meta.get("detected_confidence", 0.0)

        hint = (
            f"Conteudo detectado como SYSTEM PROMPT de IA (confianca={confidence:.0%}).\n"
            f"Empresa: {detected_company or '?'}\n"
            f"Modelo: {detected_model or '?'}\n"
            f"Persona: {detected_persona or '?'}\n"
            f"Tools: {', '.join(detected_tools) or 'none'}\n"
            f"XML tags: {', '.join(detected_tags[:10]) or 'none'}\n"
        )
        prompt_user = ANALYSIS_PROMPT_USER.format(
            source_type="prompt",
            source_url="",
            user_hint=hint,
            raw_text=raw_text[:12000],
        )
        data = await self._call_llm(ANALYSIS_PROMPT_SYSTEM, prompt_user)

        tags = data.get("tags", [])
        if "prompt-ia" not in [t.lower() for t in tags]:
            tags.insert(0, "prompt-ia")
        if detected_company:
            company_tag = detected_company.lower().replace(" ", "-")
            if company_tag not in [t.lower() for t in tags]:
                tags.insert(1, company_tag)

        note = NoteData(
            title=data.get("title", f"System Prompt - {detected_company or 'unknown'}"),
            summary=data.get("summary", ""),
            tags=tags,
            key_insights=data.get("key_insights", []),
            category=data.get("category", "Prompt de IA"),
            related_topics=data.get("related_topics", []),
            source_type="prompt",
        )
        # Add detector markers em extra meta para downstream (writer/search)
        meta["detected_score_breakdown"] = meta.get("detected_score_breakdown", {})
        note.content_body = self._build_prompt_body(note, detected_company,
                                                    detected_model, detected_tools,
                                                    detected_tags)
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
            response = (
                response_dict.get("content", "")
                if isinstance(response_dict, dict)
                else ""
            )

            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]

            return json.loads(cleaned.strip())

        except json.JSONDecodeError as e:
            log.error(
                f"[analyzer] JSON invalido do LLM: {e}. Response: {response[:200]}"
            )
            # Fallback defensivo — o LLM retornou texto explicativo em vez de JSON
            # (ex: VLM falhou e o LLM nao tem OCR real para processar)
            return {
                "title": "Nota sem titulo",
                "summary": response[:500]
                if response
                else "Conteudo nao pode ser extraido.",
                "tags": [],
                "key_insights": [],
                "category": "Geral",
                "related_topics": [],
            }
        except Exception as e:
            log.error(f"[analyzer] Erro na chamada LLM: {e}")
            raise

    # ── Markdown Builders ─────────────────────────────────────────────

    def _build_idea_body(self, note: NoteData, web_context: str = "") -> str:
        lines = [f"## Ideia\n{note.summary}\n"]

        if note.key_insights:
            lines.append("## Desenvolvimento")
            for insight in note.key_insights:
                lines.append(f"- {insight}")
            lines.append("")

        if note.related_topics:
            lines.append("## Conexoes")
            for topic in note.related_topics:
                lines.append(f"- [[{topic}]]")
            lines.append("")

        if web_context:
            lines.append("## Contexto Adicional (Web)")
            lines.append(web_context[:1500])
            lines.append("")

        connections = self._find_connections(note)
        if connections:
            lines.append("## Notas Relacionadas no Cofre")
            for conn in connections:
                lines.append(f"- [[{conn}]]")
            lines.append("")

        return "\n".join(lines)

    def _build_youtube_body(self, note: NoteData, source_url: str, meta: dict, web_context: str = "") -> str:
        lines = []

        channel = meta.get("channel", "Desconhecido")
        duration = self._format_duration(meta.get("duration"))
        views = meta.get("view_count")
        published = meta.get("upload_date", "")
        if published and len(published) == 8:
            published = f"{published[6:8]}/{published[4:6]}/{published[0:4]}"

        lines.append("## Sobre o Video")
        lines.append(f"- **Canal:** {channel}")
        if duration:
            lines.append(f"- **Duracao:** {duration}")
        if views:
            lines.append(f"- **Visualizacoes:** {views:,}".replace(",", "."))
        if published:
            lines.append(f"- **Publicado em:** {published}")
        lines.append(f"- **URL:** {source_url}")
        lines.append("")

        lines.append(f"## Resumo\n{note.summary}\n")

        if note.key_insights:
            lines.append("## Insights Chave")
            for insight in note.key_insights:
                lines.append(f"- {insight}")
            lines.append("")

        if note.related_topics:
            lines.append("## Fontes e Referencias Citadas")
            for topic in note.related_topics:
                lines.append(f"- {topic}")
            lines.append("")

        if web_context:
            lines.append("## Contexto Adicional (Web)")
            lines.append(web_context[:1500])
            lines.append("")

        connections = self._find_connections(note)
        if connections:
            lines.append("## Notas Relacionadas no Cofre")
            for conn in connections:
                lines.append(f"- [[{conn}]]")
            lines.append("")

        return "\n".join(lines)

    def _build_site_body(self, note: NoteData, source_url: str, meta: dict, web_context: str = "") -> str:
        lines = []

        author = meta.get("author", "")
        description = meta.get("description", "")

        lines.append("## Contexto do Artigo")
        if author:
            lines.append(f"- **Autor:** {author}")
        lines.append(f"- **Fonte:** {source_url}")
        if description:
            lines.append(f"- **Descricao:** {description}")
        lines.append("")

        lines.append(f"## Pontos Principais\n{note.summary}\n")

        if note.key_insights:
            lines.append("## O que aprendi")
            for insight in note.key_insights:
                lines.append(f"- {insight}")
            lines.append("")

        if note.related_topics:
            lines.append("## Fontes Citadas no Artigo")
            for topic in note.related_topics:
                lines.append(f"- {topic}")
            lines.append("")

        if web_context:
            lines.append("## Contexto Adicional (Web)")
            lines.append(web_context[:1500])
            lines.append("")

        connections = self._find_connections(note)
        if connections:
            lines.append("## Notas Relacionadas no Cofre")
            for conn in connections:
                lines.append(f"- [[{conn}]]")
            lines.append("")

        return "\n".join(lines)

    def _build_prompt_body(
        self, note: NoteData, company: str, model: str,
        tools: list[str], xml_tags: list[str],
    ) -> str:
        """Body markdown especial para system prompts de IA detectados."""
        lines = [f"## Resumo Executivo\n{note.summary}\n"]
        if note.category:
            lines.append(f"**Categoria:** {note.category}\n")

        if note.key_insights:
            lines.append("## Insights Chave")
            for insight in note.key_insights:
                lines.append(f"- {insight}")
            lines.append("")

        if company or model:
            lines.append("## Deteccao Heuristica")
            if company:
                lines.append(f"- Empresa: {company}")
            if model:
                lines.append(f"- Modelo: {model}")
            if tools:
                lines.append(f"- Tools: {', '.join(tools[:8])}")
            if xml_tags:
                lines.append(f"- XML tags: {', '.join(xml_tags[:10])}")
            lines.append("")

        if note.related_topics:
            lines.append(
                f"**Topicos Relacionados:** {', '.join(note.related_topics)}\n"
            )

        connections = self._find_connections(note)
        if connections:
            lines.append("## Conexoes (Segundo Cerebro)")
            for conn in connections:
                lines.append(f"- [[{conn}]]")
            lines.append("")

        return "\n".join(lines)

    def _build_generic_body(self, note: NoteData, web_context: str = "") -> str:
        lines = [f"## Resumo Executivo\n{note.summary}\n"]

        if note.key_insights:
            lines.append("## Insights Chave")
            for insight in note.key_insights:
                lines.append(f"- {insight}")
            lines.append("")

        if note.related_topics:
            lines.append(
                f"**Topicos Relacionados:** {', '.join(note.related_topics)}\n"
            )

        if web_context:
            lines.append("## Contexto Adicional (Web)")
            lines.append(web_context[:1500])
            lines.append("")

        connections = self._find_connections(note)
        if connections:
            lines.append("## Conexoes (Segundo Cerebro)")
            for conn in connections:
                lines.append(f"- [[{conn}]]")
            lines.append("")

        return "\n".join(lines)

    # ── Helpers ───────────────────────────────────────────────────────

    def _find_connections(self, note: NoteData) -> List[str]:
        """Busca notas relacionadas no cofre via tags."""
        try:
            related_notes = []
            for tag in note.tags[:3]:
                found = self.vault_searcher.search(tag, max_results=2)
                for f_note in found:
                    if f_note.title.lower() != note.title.lower():
                        related_notes.append(f_note.title)
            seen = set()
            return [x for x in related_notes if not (x in seen or seen.add(x))][:5]
        except Exception as e:
            log.warning(f"[analyzer] Erro ao buscar conexoes: {e}")
            return []

    def _format_duration(self, seconds) -> str:
        """Formata duracao em segundos para mm:ss ou hh:mm:ss."""
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
