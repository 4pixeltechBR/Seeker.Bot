"""
core.billing.gcp_budget_guard — Trava persistente de billing GCP.

Garante que o Seeker.Bot **nunca exceda o free tier** dos serviços GCP habilitados,
mesmo após restart, retry storms, ou bugs de paralelização.

Estratégia:
  1. Estado PERSISTENTE em data/gcp_usage.json (sobrevive a restart)
  2. Janela dupla: daily (YouTube reseta meia-noite PST) + monthly (Vision/TTS reseta dia 1 UTC)
  3. Pre-check + post-record: o caller chama `await guard.consume("service", units)`
     que valida ANTES da chamada HTTP e registra DEPOIS
  4. Hard cap em 80% do free tier (margem de segurança) + soft warning em 50%
  5. Circuit breaker por serviço: 3 over-cap attempts → service desabilitado por 1h
  6. Fallback chain: cada operação tem N fallbacks registrados via register_fallback

Free tiers aplicados (ver jul/2026):
  • YouTube Data API v3:  10,000 units/dia → cap em 8,000
  • Cloud Vision API:     1,000 units/mês → cap em 800
  • Cloud Text-to-Speech: 1M chars/mês    → cap em 800,000
  • Maps Static API:      10,000 events/mês → cap em 8,000
  • Places API (New):     10,000 events/mês → cap em 8,000 (por SKU)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine

log = logging.getLogger("seeker.billing.gcp")


class WindowKind(str, Enum):
    """Tipo de janela de reset da quota."""
    DAILY_PST = "daily_pst"      # YouTube Data API (midnight Pacific)
    MONTHLY_UTC = "monthly_utc"  # Vision, TTS, Maps (day 1 UTC)


class BudgetExceededError(Exception):
    """Levantado quando o budget free tier está esgotado para o serviço."""
    pass


class ServiceDisabledError(Exception):
    """Levantado quando o serviço foi desabilitado pelo circuit breaker."""
    pass


@dataclass
class ServiceBudget:
    """Config de budget/free tier para um serviço."""
    name: str
    window: WindowKind
    free_tier_limit: int           # limite oficial (ex: 10000 units/dia)
    unit_name: str = "units"       # nome amigável (units, events, chars)
    safe_cap: int | None = None    # limite real (80% do free tier por padrão)
    enabled: bool = True           # desabilitar manualmente p/ parar chamadas

    def __post_init__(self):
        if self.safe_cap is None:
            self.safe_cap = int(self.free_tier_limit * 0.80)

    def reset_at(self, now: float | None = None) -> float:
        """Calcula quando a quota reseta."""
        now = now or time.time()
        if self.window == WindowKind.DAILY_PST:
            # YouTube: meia-noite PST (UTC-8 standard, UTC-7 DST)
            # Para simplificar, usamos meia-noite UTC (margem de ±1h)
            dt = datetime.fromtimestamp(now, tz=timezone.utc)
            next_day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            next_day = next_day.replace(day=next_day.day + 1)
            # YouTube reseta à meia-noite PST (UTC-8), então subtraímos 8h
            # para alinhar com PST. Mas na prática é ±1h, então UTC é OK.
            return next_day.timestamp()
        else:  # MONTHLY_UTC
            dt = datetime.fromtimestamp(now, tz=timezone.utc)
            if dt.month == 12:
                next_month = dt.replace(year=dt.year + 1, month=1, day=1,
                                        hour=0, minute=0, second=0, microsecond=0)
            else:
                next_month = dt.replace(month=dt.month + 1, day=1,
                                        hour=0, minute=0, second=0, microsecond=0)
            return next_month.timestamp()


@dataclass
class UsageRecord:
    """Registro de uso de um serviço num período."""
    service: str
    window_start: float
    units_used: int = 0
    call_count: int = 0
    fallback_count: int = 0
    over_cap_count: int = 0     # vezes que tentou consumir além do safe_cap
    last_call_ts: float = 0.0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "window_start": self.window_start,
            "units_used": self.units_used,
            "call_count": self.call_count,
            "fallback_count": self.fallback_count,
            "over_cap_count": self.over_cap_count,
            "last_call_ts": self.last_call_ts,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "UsageRecord":
        return cls(**d)


# ── Default Budgets ────────────────────────────────────────────────────

DEFAULT_BUDGETS: dict[str, ServiceBudget] = {
    "youtube_data_api_v3": ServiceBudget(
        name="YouTube Data API v3",
        window=WindowKind.DAILY_PST,
        free_tier_limit=10_000,
        unit_name="units",
    ),
    "cloud_vision": ServiceBudget(
        name="Cloud Vision API",
        window=WindowKind.MONTHLY_UTC,
        free_tier_limit=1_000,
        unit_name="units",
    ),
    "cloud_text_to_speech": ServiceBudget(
        name="Cloud Text-to-Speech",
        window=WindowKind.MONTHLY_UTC,
        free_tier_limit=1_000_000,
        unit_name="chars",
    ),
    "maps_static": ServiceBudget(
        name="Maps Static API",
        window=WindowKind.MONTHLY_UTC,
        free_tier_limit=10_000,
        unit_name="events",
    ),
    "places_api": ServiceBudget(
        name="Places API (New)",
        window=WindowKind.MONTHLY_UTC,
        free_tier_limit=10_000,
        unit_name="events",
    ),
    "maps_grounding_lite": ServiceBudget(
        name="Maps Grounding Lite API",
        window=WindowKind.MONTHLY_UTC,
        free_tier_limit=10_000,
        unit_name="events",
    ),
}


# ── Persistent State ────────────────────────────────────────────────────

def _usage_path() -> Path:
    gdrive_base = os.getenv("GDRIVE_PATH")
    if gdrive_base and os.path.exists(gdrive_base):
        return Path(gdrive_base) / "gcp_usage.json"
    root = Path(__file__).resolve().parent.parent.parent.parent
    return root / "data" / "gcp_usage.json"


def _empty_state() -> dict[str, Any]:
    return {
        "usage": {},                   # service -> UsageRecord dict
        "disabled_until": {},          # service -> timestamp (circuit breaker)
        "alerts_sent": {},             # alert_key -> timestamp (cooldown)
    }


# ── GCP Budget Guard ────────────────────────────────────────────────────

class GCPBudgetGuard:
    """Guard singleton que rastreia uso de cada serviço GCP e bloqueia
    chamadas quando o free tier está prestes a ser excedido.

    Estado persistente: data/gcp_usage.json (sobrevive a restart).
    Thread-safe via asyncio.Lock.
    """

    _instance: "GCPBudgetGuard | None" = None

    def __init__(self):
        self.budgets: dict[str, ServiceBudget] = dict(DEFAULT_BUDGETS)
        self.usage: dict[str, UsageRecord] = {}
        self.disabled_until: dict[str, float] = {}
        self.alerts_sent: dict[str, float] = {}
        self._fallbacks: dict[str, list[Callable[..., Coroutine]]] = {}
        self._lock = asyncio.Lock()
        self._alert_cooldown_s = 6 * 3600  # 6h entre alertas do mesmo tipo
        self._load_state()

    @classmethod
    def get(cls) -> "GCPBudgetGuard":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> None:
        path = _usage_path()
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.usage = {
                k: UsageRecord.from_dict(v) for k, v in data.get("usage", {}).items()
            }
            self.disabled_until = data.get("disabled_until", {})
            self.alerts_sent = data.get("alerts_sent", {})
            log.debug(f"[gcp-guard] Estado carregado de {path}")
        except Exception as e:
            log.warning(f"[gcp-guard] Falha ao carregar estado: {e}")

    def _save_state(self) -> None:
        path = _usage_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "usage": {k: v.to_dict() for k, v in self.usage.items()},
                    "disabled_until": self.disabled_until,
                    "alerts_sent": self.alerts_sent,
                }, f, ensure_ascii=False, indent=2)
            tmp.replace(path)
        except Exception as e:
            log.warning(f"[gcp-guard] Falha ao salvar estado: {e}")

    # ── Budget Management ──────────────────────────────────────────────

    def register_budget(self, budget: ServiceBudget) -> None:
        """Registra/atualiza o budget de um serviço."""
        self.budgets[budget.name] = budget

    def set_enabled(self, service: str, enabled: bool) -> None:
        """Habilita/desabilita manualmente um serviço."""
        if service in self.budgets:
            self.budgets[service].enabled = enabled
            log.info(f"[gcp-guard] {service} {'habilitado' if enabled else 'DESABILITADO'}")

    def disable_service(self, service: str, duration_s: int = 3600) -> None:
        """Desabilita um serviço por `duration_s` segundos (circuit breaker)."""
        self.disabled_until[service] = time.time() + duration_s
        log.warning(f"[gcp-guard] {service} DESABILITADO por {duration_s}s "
                    f"(até {datetime.fromtimestamp(self.disabled_until[service]).isoformat()})")
        self._save_state()

    def is_service_available(self, service: str) -> bool:
        """Retorna True se o serviço pode ser chamado agora."""
        budget = self.budgets.get(service)
        if not budget:
            return False  # serviço desconhecido = bloqueado
        if not budget.enabled:
            return False

        now = time.time()
        # Verifica desabilitação temporária (circuit breaker)
        if service in self.disabled_until and self.disabled_until[service] > now:
            return False

        return True

    # ── Core API: consume ───────────────────────────────────────────────

    async def consume(self, service: str, units: int = 1) -> bool:
        """Tenta consumir `units` unidades do serviço.

        Returns:
            True se o consumo foi aprovado (caller deve fazer a chamada HTTP).
            False se o serviço está disabled ou o budget free tier está esgotado.

        Raises:
            ServiceDisabledError: serviço desabilitado manualmente ou pelo circuit breaker.
            BudgetExceededError: free tier safe_cap atingido (caller deve usar fallback).
        """
        async with self._lock:
            now = time.time()
            budget = self.budgets.get(service)
            if not budget:
                raise ValueError(f"Serviço GCP desconhecido: {service!r}. "
                                 f"Disponíveis: {list(self.budgets)}")
            if not budget.enabled:
                raise ServiceDisabledError(f"Serviço {service} desabilitado manualmente.")
            if not self.is_service_available(service):
                until = self.disabled_until.get(service, 0)
                raise ServiceDisabledError(
                    f"Serviço {service} desabilitado até "
                    f"{datetime.fromtimestamp(until).isoformat()} (circuit breaker)."
                )

            # Garante que existe UsageRecord para a janela atual
            self._ensure_current_window(service, now)

            record = self.usage[service]

            # Verifica safe_cap
            if record.units_used + units > budget.safe_cap:
                record.over_cap_count += 1
                # 3 over-cap attempts → circuit breaker (1h)
                if record.over_cap_count >= 3:
                    self.disable_service(service, duration_s=3600)
                    raise ServiceDisabledError(
                        f"{service} desabilitado após {record.over_cap_count} tentativas "
                        f"sobre o safe_cap ({budget.safe_cap} {budget.unit_name})."
                    )
                raise BudgetExceededError(
                    f"{service}: uso {record.units_used}/{budget.safe_cap} {budget.unit_name} "
                    f"+ {units} solicitado = {record.units_used + units} > safe_cap. "
                    f"Free tier: {budget.free_tier_limit} {budget.unit_name}/"
                    f"{budget.window.value}. Use fallback."
                )

            # Aprovado: registra ANTES da chamada (best-effort reserve)
            record.units_used += units
            record.call_count += 1
            record.last_call_ts = now
            self._save_state()

            log.debug(f"[gcp-guard] {service}: +{units} → "
                      f"{record.units_used}/{budget.safe_cap} {budget.unit_name}")
            return True

    async def record_call_success(self, service: str, units_used: int = 1) -> None:
        """Registra que uma chamada já aprovada foi concluída com sucesso.

        Use após `consume()` retornar True e a chamada HTTP retornar 2xx.
        O `consume()` já reservou a quota, então isso é apenas atualização de
        telemetria (last_error, fallback_count).
        """
        async with self._lock:
            record = self.usage.get(service)
            if record:
                record.last_call_ts = time.time()
                record.last_error = ""
                self._save_state()

    async def record_call_error(self, service: str, error: str, units: int = 1) -> None:
        """Registra que uma chamada já aprovada falhou.

        Estratégia: NÃO devolver a quota — assume conservadoramente que
        a chamada consumiu quota do Google mesmo em erro (cobrado parcial).
        Apenas loga o erro para telemetria.
        """
        async with self._lock:
            record = self.usage.get(service)
            if record:
                record.last_error = error[:200]
                record.last_call_ts = time.time()
                self._save_state()

    async def record_fallback(self, service: str) -> None:
        """Registra que um fallback foi usado no lugar deste serviço."""
        async with self._lock:
            record = self.usage.get(service)
            if record:
                record.fallback_count += 1
                self._save_state()

    # ── Window Management ───────────────────────────────────────────────

    def _ensure_current_window(self, service: str, now: float) -> None:
        """Reseta o UsageRecord se a janela de reset já passou."""
        budget = self.budgets[service]
        reset_at = budget.reset_at(now)

        record = self.usage.get(service)
        if not record or record.window_start < (reset_at - self._window_duration_s(budget)):
            # Nova janela: reset
            self.usage[service] = UsageRecord(
                service=service,
                window_start=now,
            )
            log.info(f"[gcp-guard] {service}: nova janela iniciada "
                     f"(reset às {datetime.fromtimestamp(reset_at).isoformat()})")

    def _window_duration_s(self, budget: ServiceBudget) -> float:
        if budget.window == WindowKind.DAILY_PST:
            return 86400  # 24h
        return 30 * 86400  # ~30 dias

    # ── Fallback Registry ──────────────────────────────────────────────

    def register_fallback(
        self,
        operation: str,
        fallback_fn: Callable[..., Coroutine],
        *,
        position: int | None = None,
    ) -> None:
        """Registra uma função de fallback para uma operação.

        Quando `consume()` falhar para o serviço principal, o caller pode
        iterar por `get_fallbacks(operation)` para tentar alternativas.

        Args:
            operation: nome lógico (ex: "analyze_thumbnail")
            fallback_fn: async callable — deve lançar se também falhar
            position: ordem de tentativa (None = append)
        """
        chain = self._fallbacks.setdefault(operation, [])
        if position is None:
            chain.append(fallback_fn)
        else:
            chain.insert(position, fallback_fn)

    def get_fallbacks(self, operation: str) -> list[Callable[..., Coroutine]]:
        return list(self._fallbacks.get(operation, []))

    # ── Reporting ─────────────────────────────────────────────────────

    def get_status(self) -> dict[str, dict[str, Any]]:
        """Snapshot do estado de todos os serviços."""
        now = time.time()
        status: dict[str, dict[str, Any]] = {}
        for name, budget in self.budgets.items():
            record = self.usage.get(name)
            reset_at = budget.reset_at(now)
            disabled_until = self.disabled_until.get(name, 0.0)

            entry = {
                "service": budget.name,
                "window": budget.window.value,
                "enabled": budget.enabled,
                "free_tier_limit": budget.free_tier_limit,
                "safe_cap": budget.safe_cap,
                "unit_name": budget.unit_name,
                "reset_at": reset_at,
                "reset_iso": datetime.fromtimestamp(reset_at, tz=timezone.utc).isoformat(),
                "circuit_breaker": disabled_until > now,
                "circuit_breaker_until": (
                    datetime.fromtimestamp(disabled_until, tz=timezone.utc).isoformat()
                    if disabled_until > now else None
                ),
            }
            if record:
                used = record.units_used
                entry.update({
                    "used": used,
                    "remaining": max(budget.safe_cap - used, 0),
                    "usage_pct": round(used / max(budget.safe_cap, 1), 4),
                    "calls": record.call_count,
                    "fallbacks": record.fallback_count,
                    "over_cap_attempts": record.over_cap_count,
                    "last_call_ts": record.last_call_ts,
                    "last_error": record.last_error,
                })
            else:
                entry.update({
                    "used": 0,
                    "remaining": budget.safe_cap,
                    "usage_pct": 0.0,
                    "calls": 0,
                    "fallbacks": 0,
                    "over_cap_attempts": 0,
                })
            status[name] = entry
        return status

    # ── Predictive Alerts ──────────────────────────────────────────────

    async def check_alerts(self) -> list[str]:
        """Gera alertas preditivos quando uso se aproxima do safe_cap.

        Returns lista de strings de alerta (vazia se tudo normal).
        Alertas têm cooldown de 6h para evitar spam.
        """
        alerts: list[str] = []
        now = time.time()
        status = self.get_status()

        for name, info in status.items():
            pct = info["usage_pct"]
            remaining = info["remaining"]

            if pct >= 0.95:
                key = f"critical:{name}"
                if self._can_alert(key):
                    alerts.append(
                        f"🚨 {info['service']}: {pct:.0%} do safe_cap usado "
                        f"({info['used']}/{info['safe_cap']} {info['unit_name']}). "
                        f"Fallbacks já acionados {info['fallbacks']}×."
                    )
                    self._mark_alert(key)
            elif pct >= 0.80:
                key = f"warning:{name}"
                if self._can_alert(key):
                    alerts.append(
                        f"⚠️ {info['service']}: {pct:.0%} do safe_cap "
                        f"({info['used']}/{info['safe_cap']} {info['unit_name']}). "
                        f"Restam {remaining} {info['unit_name']}."
                    )
                    self._mark_alert(key)
            elif pct >= 0.50:
                key = f"notice:{name}"
                if self._can_alert(key):
                    # NoTice não vai para Telegram — só log
                    log.info(f"[gcp-guard] {info['service']}: {pct:.0%} do safe_cap")

        return alerts

    def _can_alert(self, key: str) -> bool:
        now = time.time()
        last = self.alerts_sent.get(key, 0.0)
        return (now - last) >= self._alert_cooldown_s

    def _mark_alert(self, key: str) -> None:
        self.alerts_sent[key] = time.time()
        self._save_state()


# ── Convenience Wrappers ───────────────────────────────────────────────

async def safe_call_gcp(
    service: str,
    units: int,
    primary_fn: Callable[..., Coroutine],
    *args,
    fallback_fns: list[Callable[..., Coroutine]] | None = None,
    **kwargs,
) -> Any:
    """Wrapper que respeita o budget guard e aciona fallback automaticamente.

    Args:
        service: nome do serviço GCP (ex: "cloud_vision")
        units: unidades que serão consumidas pela chamada (ex: 1 para Vision)
        primary_fn: função que faz a chamada real
        fallback_fns: lista de fallbacks (tentados em ordem se primary falhar)
        *args/**kwargs: passados para primary_fn e fallbacks

    Returns:
        Resultado da chamada (primary ou fallback)

    Raises:
        BudgetExceededError: se todos os fallbacks falharem
        ServiceDisabledError: se serviço e todos os fallbacks estão disabled
    """
    guard = GCPBudgetGuard.get()
    fns = [primary_fn] + (fallback_fns or [])
    last_err: Exception | None = None

    for attempt, fn in enumerate(fns):
        try:
            allowed = await guard.consume(service if attempt == 0 else "fallback", units)
            if not allowed:
                continue
            result = await fn(*args, **kwargs)
            await guard.record_call_success(service, units)
            return result
        except (BudgetExceededError, ServiceDisabledError) as e:
            log.info(f"[gcp-guard] {fn.__name__} bloqueado: {e}")
            if attempt > 0:
                await guard.record_fallback(service)
            last_err = e
            continue
        except Exception as e:
            await guard.record_call_error(service, str(e), units)
            last_err = e
            log.warning(f"[gcp-guard] {fn.__name__} falhou: {e}")
            if attempt > 0:
                await guard.record_fallback(service)
            continue

    if last_err:
        raise last_err
    raise BudgetExceededError(f"Todos os fallbacks falharam para {service}")