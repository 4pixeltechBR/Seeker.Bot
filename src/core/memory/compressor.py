"""
Seeker.Bot — Session Compressor
src/core/memory/compressor.py

Quando a janela de sessão cresce além de N turns, comprime o histórico
antigo num resumo denso ("super info dense, no filler") e mantém só
as últimas trocas intactas.

Inspirado no Session Memory do Claude Code:
template fixo com seções State/Task/Errors/Learnings.

Resultado: contexto sempre cabe no prompt sem poluir, conversa longa
não degrada qualidade do modelo.
"""

import logging
from src.providers.base import LLMRequest, invoke_with_fallback
from config.models import ModelRouter, CognitiveRole

log = logging.getLogger("seeker.memory.compressor")

COMPRESSION_PROMPT = """Comprima este histórico de conversa num resumo operacional ultra-denso.

REGRAS:
- Máximo 500 caracteres
- Zero filler, zero repetição
- Preserve: decisões tomadas, fatos aprendidos, tarefas pendentes, erros encontrados
- Descarte: saudações, confirmações, reformulações

Use este template (preencha só seções relevantes, omita vazias):

[Estado] O que está acontecendo agora
[Tarefas] O que foi pedido e está pendente
[Decisões] O que foi decidido
[Erros] Problemas encontrados
[Aprendizados] Fatos novos sobre o usuário/contexto

HISTÓRICO:
{history}

RESUMO DENSO:"""


class SessionCompressor:
    """
    Comprime sessões longas em resumo denso.
    Usa CognitiveRole.FAST (grátis, 40 RPM) — compressão é operação barata.
    """

    def __init__(
        self,
        model_router: ModelRouter,
        api_keys: dict[str, str],
        compress_after_turns: int = 16,
        keep_recent_turns: int = 6,
    ):
        self.model_router = model_router
        self.api_keys = api_keys
        self.compress_after_turns = compress_after_turns
        self.keep_recent_turns = keep_recent_turns
        self._summaries: dict[str, str] = {}

    async def maybe_compress(
        self, session_id: str, turns: list[dict]
    ) -> list[dict]:
        """
        Se turns > threshold, comprime antigos e retorna lista reduzida.
        Senão, retorna original sem mudança.
        """
        if len(turns) <= self.compress_after_turns:
            return turns

        recent = turns[-self.keep_recent_turns:]
        old = turns[:-self.keep_recent_turns]

        history_text = self._format_for_compression(old)

        try:
            summary = await self._compress(history_text)
            self._summaries[session_id] = summary
            log.info(
                f"[compressor] '{session_id}' comprimida: "
                f"{len(old)} turns → {len(summary)} chars"
            )
        except Exception as e:
            log.warning(f"[compressor] Falha, mantendo cache cheio: {e}")
            summary = self._summaries.get(session_id)
            if not summary:
                return turns

        compressed_turn = {
            "role": "system",
            "content": f"[CONTEXTO COMPRIMIDO]\n{summary}",
        }
        return [compressed_turn] + recent

    def get_summary(self, session_id: str) -> str | None:
        return self._summaries.get(session_id)

    async def _compress(self, history_text: str) -> str:
        prompt = COMPRESSION_PROMPT.format(history=history_text)
        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            system="Comprima informação. Ultra-denso. Máximo 500 caracteres.",
            temperature=0.1,
            max_tokens=256,
        )
        resp = await invoke_with_fallback(
            CognitiveRole.FAST, req,
            self.model_router, self.api_keys,
        )
        return resp.text.strip()

    def _format_for_compression(self, turns: list[dict]) -> str:
        lines = []
        for turn in turns:
            role = "User" if turn["role"] == "user" else "Bot"
            lines.append(f"{role}: {turn['content'][:200]}")
        return "\n".join(lines)

    def serialize_state(self) -> dict:
        return {"summaries": self._summaries}

    def load_state(self, state: dict):
        self._summaries = state.get("summaries", {})
