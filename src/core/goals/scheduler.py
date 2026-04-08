"""
Seeker.Bot — Goal Scheduler
src/core/goals/scheduler.py

Orquestra múltiplos AutonomousGoal em background.
Equivalente ao Coordinator Mode do Claude Code, adaptado para agente autônomo.

Responsabilidades:
- Ciclo independente por goal (cada um no seu intervalo)
- Budget global + per-goal
- Backoff em falhas consecutivas
- Persistência de estado de todos os goals
- Roteamento de notificações (Telegram, Email, ambos)
"""

import asyncio
import json
import logging
import os
import time
from collections import deque
from datetime import date

from src.core.goals.protocol import (
    AutonomousGoal,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)

from src.providers.base import LLMRequest, invoke_with_fallback
from config.models import CognitiveRole

log = logging.getLogger("seeker.scheduler")

STATE_DIR = os.path.join(os.getcwd(), "data", "goals")


class GoalScheduler:
    """
    Roda N goals em background, cada um no seu ritmo.
    
    Uso:
        scheduler = GoalScheduler(notifier)
        scheduler.register(revenue_hunter)
        scheduler.register(sense_news)
        await scheduler.start()
    """

    MAX_CONSECUTIVE_FAILURES = 3
    GLOBAL_DAILY_BUDGET_USD = 2.00  # Teto de segurança para TODOS os goals somados

    def __init__(self, notifier: "GoalNotifier"):
        self.notifier = notifier
        self._goals: dict[str, AutonomousGoal] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._rethink_tasks: set = set()  # Background rethink tasks (tracked for shutdown)
        self._failure_counts: dict[str, int] = {}
        self._cycle_history: dict[str, deque] = {}
        self._global_spent_today: float = 0.0
        self._budget_date: str = ""
        self.friction_metrics = {"rate_limits": 0, "rethinks_blocked": 0, "sara_edits": 0}
        self.running = False

        os.makedirs(STATE_DIR, exist_ok=True)

    def register(self, goal: AutonomousGoal):
        """Registra um goal e carrega estado persistido se existir."""
        self._goals[goal.name] = goal
        self._failure_counts[goal.name] = 0
        self._cycle_history[goal.name] = deque(maxlen=20)
        self._load_goal_state(goal)
        log.info(
            f"[scheduler] Registrado: {goal.name} | "
            f"intervalo={goal.interval_seconds}s | "
            f"budget=${goal.budget.max_daily_usd}/dia | "
            f"canais={[c.value for c in goal.channels]}"
        )

    async def start(self):
        """Inicia todos os goals registrados em tasks independentes."""
        self.running = True
        for name, goal in self._goals.items():
            task = asyncio.create_task(self._run_goal_loop(goal))
            self._tasks[name] = task
        log.info(f"[scheduler] {len(self._goals)} goals iniciados.")

    async def stop(self):
        """Para todos os goals e persiste estado."""
        self.running = False

        # Aguarda rethink tasks completarem
        if self._rethink_tasks:
            log.info(f"[scheduler] Aguardando {len(self._rethink_tasks)} rethink tasks...")
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._rethink_tasks, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                log.warning("[scheduler] Timeout aguardando rethink tasks (5s). Continuando...")

        # Cancela goal loops
        for name, task in self._tasks.items():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # Persiste estado final
        for goal in self._goals.values():
            self._save_goal_state(goal)

        self._tasks.clear()
        self._rethink_tasks.clear()
        log.info("[scheduler] Todos os goals parados.")

    def get_status_report(self) -> str:
        """Retorna status formatado de todos os goals (pro /status do Telegram)."""
        lines = [f"<b>🎯 Goals Ativos ({len(self._goals)})</b>\n"]
        today = date.today().isoformat()
        now = time.time()

        for name, goal in self._goals.items():
            budget = goal.budget
            budget.reset_if_new_day(today)
            status = goal.get_status()
            failures = self._failure_counts.get(name, 0)
            history = list(self._cycle_history.get(name, []))

            emoji = {
                GoalStatus.IDLE: "⏸",
                GoalStatus.RUNNING: "🟢",
                GoalStatus.PAUSED: "🟡",
                GoalStatus.WAITING_APPROVAL: "🔵",
                GoalStatus.ERROR: "🔴",
            }.get(status, "⚪")

            # Trend bar: last 10 cycles (✅/❌)
            recent = history[-10:]
            trend = "".join("✅" if c["ok"] else "❌" for c in recent) or "—"

            # Success rate
            if history:
                ok_count = sum(1 for c in history if c["ok"])
                rate = ok_count / len(history) * 100
                rate_str = f"{rate:.0f}%"
            else:
                rate_str = "—"

            # Last run age
            if history:
                age_s = now - history[-1]["ts"]
                if age_s < 3600:
                    age_str = f"{age_s/60:.0f}min atrás"
                else:
                    age_str = f"{age_s/3600:.1f}h atrás"
                last_summary = history[-1]["summary"]
            else:
                age_str = "nunca rodou"
                last_summary = ""

            # Avg latency (last 5)
            recent_latencies = [c["latency"] for c in history[-5:] if c["latency"] > 0]
            latency_str = f"{sum(recent_latencies)/len(recent_latencies):.1f}s" if recent_latencies else "—"

            lines.append(
                f"  {emoji} <b>{name}</b>\n"
                f"    Status: {status.value} | Sucesso: {rate_str} | Latência: {latency_str}\n"
                f"    Trend: {trend}\n"
                f"    Budget: ${budget.spent_today_usd:.4f}/${budget.max_daily_usd} | Falhas: {failures}\n"
                f"    Último: {age_str}"
                + (f"\n    <i>{last_summary}</i>" if last_summary else "")
            )

        lines.append(
            f"\n🛡️ <b>Fricção Controlada (Radical Trust):</b>\n"
            f"  🛑 Alucinações Rethink: {self.friction_metrics['rethinks_blocked']}\n"
            f"  🛠️ SARA Auto-Edições: {self.friction_metrics['sara_edits']}\n"
            f"  🚷 Rate Limits Contornados: {self.friction_metrics['rate_limits']}\n"
        )

        lines.append(
            f"\n<b>Budget global:</b> ${self._global_spent_today:.4f}"
            f"/${self.GLOBAL_DAILY_BUDGET_USD}"
        )
        return "\n".join(lines)

    # ── Loop principal por goal ───────────────────────────

    async def _run_goal_loop(self, goal: AutonomousGoal):
        """Loop independente para um goal. Roda até stop()."""
        await asyncio.sleep(10)  # Respira pós-boot

        while self.running:
            try:
                today = date.today().isoformat()

                # Reset diário
                goal.budget.reset_if_new_day(today)
                if self._budget_date != today:
                    self._global_spent_today = 0.0
                    self._budget_date = today

                # Check budget per-goal
                if goal.budget.exhausted:
                    log.info(f"[scheduler/{goal.name}] Budget diário esgotado.")
                    await asyncio.sleep(goal.interval_seconds)
                    continue

                # Check budget global
                if self._global_spent_today >= self.GLOBAL_DAILY_BUDGET_USD:
                    log.warning(
                        f"[scheduler] Budget GLOBAL esgotado "
                        f"(${self._global_spent_today:.4f}). "
                        f"Todos os goals pausados."
                    )
                    await asyncio.sleep(goal.interval_seconds)
                    continue

                # Backoff se muitas falhas
                failures = self._failure_counts.get(goal.name, 0)
                if failures >= self.MAX_CONSECUTIVE_FAILURES:
                    backoff = goal.interval_seconds * 2
                    log.warning(
                        f"[scheduler/{goal.name}] {failures} falhas, "
                        f"backoff {backoff}s"
                    )
                    await asyncio.sleep(backoff)
                    self._failure_counts[goal.name] = 0
                    continue

                # Executa ciclo
                _cycle_start = time.monotonic()
                result = await goal.run_cycle()
                _cycle_latency = time.monotonic() - _cycle_start

                # Registra histórico
                self._cycle_history[goal.name].append({
                    "ts": time.time(),
                    "ok": result.success,
                    "cost": result.cost_usd,
                    "latency": round(_cycle_latency, 1),
                    "summary": result.summary[:60],
                })

                # Contabiliza custo
                goal.budget.spend(result.cost_usd)
                self._global_spent_today += result.cost_usd
                self._failure_counts[goal.name] = 0

                # Contabiliza Radical Trust Metrics (se houver via data)
                if result.data:
                    rethinks = result.data.get("rethink_blocks", 0)
                    if rethinks > 0:
                        self.friction_metrics["rethinks_blocked"] += rethinks
                        
                    sara_ops = result.data.get("sara_edits", 0)
                    if sara_ops > 0:
                        self.friction_metrics["sara_edits"] += sara_ops

                # Notifica se houver conteúdo
                if result.notification:
                    await self.notifier.send(
                        goal.name, result.notification, goal.channels, data=result.data
                    )

                log.info(
                    f"[scheduler/{goal.name}] Ciclo OK | "
                    f"{result.summary} | "
                    f"${result.cost_usd:.4f}"
                )

            except Exception as e:
                import traceback
                tb_str = traceback.format_exc()
                self._failure_counts[goal.name] = (
                    self._failure_counts.get(goal.name, 0) + 1
                )
                self._cycle_history[goal.name].append({
                    "ts": time.time(),
                    "ok": False,
                    "cost": 0.0,
                    "latency": 0.0,
                    "summary": f"Exceção: {str(e)[:50]}",
                })
                log.error(
                    f"[scheduler/{goal.name}] Falha "
                    f"#{self._failure_counts[goal.name]}: {e}",
                    exc_info=True
                )
                
                # RETHINK: Confiança Extrema. Se for o início do backoff, emite relatório proativo
                if self._failure_counts[goal.name] == self.MAX_CONSECUTIVE_FAILURES:
                    self._create_tracked_task(self._execute_rethink_failure(goal.name, str(e), tb_str, goal.channels))
                elif self._failure_counts[goal.name] == 1 and "rate" not in str(e).lower():
                    # Avisa no primeiro problema estrutural (que não seja rate limit local)
                    self._create_tracked_task(self._execute_rethink_failure(goal.name, str(e), tb_str, goal.channels))

            finally:
                self._save_goal_state(goal)
                await asyncio.sleep(goal.interval_seconds)

    # ── Background Task Management ──────────────────────────
    def _create_tracked_task(self, coro) -> asyncio.Task:
        """Cria uma task e rastreia para shutdown seguro."""
        task = asyncio.create_task(coro)
        self._rethink_tasks.add(task)

        def _on_task_done(t: asyncio.Task):
            """Callback quando task termina (sucesso ou erro)."""
            self._rethink_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                log.error(f"[rethink] Background task falhou: {exc}", exc_info=True)

        task.add_done_callback(_on_task_done)
        return task

    # ── Rethink (Autoavaliação de Falhas) ─────────────────
    async def _execute_rethink_failure(self, goal_name: str, error_msg: str, tb_str: str, channels: list[NotificationChannel]):
        """Analisa a exceção ocorrida em um Goal e gera um relatório humanizado proativo antes do backoff."""
        prompt = (
            f"O Goal Autônomo '{goal_name}' acabou de falhar. Você é o módulo de RETHINK.\n"
            "Seu papel é praticar a 'Confiança Extrema' explicando de forma concisa:\n"
            "1. O que parece ter acontecido (causa raiz provável)\n"
            "2. Qual seria o impacto se o scheduler não o pausasse temporariamente.\n\n"
            f"ERRO: {error_msg}\n"
            f"TRACEBACK:\n{tb_str[-1500:]}\n\n"
            "Responda apenas com a explicação formatada em Telegram HTML, iniciando "
            "com '<b>RETHINK: Avaliação de Falha</b> 🛑\n' e sendo conciso. Sem enrolação."
        )
        
        try:
            # Empresta as keys de um goal carregado localmente, como work-around, ou assume q o pipeline injeta as keys globais dps.
            # No scheduler não temos self.pipeline_api_keys diretamente, então pegamos do environment se possível,
            # Ou passamos uma LLMRequest para o fallback resolver (invoke defaults).
            from src.core.pipeline import SeekerPipeline
            # Hack seguro se o router global nao for mandado
            from config.models import ModelRouter
            resp = await invoke_with_fallback(
                CognitiveRole.FAST,
                LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    system="Explique o erro do sistema.",
                    temperature=0.1,
                    max_tokens=300
                ),
                ModelRouter(),
                {} # Dict de api keys empty delega pro os.environ na lib base
            )
            report = resp.text
            self.friction_metrics["rethinks_blocked"] += 1
            await self.notifier.send(goal_name, report, channels)
        except Exception as rethink_ex:
            log.error(f"[rethink] Falhou ao explicar o erro: {rethink_ex}", exc_info=True)

    # ── Persistência ──────────────────────────────────────

    def _save_goal_state(self, goal: AutonomousGoal):
        path = os.path.join(STATE_DIR, f"{goal.name}.json")
        try:
            state = goal.serialize_state()
            state["_budget"] = {
                "spent_today_usd": goal.budget.spent_today_usd,
                "budget_reset_date": goal.budget.budget_reset_date,
            }
            state["_failures"] = self._failure_counts.get(goal.name, 0)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"[scheduler] Falha ao salvar {goal.name}: {e}", exc_info=True)

    def _load_goal_state(self, goal: AutonomousGoal):
        path = os.path.join(STATE_DIR, f"{goal.name}.json")
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            # Restaura budget
            budget_data = state.pop("_budget", {})
            goal.budget.spent_today_usd = budget_data.get("spent_today_usd", 0.0)
            goal.budget.budget_reset_date = budget_data.get("budget_reset_date", "")
            # Restaura failures
            self._failure_counts[goal.name] = state.pop("_failures", 0)
            # Restaura estado do goal
            goal.load_state(state)
            log.info(f"[scheduler] Estado restaurado: {goal.name}")
        except Exception as e:
            log.warning(f"[scheduler] Falha ao carregar {goal.name}: {e}")


