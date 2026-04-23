"""
Analyzer - Lógica de análise e tagueamento com LLM
"""
import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from .prompts import ANALYSIS_PROMPT_SYSTEM, ANALYSIS_PROMPT_USER
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
    content_body: str = "" # Final markdown body

class KnowledgeAnalyzer:
    def __init__(self, cascade_adapter):
        self.cascade = cascade_adapter
        self.vault_searcher = VaultSearcher() # Usado para graph enrichment

    async def analyze_and_tag(self, raw_text: str, source_type: str, source_url: str = "", user_hint: str = "") -> NoteData:
        """Processa o texto bruto via LLM para gerar metadados e resumo."""
        
        # 1. Chamada ao LLM (FAST tier)
        prompt_user = ANALYSIS_PROMPT_USER.format(
            source_type=source_type,
            source_url=source_url,
            user_hint=user_hint,
            raw_text=raw_text[:8000] # Limite de segurança
        )
        
        try:
            log.info(f"[analyzer] Analisando conteúdo de {source_type}...")
            response = await self.cascade.prompt(
                system_prompt=ANALYSIS_PROMPT_SYSTEM,
                user_prompt=prompt_user,
                role="fast"
            )
            
            # Limpeza básica de JSON (remover blocos de código se houver)
            cleaned_resp = response.strip()
            if cleaned_resp.startswith("```json"):
                cleaned_resp = cleaned_resp[7:-3].strip()
            elif cleaned_resp.startswith("```"):
                cleaned_resp = cleaned_resp[3:-3].strip()
                
            data = json.loads(cleaned_resp)
            
            note = NoteData(
                title=data.get("title", "Nota sem título"),
                summary=data.get("summary", ""),
                tags=data.get("tags", []),
                key_insights=data.get("key_insights", []),
                category=data.get("category", "Geral"),
                related_topics=data.get("related_topics", [])
            )
            
            # 2. Graph Enrichment (Wikilinks)
            note.content_body = self._build_markdown_body(note)
            
            # 3. Research Chain (opcional, pode ser feito fora ou aqui)
            # Por enquanto, focamos na nota base.
            
            return note
            
        except Exception as e:
            log.error(f"[analyzer] Erro na análise LLM: {e}")
            raise e

    def _build_markdown_body(self, note: NoteData) -> str:
        """Constrói o corpo final da nota em Markdown."""
        lines = []
        
        lines.append(f"## Resumo Executivo\n{note.summary}\n")
        
        if note.key_insights:
            lines.append("## 💡 Insights Chave")
            for insight in note.key_insights:
                lines.append(f"- {insight}")
            lines.append("")
            
        if note.related_topics:
            lines.append(f"**Tópicos Relacionados:** {', '.join(note.related_topics)}\n")

        # Seção de Conexões (Graph Enrichment)
        connections = self._find_connections(note)
        if connections:
            lines.append("## 🔗 Conexões (Segundo Cérebro)")
            for conn in connections:
                lines.append(f"- [[{conn}]]")
            lines.append("")

        return "\n".join(lines)

    def _find_connections(self, note: NoteData) -> List[str]:
        """Busca notas relacionadas no cofre baseada em tags comuns."""
        try:
            related_notes = []
            # Busca notas que compartilham pelo menos uma tag
            for tag in note.tags:
                found = self.vault_searcher.search(tag, max_results=3)
                for f_note in found:
                    if f_note.title.lower() != note.title.lower():
                        related_notes.append(f_note.title)
            
            # Remove duplicatas mantendo ordem
            seen = set()
            unique_conns = [x for x in related_notes if not (x in seen or seen.add(x))]
            
            return unique_conns[:5] # Limite de 5 conexões
        except Exception as e:
            log.warning(f"[analyzer] Erro ao buscar conexões: {e}")
            return []
