"""
Seeker.Bot — Signature Guardrail
src/core/rate_limiting/signature.py

Evita loops redundantes de chamadas de APIs de busca *dentro do mesmo turno*
de raciocínio. NÃO deve bloquear pesquisas de turnos diferentes do usuário.

Critério de bloqueio:
  - Mesma assinatura (hash SHA-256) gerada MAIS DE UMA VEZ no mesmo turno
    de raciocínio (dentro do active loop de um único `process()` call).
  - Assinaturas de turnos anteriores expiram após TTL_SECONDS.
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("seeker.rate_limiting.signature")

# Hashes mais antigos que TTL_SECONDS são ignorados — não são loops, são
# pesquisas legítimas em novos turnos do usuário.
_TTL_SECONDS = 60  # 1 minuto é suficiente para cobrir um active loop


@dataclass
class _SignatureEntry:
    sig_hash: str
    timestamp: float = field(default_factory=time.monotonic)


class SignatureGuardrail:
    """
    Signature Guardrail — intercepta loops de busca/ação repetitivos
    dentro de um único ciclo de raciocínio (active loop).

    Escopo: detecta se o LLM gerou a *mesma* query de busca mais de uma
    vez dentro do mesmo `process()` call — sintoma claro de loop interno.

    Não bloqueia pesquisas de turnos distintos do usuário (TTL curto garante isso).
    """

    def __init__(self, max_history: int = 10, ttl_seconds: float = _TTL_SECONDS):
        self.max_history = max_history
        self.ttl_seconds = ttl_seconds
        # Dict[session_id] -> list of _SignatureEntry
        self._history: dict[str, list[_SignatureEntry]] = {}

    def _evict_expired(self, entries: list[_SignatureEntry]) -> list[_SignatureEntry]:
        """Remove entradas mais antigas que TTL — elas são de turnos passados."""
        cutoff = time.monotonic() - self.ttl_seconds
        return [e for e in entries if e.timestamp >= cutoff]

    def check_loop(self, session_id: str, signature_text: str) -> tuple[bool, str]:
        """
        Verifica se a assinatura já foi gerada neste turno de raciocínio.

        Args:
            session_id: ID da sessão (ex: "telegram")
            signature_text: Texto representando a ação (ex: queries de busca concatenadas)

        Returns:
            (allowed, message) — se allowed=False, message contém resposta sintética.
        """
        if not signature_text or not session_id:
            return True, ""

        clean_text = signature_text.strip().lower()
        sig_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()

        session_history = self._history.setdefault(session_id, [])

        # Remove entradas antigas (de turnos passados) antes de verificar
        session_history = self._evict_expired(session_history)
        self._history[session_id] = session_history

        # Só bloqueia se a assinatura apareceu NO MESMO turno (dentro do TTL)
        if any(e.sig_hash == sig_hash for e in session_history):
            log.warning(
                f"[guardrail] Loop de assinatura detectado (mesmo turno) — sessão='{session_id}' "
                f"sig='{clean_text[:80]}'"
            )
            sintetica = (
                "[Sistema: Loop de Ação Detectado]\n"
                "A mesma query de busca foi gerada duas vezes dentro deste ciclo de raciocínio. "
                "Isso indica um loop interno. Reformule a estratégia ou sintetize com os dados já obtidos."
            )
            return False, sintetica

        # Registra e limita tamanho do histórico
        session_history.append(_SignatureEntry(sig_hash=sig_hash))
        if len(session_history) > self.max_history:
            session_history.pop(0)

        return True, ""

    def clear(self, session_id: str) -> None:
        """Limpa histórico de assinaturas de uma sessão (reinício/compressão)."""
        self._history.pop(session_id, None)

    def reset_turn(self, session_id: str) -> None:
        """
        Chamado no início de cada novo turno do usuário para garantir que
        pesquisas legítimas não sejam bloqueadas por histórico de turnos anteriores.
        """
        self._history.pop(session_id, None)
        log.debug(f"[guardrail] Histórico resetado para nova solicitação — sessão='{session_id}'")
