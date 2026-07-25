from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from config.models import CognitiveRole
from src.providers.base import LLMRequest, invoke_with_fallback

log = logging.getLogger("seeker.research_machine.synthesizer")

SYNTHESIS_SYSTEM = (
    "Você é um assistente de pesquisa que sintetiza conteúdo de vídeos do YouTube. "
    "Gere resumo estruturado, flashcards e infográfico textual (ASCII/emoji). "
    "Output em markdown PT-BR."
)

FLASHCARD_SYSTEM = (
    "Com base no conteúdo abaixo, gere flashcards no formato:\n"
    "**Pergunta:** ...\n**Resposta:** ...\n\n"
    "Separe cada flashcard com ---"
)


@dataclass
class SynthesisResult:
    summary_md: str
    flashcards: list[str] = field(default_factory=list)
    infographic: str = ""
    cost_usd: float = 0.0


class Synthesizer:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    async def synthesize(self, query: str, videos_context: str) -> SynthesisResult:
        user_prompt = (
            f"Pesquisa: {query}\n\n"
            f"Vídeos encontrados:\n{videos_context}\n\n"
            "Gere:\n"
            "1. ## Resumo Executivo (5 tópicos)\n"
            "2. ## Análise por Vídeo (bullet points)\n"
            "3. ## Insights e Conexões\n"
            "4. ## Flashcards (5 pares Q&A no formato **Pergunta:** ... **Resposta:** ... separados por ---)\n"
            "5. ## Infográfico ASCII"
        )
        req = LLMRequest(
            messages=[{"role": "user", "content": user_prompt}],
            system=SYNTHESIS_SYSTEM,
            temperature=0.3,
            max_tokens=4096,
        )
        try:
            resp = await invoke_with_fallback(
                CognitiveRole.SYNTHESIS, req,
                self.pipeline.model_router, self.pipeline.api_keys,
            )
        except Exception as e:
            log.error(f"[synthesizer] Falha: {e}")
            return SynthesisResult(summary_md=f"Erro na síntese: {e}")

        raw = resp.text.strip()
        cost = getattr(resp, "cost_usd", 0.0) or 0.0
        
        # Extrai flashcards e infográfico do response
        flashcards = self._extract_flashcards(raw)
        infographic = self._extract_infographic(raw)
        
        return SynthesisResult(
            summary_md=raw,
            flashcards=flashcards,
            infographic=infographic,
            cost_usd=cost
        )

    def _extract_flashcards(self, text: str) -> list[str]:
        """Extrai flashcards do formato **Pergunta:** ... **Resposta:** ... ---"""
        # Procura por padrão **Pergunta:** ... **Resposta:** ... ---
        pattern = r'\*\*Pergunta:\*\*\s*(.+?)\s*\*\*Resposta:\*\*\s*(.+?)(?=\n---|\n\*\*Pergunta:|\Z)'
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        flashcards = []
        for q, a in matches:
            q = q.strip()
            a = a.strip()
            if q and a:
                flashcards.append(f"**Pergunta:** {q}\n**Resposta:** {a}")
        return flashcards[:10]  # max 10

    def _extract_infographic(self, text: str) -> str:
        """Extrai bloco de infográfico ASCII (entre ```)."""
        # Procura blocos de código que pareçam infográficos
        blocks = re.findall(r'```(?:ascii|text)?\n(.+?)```', text, re.DOTALL)
        if blocks:
            return blocks[0].strip()
        # Fallback: procura por "## Infográfico" ou similar
        infographic_match = re.search(r'##\s*Infográfico[^\n]*\n(.+?)(?:\n## |\Z)', text, re.DOTALL | re.IGNORECASE)
        if infographic_match:
            return infographic_match.group(1).strip()
        return ""

    async def extracts_transcript(self, video_id: str) -> str:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["pt", "en"])
            return " ".join(t["text"] for t in transcript[:200])
        except Exception:
            return ""