"""
Seeker.Bot — Desktop Watch Goal
src/skills/desktop_watch/goal.py

Monitoramento proativo da tela.
Quando ATIVADO (via /watch), captura screenshots periodicamente,
analisa com VLM, e notifica o usuário via Telegram quando detecta
algo que exige intervenção humana (diálogos, erros, permissões).

Desligado por padrão. Controlado por /watch e /watchoff.
"""

import asyncio
import logging
import os
import time

from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel,
)
from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.desktop_watch")

# Patterns que indicam necessidade de intervenção humana
ALERT_KEYWORDS = [
    "permission", "permissão", "permitir", "allow", "deny", "negar",
    "error", "erro", "falha", "failed", "crash",
    "update", "atualização", "restart", "reiniciar",
    "install", "instalar", "uninstall",
    "confirm", "confirmar", "confirmação",
    "warning", "aviso", "alerta",
    "accept", "aceitar", "decline", "recusar",
    "save", "salvar", "discard", "descartar",
    "yes", "no", "sim", "não", "ok", "cancel", "cancelar",
    "dialog", "diálogo", "popup", "modal",
    "sign in", "login", "entrar",
    "expired", "expirado", "timeout",
    "download", "baixar",
    "blocked", "bloqueado",
]

# Prompt para o VLM analisar a tela em modo vigilância
WATCH_PROMPT = """Analise esta captura de tela de um computador Windows.
Seu papel é um VIGILANTE DIGITAL que monitora a tela enquanto o dono está ausente.

Responda em formato JSON estrito:
{
  "needs_attention": true/false,
  "urgency": "none" | "low" | "medium" | "high" | "critical",
  "category": "dialog" | "error" | "update" | "permission" | "notification" | "idle" | "normal",
  "summary": "Descrição curta do que está na tela (1 frase)",
  "action_needed": "O que o dono precisa fazer (1 frase, ou null se nada)"
}

Classifique como needs_attention=true APENAS se houver:
- Diálogos de permissão/confirmação esperando clique
- Erros ou crashes visíveis
- Popups de atualização pedindo interação
- Alertas de segurança ou sistema
- Downloads concluídos esperando ação
- Processos travados visualmente

Se a tela mostra apenas aplicações rodando normalmente, needs_attention=false.
NÃO marque como atenção necessária se for apenas um desktop parado ou aplicação funcionando."""