class GoalNotifier:
    """
    Roteia notificações dos goals para Telegram, Email ou ambos.
    Injetado no scheduler — desacoplado dos canais.
    """

    def __init__(
        self,
        bot=None,
        admin_chats: set[int] | None = None,
        email_client=None,
        email_recipients: list[str] | None = None,
    ):
        self.bot = bot
        self.admin_chats = admin_chats or set()
        self.email_client = email_client
        self.email_recipients = email_recipients or []

    async def send(
        self,
        goal_name: str,
        content: str,
        channels: list[NotificationChannel],
        data: dict | None = None,
    ):
        """Despacha notificação para os canais configurados."""
        for channel in channels:
            if channel in (NotificationChannel.TELEGRAM, NotificationChannel.BOTH):
                await self._send_telegram(goal_name, content, data)
            if channel in (NotificationChannel.EMAIL, NotificationChannel.BOTH):
                await self._send_email(goal_name, content)

    async def _send_telegram(self, goal_name: str, content: str, data: dict | None = None):
        if not self.bot:
            return
            
        import re
        def clean_html(raw_html):
            cleanr = re.compile('<.*?>')
            return re.sub(cleanr, '', raw_html)
            
        for uid in self.admin_chats:
            try:
                # Se tiver PDF, doc longo ou bytes de foto
                from aiogram.enums import ParseMode
                pdf_path = (data or {}).get("pdf_path", "")
                photo_bytes = (data or {}).get("photo_bytes", None)

                if pdf_path and os.path.exists(pdf_path):
                    from aiogram.types import FSInputFile
                    doc = FSInputFile(pdf_path)
                    safe_caption = clean_html(content)[:1000] + "..." if len(content) > 1000 else clean_html(content)
                    await self.bot.send_document(uid, doc, caption=safe_caption)
                elif photo_bytes:
                    from aiogram.types import BufferedInputFile
                    photo = BufferedInputFile(photo_bytes, filename="watch_alert.png")
                    safe_caption = clean_html(content)[:1000] + "..." if len(content) > 1000 else clean_html(content)
                    await self.bot.send_photo(uid, photo, caption=safe_caption)
                else:
                    if len(content) > 4000:
                        content_safe = clean_html(content)[:4000] + "\n\n(Aviso: Mensagem longa truncada)"
                        await self.bot.send_message(uid, content_safe)
                    else:
                        await self.bot.send_message(uid, content, parse_mode=ParseMode.HTML)
            except Exception as e:
                log.error(f"[notifier/{goal_name}] Telegram falhou {uid}: {e}", exc_info=True)

    async def _send_email(self, goal_name: str, content: str):
        if not self.email_client or not self.email_recipients:
            return
        try:
            subject = f"[Seeker] {goal_name}"
            await self.email_client.send(
                to=self.email_recipients,
                subject=subject,
                body_html=content,
            )
        except Exception as e:
            log.error(f"[notifier/{goal_name}] Email falhou: {e}", exc_info=True)
