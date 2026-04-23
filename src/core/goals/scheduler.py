"""
Seeker.Bot — Goal Scheduler (Unified + Preemption)
src/core/goals/scheduler.py

Orquestra múltiplos AutonomousGoal em background com priorização inteligente.
Equivalente ao Coordinator Mode do Claude Code, adaptado para agente autônomo.

Responsabilidades:
- Ciclo independente por goal (cada um no seu intervalo)
- Budget global + per-goal
- Backoff em falhas consecutivas
- Persistência de estado de todos os goals
- Roteamento de notificações (Telegram, Email, ambos)

Melhorias Sprint 7.2:
- Priority system: CRITICAL > HIGH > NORMAL > LOW
- Preemption: Goals CRITICAL interrompem goals NORMAL/LOW
- Coroutine pool: Limita concurrent goals executando (máx 3)
"""

import asyncio
import json
import logging
import os
import time
from collections import deque
from datetime import date
from enum import Enum
from typing import Any, Coroutine

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


class GoalPriority(Enum):
    """Priority levels para goals — determina preemption e scheduling"""
    CRITICAL = 0  # Interrompe goals em execução (alerta, health check)
    HIGH = 1      # Executado antes de NORMAL/LOW (importante mas não crítico)
    NORMAL = 2    # Priority padrão (maioria dos goals)
    LOW = 3       # Executado apenas se recursos disponíveis (background tasks)


