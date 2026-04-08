import asyncio
import logging
from enum import Enum, auto
from src.core.habits.tracker import HabitTracker

log = logging.getLogger("seeker.vision.afk")


class PermissionResult(Enum):
    APPROVED = auto()
    DENIED = auto()
    AFK = auto()       # Timeout Tier 2 (segundo timeout) → auto-approve leitura
    DEFERRED = auto()  # Timeout Tier 2 (primeiro timeout) → enfileira retry
    EXPIRED = auto()   # Timeout Tier 1 → abort (Desktop Takeover)


class AFKProtocol:
    """
    Gerencia hierarquia de consentimentos de Visão e Mouse no Telegram.
    
    Filosofia de segurança (alinhada com Claude Code):
    - Ações de LEITURA (screenshot, OCR, navegação): podem ser auto-aprovadas após 
      timeout escalonado (3min → retry → +30min = AFK confirmado)
    - Ações de ESCRITA (click, submit, form fill): sempre exigem aprovação explícita
    - Desktop takeover (Tier 1/L3): timeout = abort, nunca auto-approve
    """
    FIRST_TIMEOUT_SECONDS = 180    # 3 minutos — primeira tentativa
    SECOND_TIMEOUT_SECONDS = 1800  # 30 minutos — confirmação de AFK real

    def __init__(self, bot, telegram_allowed_users: set[int], habit_tracker: HabitTracker | None = None):
        self.bot = bot
        self.users = telegram_allowed_users
        self.habits = habit_tracker or HabitTracker()

        # Lock serializa requests concorrentes de permissão
        self._lock = asyncio.Lock()

        # Dicionário: request_id → Future (suporta múltiplos requests em fila)
        self._requests: dict[str, asyncio.Future] = {}
        self._request_counter = 0

        # Fila de ações deferidas aguardando segundo timeout
        self._deferred_queue: list[dict] = []

    async def request_permission(
        self, reason: str, tier: int, action_type: str = "read"
    ) -> PermissionResult:
        """
        Pausa o script L2 ou L3 aguardando o Humano ou Timeout.

        Args:
            reason: Descrição legível da ação pedida
            tier: 1 (Desktop/L3) ou 2 (Headless/L2)
            action_type: "read" (screenshot, OCR, navegar) ou "write" (click, submit, form)

        Regras:
            Tier 1 (Mouse Override):  Timeout = EXPIRED (abort sempre)
            Tier 2 + write:           Timeout = EXPIRED (nunca auto-approve escrita)
            Tier 2 + read:            Timeout = DEFERRED → segundo ciclo → AFK
        """
        return await self._request_permission_inner(reason, tier, action_type)

    async def _request_permission_inner(
        self, reason: str, tier: int, action_type: str
    ) -> PermissionResult:
        # Cria Future individual para este request (evita race condition)
        # Lock protege apenas a criação e registro
        async with self._lock:
            self._request_counter += 1
            request_id = f"req_{self._request_counter}"
            future = asyncio.Future()
            self._requests[request_id] = future

        # Monta mensagem com contexto claro do que vai acontecer no timeout
        msg = f"<b>🚨 AUTORIZAÇÃO VISUAL: Tier {tier}</b>\n\n{reason}\n\n"
        msg += f"<b>Tipo:</b> {'📖 Leitura' if action_type == 'read' else '✍️ Escrita'}\n\n"

        # Consulta padrão de hábito antes de perguntar
        habit = self.habits.suggest(reason[:30], action_type)
        if habit["action"] == "auto_approve" and tier == 2 and action_type == "read":
            log.info(
                f"[AFK] Auto-approve por hábito: {habit['reasoning']} "
                f"(conf={habit['confidence']:.0%}, {habit['samples']} amostras)"
            )
            # Notifica que auto-aprovou por padrão
            for uid in self.users:
                try:
                    await self.bot.send_message(
                        uid,
                        f"🧠 <b>Auto-aprovado por hábito</b>\n{reason}\n"
                        f"<i>{habit['reasoning']}</i>",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            return PermissionResult.APPROVED

        if habit["action"] == "auto_skip":
            log.info(f"[AFK] Auto-skip por hábito: {habit['reasoning']}")
            return PermissionResult.DENIED

        if tier == 1 or action_type == "write":
            msg += (
                "<i>⏱ Timeout de 3 minutos. Sem resposta = operação <b>ABORTADA</b>.\n"
                "Ações de escrita e controle de desktop nunca são auto-aprovadas.</i>"
            )
            timeout = self.FIRST_TIMEOUT_SECONDS
            timeout_result = PermissionResult.EXPIRED
        else:
            msg += (
                "<i>⏱ Timeout de 3 minutos. Sem resposta = ação <b>ENFILEIRADA</b>.\n"
                "Se você não responder em mais 30 minutos, prosseguirei em modo leitura.</i>"
            )
            timeout = self.FIRST_TIMEOUT_SECONDS
            timeout_result = PermissionResult.DEFERRED

        markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Autorizar", "callback_data": f"vis_auth_yes_{tier}"},
                    {"text": "❌ Negar", "callback_data": f"vis_auth_no_{tier}"},
                ]
            ]
        }

        for uid in self.users:
            try:
                await self.bot.send_message(
                    uid, msg, reply_markup=markup, parse_mode="HTML"
                )
            except Exception as e:
                log.error(f"[AFK] Falha envio {uid}: {e}", exc_info=True)

        log.info(
            f"[AFK] Aguardando consentimento Tier {tier}/{action_type} "
            f"(Timeout = {timeout}s)..."
        )

        try:
            return await asyncio.wait_for(
                future, timeout=timeout
            )
        except asyncio.TimeoutError:
            log.info(f"[AFK] Primeiro timeout — resultado: {timeout_result.name}")
            if timeout_result == PermissionResult.DEFERRED:
                return await self._handle_deferred(reason, tier, request_id)
            # Limpa request do dicionário
            async with self._lock:
                self._requests.pop(request_id, None)
            return timeout_result

    async def _handle_deferred(self, reason: str, tier: int, request_id: str) -> PermissionResult:
        """
        Segundo ciclo: notifica que a ação foi enfileirada e espera mais 30 minutos.
        Se o humano não responder nesse período, assume AFK real e auto-aprova leitura.
        """
        # Cria novo Future para segundo ciclo (reutiliza request_id)
        async with self._lock:
            future = asyncio.Future()
            self._requests[request_id] = future

        msg = (
            f"<b>⏸ AÇÃO ENFILEIRADA (Tier {tier})</b>\n\n"
            f"{reason}\n\n"
            f"<i>Você não respondeu em 3 minutos. Aguardarei mais 30 minutos.\n"
            f"Se não houver resposta, prosseguirei em <b>modo leitura apenas</b>.</i>"
        )

        markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Autorizar agora", "callback_data": f"vis_auth_yes_{tier}"},
                    {"text": "❌ Cancelar", "callback_data": f"vis_auth_no_{tier}"},
                ]
            ]
        }

        for uid in self.users:
            try:
                await self.bot.send_message(
                    uid, msg, reply_markup=markup, parse_mode="HTML"
                )
            except Exception as e:
                log.error(f"[AFK] Falha envio deferred {uid}: {e}", exc_info=True)

        log.info(
            f"[AFK] Segundo timeout iniciado ({self.SECOND_TIMEOUT_SECONDS}s)..."
        )

        try:
            return await asyncio.wait_for(
                future,
                timeout=self.SECOND_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            log.info("[AFK] Segundo timeout — AFK confirmado. Auto-aprovando leitura.")
            # Notifica que entrou em modo AFK
            for uid in self.users:
                try:
                    await self.bot.send_message(
                        uid,
                        "🤖 <b>AFK confirmado.</b> Prosseguindo em modo leitura.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            # Limpa request do dicionário
            async with self._lock:
                self._requests.pop(request_id, None)
            return PermissionResult.AFK

    async def resolve_request(self, result: str, tier: str, goal_name: str = "", action_type: str = "read"):
        """Chamado pelo Dispatcher do Telegram Action. Protegido por lock."""
        async with self._lock:
            # Busca primeira request em fila (FIFO)
            if not self._requests:
                log.warning(f"[AFK] resolve_request sem requests pendentes (result={result})")
                return

            # Pega primeiro request da fila (order de criação)
            request_id = next(iter(self._requests))
            future = self._requests.pop(request_id)

            if future.done():
                log.warning(f"[AFK] Future já completado (request_id={request_id}, result={result})")
                return

            approved = result == "yes"
            permission_result = (
                PermissionResult.APPROVED if result == "yes" else PermissionResult.DENIED
            )

            # Set Future com resultado (thread-safe)
            future.set_result(permission_result)

            # Registra decisão no Habit Tracker
            if goal_name:
                self.habits.record(goal_name, action_type, approved=approved)