class DesktopWatchGoal:
    """
    Vigília autônoma do desktop.
    Captura screenshots periódicos, analisa com VLM, e alerta o dono
    quando algo precisa de intervenção.

    Toggle: habilitado/desabilitado via /watch e /watchoff no Telegram.
    """

    MAX_CONSECUTIVE_FAILURES = 3  # Circuit breaker: auto-desativa após N timeouts

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._enabled = False  # Desligado por padrão
        self._budget = GoalBudget(max_per_cycle_usd=0.0, max_daily_usd=0.0)

        # Controle de dedup: não alertar a mesma coisa N vezes
        self._last_alert_hash: str = ""
        self._last_alert_time: float = 0
        self.ALERT_COOLDOWN = 300  # 5 minutos entre alertas similares

        # Contadores de sessão
        self._scans_total = 0
        self._alerts_sent = 0
        self._watch_started_at: float = 0
        self._consecutive_failures = 0  # Circuit breaker counter

        # VLM singleton — reutilizado entre ciclos para evitar vazamento de httpx clients
        self._vlm: VLMClient | None = None

    @property
    def name(self) -> str:
        return "desktop_watch"

    @property
    def interval_seconds(self) -> int:
        # Quando ativo, escaneia a cada 2 minutos
        # Quando inativo, checa a cada 5 minutos (só pra ver se foi ativado)
        return 120 if self._enabled else 300

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    # ── Toggle ──────────────────────────────────────────────

    def enable(self):
        """Ativado pelo /watch."""
        self._enabled = True
        self._watch_started_at = time.time()
        self._scans_total = 0
        self._alerts_sent = 0
        log.info("[desktop_watch] 👁️ Vigilância ATIVADA")

    def disable(self):
        """Desativado pelo /watchoff."""
        self._enabled = False
        log.info("[desktop_watch] 👁️ Vigilância DESATIVADA")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # ── Core ────────────────────────────────────────────────

    async def run_cycle(self) -> GoalResult:
        if not self._enabled:
            return GoalResult(
                success=True,
                summary="Desktop Watch desativado. Use /watch para ativar.",
                cost_usd=0.0,
            )

        self._status = GoalStatus.RUNNING
        self._scans_total += 1

        try:
            # 1. Captura a tela silenciosamente (sem pedir permissão — já foi autorizado pelo /watch)
            from src.skills.vision.screenshot import capture_desktop
            screenshot_bytes = await capture_desktop()

            if not screenshot_bytes:
                self._status = GoalStatus.IDLE
                return GoalResult(
                    success=False,
                    summary="Falha na captura de tela",
                    cost_usd=0.0,
                )

            # 2. Análise rápida via VLM (singleton reutilizado)
            if self._vlm is None:
                from src.skills.vision.vlm_client import VLMClient
                from src.skills.vision.gemini_vlm import GeminiVLMClient
                from src.skills.vision.vlm_router import VLMRouter
                cloud_vlm = GeminiVLMClient()
                local_vlm = VLMClient(model="qwen2.5-vl")
                self._vlm = VLMRouter(
                    cloud_vlm_client=cloud_vlm,
                    local_vlm_client=local_vlm,
                    glm_ocr_enabled=False # Não precisa de OCR puro para vigilância
                )

            if not await self._vlm.health_check():
                self._status = GoalStatus.IDLE
                return GoalResult(
                    success=True,
                    summary="VLM offline — scan pulado",
                    cost_usd=0.0,
                )

            analysis_dict = await self._vlm.analyze_screenshot(
                screenshot_bytes, WATCH_PROMPT
            )
            # analyze_screenshot returns a Dict; extract raw text for JSON parsing
            analysis_raw = analysis_dict.get("analysis") or analysis_dict.get("text") or str(analysis_dict)

            # 3. Parse do resultado
            import json
            result_data = self._parse_vlm_response(analysis_raw)

            if not result_data.get("needs_attention", False):
                self._consecutive_failures = 0  # Reset circuit breaker em sucesso
                self._status = GoalStatus.IDLE
                return GoalResult(
                    success=True,
                    summary=f"Scan #{self._scans_total}: tela normal",
                    cost_usd=0.0,
                )

            # 4. Dedup: não alertar a mesma coisa repetidamente
            # Dedup por category+urgency (em vez de texto livre que varia entre scans)
            alert_hash = f"{result_data.get('category', 'unknown')}:{result_data.get('urgency', 'medium')}"
            now = time.time()
            if (alert_hash == self._last_alert_hash and
                    (now - self._last_alert_time) < self.ALERT_COOLDOWN):
                self._status = GoalStatus.IDLE
                return GoalResult(
                    success=True,
                    summary=f"Alerta suprimido (cooldown): {alert_hash}",
                    cost_usd=0.0,
                )

            # 5. Alerta!
            self._last_alert_hash = alert_hash
            self._last_alert_time = now
            self._alerts_sent += 1

            urgency_emoji = {
                "low": "🟡",
                "medium": "🟠",
                "high": "🔴",
                "critical": "🚨",
            }.get(result_data.get("urgency", "medium"), "🟠")

            category = result_data.get("category", "unknown")
            summary = result_data.get("summary", "Algo precisa de atenção")
            action = result_data.get("action_needed", "Verificar a tela")

            notification = (
                f"{urgency_emoji} <b>DESKTOP WATCH — ATENÇÃO NECESSÁRIA</b>\n\n"
                f"📋 <b>Categoria:</b> {category}\n"
                f"📝 <b>Resumo:</b> {summary}\n"
                f"👉 <b>Ação:</b> {action}\n\n"
                f"<i>Scan #{self._scans_total} · {self._alerts_sent} alertas nesta sessão</i>\n"
                f"<i>Use /watchoff para desativar a vigilância.</i>"
            )

            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary=f"ALERTA: {summary}",
                notification=notification,
                cost_usd=0.0,
                data={"photo_bytes": screenshot_bytes},
            )

        except Exception as e:
            log.error(f"[desktop_watch] Erro no scan: {e}", exc_info=True)
            self._consecutive_failures += 1
            self._status = GoalStatus.IDLE

            # Circuit breaker: auto-desativa após N falhas consecutivas
            if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                log.warning(
                    f"[desktop_watch] 🛑 Circuit breaker: {self._consecutive_failures} "
                    f"falhas consecutivas → auto-desativando"
                )
                self.disable()
                return GoalResult(
                    success=False,
                    summary=f"Auto-desativado após {self._consecutive_failures} timeouts.",
                    notification=(
                        "🛑 <b>Desktop Watch AUTO-DESATIVADO</b>\n\n"
                        f"O VLM (Ollama) não respondeu {self._consecutive_failures}x seguidas.\n"
                        "Possível causa: modelo travado ou VRAM insuficiente.\n\n"
                        "<i>Use /watch para reativar quando o Ollama estiver estável.</i>"
                    ),
                    cost_usd=0.0,
                )

            return GoalResult(
                success=False,
                summary=f"Erro no scan ({self._consecutive_failures}/{self.MAX_CONSECUTIVE_FAILURES}): {e}",
                cost_usd=0.0,
            )

    def _parse_vlm_response(self, raw: str) -> dict:
        """Parse JSON do VLM com fallback robusto."""
        import json
        try:
            # Limpa markdown do VLM
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]

            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                text = text[start:end + 1]

            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            # Fallback: procura keywords de alerta no texto
            lower = raw.lower()
            has_alert = any(kw in lower for kw in ALERT_KEYWORDS)
            return {
                "needs_attention": has_alert,
                "urgency": "medium" if has_alert else "none",
                "category": "unknown",
                "summary": raw[:100] if has_alert else "Tela normal",
                "action_needed": "Verificar a tela" if has_alert else None,
            }

    # ── Persistência ────────────────────────────────────────

    def serialize_state(self) -> dict:
        return {
            "enabled": self._enabled,
            "scans_total": self._scans_total,
            "alerts_sent": self._alerts_sent,
            "last_alert_hash": self._last_alert_hash,
        }

    def load_state(self, state: dict) -> None:
        # NÃO restaura enabled — sempre começa desligado
        # (o usuário precisa dar /watch explicitamente)
        self._enabled = False
        self._scans_total = state.get("scans_total", 0)
        self._alerts_sent = state.get("alerts_sent", 0)
        self._last_alert_hash = state.get("last_alert_hash", "")


def create_goal(pipeline) -> DesktopWatchGoal:
    """Factory chamada pelo Goal Registry."""
    return DesktopWatchGoal(pipeline)