class GoalScheduler:
    """
    Roda N goals em background com priorização inteligente.

    Melhorias Sprint 7.2:
    - Priority-based scheduling (CRITICAL > HIGH > NORMAL > LOW)
    - Preemption: CRITICAL interrompe NORMAL/LOW em execução
    - Coroutine pool: Máx 3 goals executando em paralelo

    Uso:
        scheduler = GoalScheduler(notifier)
        scheduler.register(revenue_hunter, priority=GoalPriority.NORMAL)
        scheduler.register(critical_alert, priority=GoalPriority.CRITICAL)
        await scheduler.start()
    """

    MAX_CONSECUTIVE_FAILURES = 3
    GLOBAL_DAILY_BUDGET_USD = 2.00  # Teto de segurança para TODOS os goals somados
    MAX_CONCURRENT_GOALS = 3        # Limita goals executando em paralelo (Sprint 7.2)

    def __init__(self, notifier: "GoalNotifier"):
        self.notifier = notifier
        self._goals: dict[str, AutonomousGoal] = {}
        self._goal_priorities: dict[str, GoalPriority] = {}  # Sprint 7.2: priority mapping
        self._tasks: dict[str, asyncio.Task] = {}
        self._rethink_tasks: set = set()  # Background rethink tasks (tracked for shutdown)
        self._failure_counts: dict[str, int] = {}
        self._cycle_history: dict[str, deque] = {}
        self._global_spent_today: float = 0.0
        self._budget_date: str = ""

        # Sprint 7.2: Preemption & Pooling
        self._running_goals: set[str] = set()  # Goals currently executing
        self._paused_by_preemption: set[str] = set()  # Goals paused due to CRITICAL
        self._pool_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_GOALS)

        self.friction_metrics = {"rate_limits": 0, "rethinks_blocked": 0, "sara_edits": 0}
        self.running = False

        os.makedirs(STATE_DIR, exist_ok=True)

    def register(self, goal: AutonomousGoal, priority: GoalPriority = GoalPriority.NORMAL) -> None:
        """
        Registra um goal e carrega estado persistido se existir.

        Args:
            goal: AutonomousGoal para registrar
            priority: GoalPriority (CRITICAL/HIGH/NORMAL/LOW) — Sprint 7.2
        """
        self._goals[goal.name] = goal
        self._goal_priorities[goal.name] = priority
        self._failure_counts[goal.name] = 0
        self._cycle_history[goal.name] = deque(maxlen=20)
        self._load_goal_state(goal)
        log.info(
            f"[scheduler] Registrado: {goal.name} | "
            f"prioridade={priority.name} | "
            f"intervalo={goal.interval_seconds}s | "
            f"budget=${goal.budget.max_daily_usd}/dia | "
            f"canais={[c.value for c in goal.channels]}"
        )

    async def start(self) -> None:
        """Inicia todos os goals registrados em tasks independentes."""
        self.running = True
        for name, goal in self._goals.items():
            task = asyncio.create_task(self._run_goal_loop(goal))
            self._tasks[name] = task
        log.info(f"[scheduler] {len(self._goals)} goals iniciados.")

    async def stop(self) -> None:
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

    def get_health_dashboard(self) -> dict[str, Any]:
        """Retorna dashboard completo de saúde de todos os goals com métricas avançadas."""
        today = date.today().isoformat()
        now = time.time()

        goals_health = {}
        for name, goal in self._goals.items():
            goals_health[name] = self.get_goal_metrics(name)

        return {
            "timestamp": now,
            "date": today,
            "global_budget": {
                "spent": self._global_spent_today,
                "limit": self.GLOBAL_DAILY_BUDGET_USD,
            },
            "friction_metrics": dict(self.friction_metrics),
            "goals": goals_health,
            "summary": {
                "total_goals": len(self._goals),
                "avg_success_rate": sum(g["metrics"]["success_rate"] for g in goals_health.values()) / len(goals_health) if goals_health else 0,
                "total_cost_today": sum(goal.budget.spent_today_usd for goal in self._goals.values()),
            }
        }

    def get_goal_metrics(self, goal_name: str) -> dict[str, Any]:
        """Retorna métricas detalhadas de um goal específico."""
        if goal_name not in self._goals:
            return {}

        goal = self._goals[goal_name]
        history = list(self._cycle_history.get(goal_name, []))
        failures = self._failure_counts.get(goal_name, 0)
        now = time.time()

        if not history:
            return {
                "name": goal_name,
                "status": goal.get_status().value,
                "metrics": {
                    "success_rate": 0.0,
                    "total_cycles": 0,
                    "avg_latency": 0.0,
                    "total_cost": 0.0,
                    "consecutive_failures": failures,
                },
                "history": [],
            }

        # Calcula métricas
        ok_count = sum(1 for c in history if c["ok"])
        success_rate = ok_count / len(history) * 100

        latencies = [c["latency"] for c in history if c["latency"] > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        total_cost = sum(c["cost"] for c in history)

        # Trend: últimas 5 vs anteriores
        recent_5 = history[-5:]
        recent_success = sum(1 for c in recent_5 if c["ok"]) / len(recent_5) * 100 if recent_5 else 0.0

        earlier = history[:-5]
        earlier_success = sum(1 for c in earlier if c["ok"]) / len(earlier) * 100 if earlier else 0.0

        trend = "📈" if recent_success > earlier_success else ("📉" if recent_success < earlier_success else "➡️")

        return {
            "name": goal_name,
            "status": goal.get_status().value,
            "budget": {
                "spent_today": goal.budget.spent_today_usd,
                "limit": goal.budget.max_daily_usd,
            },
            "metrics": {
                "success_rate": round(success_rate, 1),
                "recent_5_success_rate": round(recent_success, 1),
                "trend": trend,
                "total_cycles": len(history),
                "avg_latency": round(avg_latency, 2),
                "min_latency": min(latencies) if latencies else 0.0,
                "max_latency": max(latencies) if latencies else 0.0,
                "total_cost": round(total_cost, 4),
                "consecutive_failures": failures,
            },
            "last_run": {
                "timestamp": history[-1]["ts"],
                "age_seconds": now - history[-1]["ts"],
                "success": history[-1]["ok"],
                "cost": history[-1]["cost"],
                "latency": history[-1]["latency"],
                "summary": history[-1]["summary"],
            },
            "history": [
                {
                    "ts": c["ts"],
                    "ok": c["ok"],
                    "cost": c["cost"],
                    "latency": c["latency"],
                }
                for c in history[-10:]  # Últimas 10 execuções
            ],
        }

    # ── Preemption & Priority Management (Sprint 7.2) ──────

    async def _check_preemption_needed(self) -> bool:
        """
        Verifica se há goals CRITICAL que precisam executar.
        Se sim, retorna True (indica que deve pausar goals NORMAL/LOW).
        """
        for name, priority in self._goal_priorities.items():
            if priority == GoalPriority.CRITICAL and name not in self._running_goals:
                # Goal CRITICAL está esperando executar
                return True
        return False

    def _should_execute_goal(self, goal_name: str) -> bool:
        """
        Determina se um goal deve executar agora, levando em conta preemption.
        """
        priority = self._goal_priorities.get(goal_name, GoalPriority.NORMAL)

        # Goals em pausa por preemption não executam
        if goal_name in self._paused_by_preemption:
            return False

        # Se há CRITICAL em execução e este é NORMAL/LOW, pausar
        if priority in [GoalPriority.NORMAL, GoalPriority.LOW]:
            for other_name, other_priority in self._goal_priorities.items():
                if (other_priority == GoalPriority.CRITICAL and
                    other_name in self._running_goals):
                    self._paused_by_preemption.add(goal_name)
                    return False

        return True

    def _get_next_priority_goal(self) -> str | None:
        """
        Retorna o goal de maior prioridade que está aguardando executar.
        Considera preemption e pool limits.
        """
        if len(self._running_goals) >= self.MAX_CONCURRENT_GOALS:
            return None  # Pool cheio

        # Ordena goals por prioridade
        sorted_goals = sorted(
            self._goal_priorities.items(),
            key=lambda x: x[1].value  # Menor valor = maior prioridade
        )

        for goal_name, priority in sorted_goals:
            if goal_name not in self._running_goals:
                if self._should_execute_goal(goal_name):
                    return goal_name

        return None

    # ── Loop principal por goal ───────────────────────────

    def _write_heartbeat(self) -> None:
        """Escreve timestamp no arquivo de heartbeat para o watchdog monitorar."""
        try:
            import os, time
            os.makedirs("logs", exist_ok=True)
            with open("logs/bot_heartbeat.txt", "w") as f:
                f.write(str(time.time()))
        except Exception:
            pass

    async def _run_goal_loop(self, goal: AutonomousGoal) -> None:
        """Loop independente para um goal. Roda até stop() com preemption support."""
        await asyncio.sleep(10)  # Respira pós-boot

        while self.running:
            try:
                today = date.today().isoformat()

                # Reset diário
                goal.budget.reset_if_new_day(today)
                if self._budget_date != today:
                    self._global_spent_today = 0.0
                    self._budget_date = today

                # ── Sprint 7.2: Check preemption ──────────────────────────
                if not self._should_execute_goal(goal.name):
                    # Goal foi pausado por preemption ou pool cheio
                    await asyncio.sleep(5)  # Respira e tenta novamente
                    continue

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

                # ── Sprint 7.2: Pool semaphore (limita concurrent goals) ────
                async with self._pool_semaphore:
                    self._running_goals.add(goal.name)
                    if goal.name in self._paused_by_preemption:
                        self._paused_by_preemption.discard(goal.name)

                    try:
                        # Heartbeat: atualiza timestamp para o watchdog
                        self._write_heartbeat()

                        # Executa ciclo
                        _cycle_start = time.monotonic()
                        result = await goal.run_cycle()
                        _cycle_latency = time.monotonic() - _cycle_start
                    finally:
                        self._running_goals.discard(goal.name)

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
    def _create_tracked_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
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
    async def _execute_rethink_failure(self, goal_name: str, error_msg: str, tb_str: str, channels: list[NotificationChannel]) -> None:
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

    def _save_goal_state(self, goal: AutonomousGoal) -> None:
        path = os.path.join(STATE_DIR, f"{goal.name}.json")
        try:
            state = goal.serialize_state()
            state["_budget"] = {
                "spent_today_usd": goal.budget.spent_today_usd,
                "budget_reset_date": goal.budget.budget_reset_date,
            }
            state["_failures"] = self._failure_counts.get(goal.name, 0)
            # Persiste histórico de ciclos (últimas 20)
            state["_cycle_history"] = list(self._cycle_history.get(goal.name, []))
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"[scheduler] Falha ao salvar {goal.name}: {e}", exc_info=True)

    def _load_goal_state(self, goal: AutonomousGoal) -> None:
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
            # Restaura histórico de ciclos
            cycle_history = state.pop("_cycle_history", [])
            if cycle_history:
                self._cycle_history[goal.name] = deque(cycle_history, maxlen=20)
            # Restaura contagem de falhas
            self._failure_counts[goal.name] = state.pop("_failures", 0)
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
        data: dict[str, Any] | None = None,
    ) -> None:
        """Despacha notificação para os canais configurados."""
        for channel in channels:
            if channel in (NotificationChannel.TELEGRAM, NotificationChannel.BOTH):
                await self._send_telegram(goal_name, content, data)
            if channel in (NotificationChannel.EMAIL, NotificationChannel.BOTH):
                await self._send_email(goal_name, content)

    async def _send_telegram(self, goal_name: str, content: str, data: dict[str, Any] | None = None) -> None:
        if not self.bot:
            return

        import re
        def clean_html(raw_html: str) -> str:
            cleanr = re.compile('<.*?>')
            return re.sub(cleanr, '', raw_html)

        def sanitize_telegram_html(text: str) -> str:
            """Remove <email@domain> patterns que o Telegram interpreta como tags invalidas."""
            # Substitui <qualquer-coisa-com-@> por versao escapada
            return re.sub(r'<([^>]*@[^>]*)>', r'&lt;\1&gt;', text)

        for uid in self.admin_chats:
            try:
                # Se tiver PDF, doc longo ou bytes de foto
                from aiogram.enums import ParseMode
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

                pdf_path = (data or {}).get("pdf_path", "")
                photo_bytes = (data or {}).get("photo_bytes", None)
                reply_markup = (data or {}).get("reply_markup", None)  # Inline keyboard (se houver)

                # Sanitiza o conteudo HTML antes de qualquer envio
                content = sanitize_telegram_html(content)

                # Constrói reply_markup se data contém buttons (ex: de approval notifications)
                if not reply_markup and (data or {}).get("buttons"):
                    buttons_data = data.get("buttons", [])
                    buttons = [[
                        InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                        for btn in row
                    ] for row in buttons_data]
                    reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons)

                if pdf_path and os.path.exists(pdf_path):
                    from aiogram.types import FSInputFile
                    doc = FSInputFile(pdf_path)
                    if len(content) > 1000:
                        # Envia o texto completo primeiro (suporta HTML)
                        # Nota: se content > 4096, o Telegram limitará, mas dossiês costumam ter ~1500-2500
                        try:
                            await self.bot.send_message(uid, content, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
                        except Exception as e:
                            log.warning(f"Erro ao enviar mensagem longa (HTML): {e}. Tentando fallback sem HTML.")
                            await self.bot.send_message(uid, clean_html(content)[:4000], reply_markup=reply_markup)
                        
                        # Envia o PDF logo em seguida
                        await self.bot.send_document(uid, doc, caption="📄 Dossiê Anexo")
                    else:
                        await self.bot.send_document(uid, doc, caption=content, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
                elif photo_bytes:
                    from aiogram.types import BufferedInputFile
                    photo = BufferedInputFile(photo_bytes, filename="watch_alert.png")
                    safe_caption = clean_html(content)[:1000] + "..." if len(content) > 1000 else clean_html(content)
                    await self.bot.send_photo(uid, photo, caption=safe_caption, reply_markup=reply_markup)
                else:
                    if len(content) > 4000:
                        parts = []
                        remaining = content
                        while remaining:
                            if len(remaining) <= 4000:
                                parts.append(remaining)
                                break
                            # Try to split at double newline, or single newline
                            cut = remaining.rfind("\n\n", 0, 4000)
                            if cut == -1 or cut < 2000:
                                cut = remaining.rfind("\n", 0, 4000)
                            if cut == -1 or cut < 2000:
                                cut = 4000
                                
                            parts.append(remaining[:cut].rstrip())
                            remaining = remaining[cut:].lstrip()
                            
                        for i, part in enumerate(parts):
                            markup = reply_markup if i == len(parts) - 1 else None
                            try:
                                await self.bot.send_message(uid, part, parse_mode=ParseMode.HTML, reply_markup=markup)
                            except Exception as e:
                                if "can't parse entities" in str(e).lower() or "html" in str(e).lower():
                                    log.warning(f"Fallback to plain text for chunk {i} due to HTML parse error: {e}")
                                    await self.bot.send_message(uid, clean_html(part), reply_markup=markup)
                                else:
                                    raise e
                    else:
                        await self.bot.send_message(uid, content, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            except Exception as e:
                log.error(f"[notifier/{goal_name}] Telegram falhou {uid}: {e}", exc_info=True)

    async def _send_email(self, goal_name: str, content: str) -> None:
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
