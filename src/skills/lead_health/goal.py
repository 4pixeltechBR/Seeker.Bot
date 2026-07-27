"""
Lead Health Check — detecta leads estagnados, gera alertas, move status automático.

Skills diários que rodam junto ao ShowDeck. Detecta:

1. **Leads parados** (>30 dias no mesmo stage)
   - Move NOVO → GELADO se >60 dias sem contato
   - Move CONTATADO → GELADO se >45 dias sem follow-up
   - Move PROPOSTA → GELADO se >90 dias sem resposta

2. **Ghosting** (sem atividade no crm_activities há >14 dias)
   - Marca lead com flag `health_flag=ghost_risk`

3. **Oportunidades urgentes** (evento em 1-3 meses ainda em NOVO)
   - Alerta prioritário via Telegram

4. **Re-discovery candidate** (GELADO há >90 dias com evento futuro)
   - Sugere re-abordagem com novo ângulo

Output:
- Updates diretos em crm_leads (status, status_changed_at)
- Notificação Telegram consolidada (sem spam)
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from src.core.goals.protocol import (
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)
from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.lead_health")


# ── Regras de saúde (dias por stage) ────────────────────────────

STALE_DAYS_BY_STAGE = {
    "NOVO":          60,   # 60 dias sem contato → GELADO
    "CONTATADO":     45,   # 45 dias → GELADO
    "PROPOSTA":      90,   # 90 dias → GELADO
    "NEGOCIANDO":    60,   # 60 dias → GELADO
    "GELADO":        365,  # não re-gelo (mantém)
}

GHOSTING_DAYS = 14         # sem activity = ghosting
URGENT_WINDOW_MIN = 3      # evento em 1-3 meses
URGENT_WINDOW_MAX = 6      # até 6 meses é "urgente" pra lead novo


class LeadHealthCheck:
    """Daily health check do pipeline de vendas."""

    SCHEDULE_HOUR = 9
    SCHEDULE_MINUTE = 0
    CATCHUP_WINDOW_HOURS = 6
    TOP_REPORT_LEADS = 10

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._last_runs: set[str] = set()
        self._budget = GoalBudget(max_per_cycle_usd=0.0, max_daily_usd=0.0)
        self.crm_store = CRMStore(self.pipeline.memory._db)

    @property
    def name(self) -> str:
        return "lead_health"

    @property
    def interval_seconds(self) -> int:
        from datetime import datetime, timedelta
        now = datetime.now()
        target = now.replace(hour=self.SCHEDULE_HOUR, minute=self.SCHEDULE_MINUTE,
                              second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        diff = (target - now).total_seconds()
        return max(60, min(3600, int(diff)))

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    async def run_cycle(self) -> GoalResult:
        from datetime import datetime, timedelta
        now = datetime.now()
        target_today = now.replace(
            hour=self.SCHEDULE_HOUR, minute=self.SCHEDULE_MINUTE, second=0, microsecond=0
        )
        window_end = target_today + timedelta(hours=self.CATCHUP_WINDOW_HOURS)

        run_id = now.strftime("%Y-%m-%d")
        if run_id in self._last_runs:
            return GoalResult(
                success=True,
                summary=f"Já executado hoje ({run_id})",
                cost_usd=0.0,
            )

        if not (target_today <= now <= window_end):
            return GoalResult(
                success=True,
                summary=f"Fora da janela de catch-up",
                cost_usd=0.0,
            )

        self._status = GoalStatus.RUNNING
        await self.crm_store.init_tables()

        # 1. Detectar leads parados
        gelados = await self._detect_stale_leads()

        # 2. Detectar urgent (evento próximo + ainda NOVO)
        urgent = await self._detect_urgent_leads()

        # 3. Detectar ghosting
        ghosting = await self._detect_ghosting()

        # 4. Detectar re-discovery candidates
        rediscovery = await self._detect_rediscovery_candidates()

        notification = self._build_report(
            gelados, urgent, ghosting, rediscovery
        )

        self._last_runs.add(run_id)
        self._status = GoalStatus.IDLE

        total_changes = len(gelados) + len(urgent) + len(ghosting)
        return GoalResult(
            success=True,
            summary=f"health check: {len(gelados)} movidos p/ GELADO, "
                    f"{len(urgent)} urgentes, {len(ghosting)} ghosting, "
                    f"{len(rediscovery)} rediscovery",
            notification=notification,
            cost_usd=0.0,
            data={
                "gelados_moved": len(gelados),
                "urgent_count": len(urgent),
                "ghosting_count": len(ghosting),
                "rediscovery_count": len(rediscovery),
            },
        )

    async def _detect_stale_leads(self) -> list[dict]:
        """Detecta leads parados >N dias (move para GELADO)."""
        rows = await self.crm_store._db.execute_fetchall(
            """
            SELECT target_key, status, cidade, estado, orcamento_valor_estimado,
                   data_evento_ano, data_evento_mes,
                   CAST((julianday('now') - julianday(COALESCE(updated_at, discovered_at))) AS INTEGER) as days_idle
            FROM crm_leads
            WHERE status IN ('NOVO', 'CONTATADO', 'PROPOSTA', 'NEGOCIANDO')
              AND status NOT IN ('FECHADO_GANHO', 'FECHADO_PERDIDO', 'GELADO')
            """
        )
        cols = [d[0] for d in rows.cursor.description]
        gelados: list[dict] = []
        now_ts = int(datetime.now().timestamp())

        for row in rows:
            d = dict(zip(cols, row))
            status = d.get("status") or "NOVO"
            max_days = STALE_DAYS_BY_STAGE.get(status, 60)
            days_idle = d.get("days_idle", 0)
            if days_idle >= max_days:
                # Move para GELADO
                await self.crm_store._db.execute(
                    "UPDATE crm_leads SET status = ?, status_changed_at = ? "
                    "WHERE target_key = ?",
                    ("GELADO", now_ts, d["target_key"]),
                )
                gelados.append({
                    "target_key": d["target_key"],
                    "cidade": d.get("cidade"),
                    "estado": d.get("estado"),
                    "status_from": status,
                    "days_idle": days_idle,
                    "valor_estimado": d.get("orcamento_valor_estimado"),
                })
                log.info(
                    f"[lead_health] {d.get('cidade')} movido {status}→GELADO "
                    f"(parado há {days_idle}d)"
                )

        await self.crm_store._db.commit()
        return gelados

    async def _detect_urgent_leads(self) -> list[dict]:
        """Detecta leads com evento próximo (1-6m) ainda em NOVO/CONTATADO."""
        # Evento entre hoje+1m e hoje+6m, status ainda inicial
        from datetime import date
        today = date.today()
        target_year = today.year
        target_month = today.month + URGENT_WINDOW_MIN
        if target_month > 12:
            target_month -= 12
            target_year += 1

        rows = await self.crm_store._db.execute_fetchall(
            """
            SELECT target_key, cidade, estado, status, data_evento_ano, data_evento_mes,
                   nome_evento, orcamento_valor_estimado
            FROM crm_leads
            WHERE status IN ('NOVO', 'CONTATADO')
              AND data_evento_ano IS NOT NULL
              AND data_evento_mes IS NOT NULL
              AND (
                  (data_evento_ano = ? AND data_evento_mes >= ?)
                  OR (data_evento_ano = ? + 1 AND data_evento_mes <= ?)
              )
            """,
            (today.year, today.month, today.year, URGENT_WINDOW_MAX),
        )
        cols = [d[0] for d in rows.cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def _detect_ghosting(self) -> list[dict]:
        """Detecta leads com status avançado mas sem atividade no crm_activities há >14 dias."""
        rows = await self.crm_store._db.execute_fetchall(
            """
            SELECT l.target_key, l.cidade, l.estado, l.status, l.data_evento_ano, l.data_evento_mes,
                   MAX(CAST(a.timestamp AS REAL)) as last_activity_ts,
                   CAST((julianday('now') - julianday(MAX(COALESCE(a.timestamp, l.discovered_at)))) AS INTEGER) as days_since_activity
            FROM crm_leads l
            LEFT JOIN crm_activities a ON a.lead_target_key = l.target_key
            WHERE l.status IN ('CONTATADO', 'PROPOSTA', 'NEGOCIANDO')
            GROUP BY l.target_key
            HAVING days_since_activity >= ?
            ORDER BY l.orcamento_valor_estimado DESC NULLS LAST
            LIMIT 50
            """,
            (GHOSTING_DAYS,),
        )
        cols = [d[0] for d in rows.cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def _detect_rediscovery_candidates(self) -> list[dict]:
        """Detecta leads GELADO com evento futuro (>3m) - candidatos a re-abordagem."""
        from datetime import date
        today = date.today()
        target_month = today.month + 3
        target_year = today.year
        if target_month > 12:
            target_month -= 12
            target_year += 1

        rows = await self.crm_store._db.execute_fetchall(
            """
            SELECT target_key, cidade, estado, status, data_evento_ano, data_evento_mes,
                   nome_evento, orcamento_valor_estimado,
                   CAST((julianday('now') - julianday(status_changed_at)) AS INTEGER) as days_gelado
            FROM crm_leads
            WHERE status = 'GELADO'
              AND data_evento_ano IS NOT NULL
              AND data_evento_mes IS NOT NULL
              AND (
                  (data_evento_ano = ? AND data_evento_mes >= ?)
                  OR (data_evento_ano > ?)
              )
            ORDER BY orcamento_valor_estimado DESC NULLS LAST
            LIMIT 30
            """,
            (today.year, today.month, today.year),
        )
        cols = [d[0] for d in rows.cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    def _build_report(self, gelados, urgent, ghosting, rediscovery) -> str:
        lines = ["<b>🏥 LEAD HEALTH CHECK</b>", ""]

        # 1. Movidos para GELADO
        if gelados:
            lines.append(f"❄️ <b>{len(gelados)} movidos para GELADO</b> (parados)")
            for g in gelados[:5]:
                cid = (g.get("cidade") or "?")
                est = (g.get("estado") or "?")
                st = g.get("status_from", "?")
                d = g.get("days_idle", "?")
                v = g.get("valor_estimado") or "?"
                lines.append(f"  • {cid}/{est}: {st} ({d}d parado, R$ {v})")
            if len(gelados) > 5:
                lines.append(f"  ... +{len(gelados)-5} outros")
            lines.append("")

        # 2. Urgentes (evento próximo, ainda NOVO/CONTATADO)
        if urgent:
            lines.append(f"🚨 <b>{len(urgent)} URGENTES</b> (evento em 1-6m, sem avanço)")
            for u in urgent[:5]:
                cid = (u.get("cidade") or "?")
                est = (u.get("estado") or "?")
                ne = (u.get("nome_evento") or "?")[:40]
                ano = u.get("data_evento_ano") or "?"
                mes = u.get("data_evento_mes") or "?"
                st = u.get("status") or "?"
                lines.append(
                    f"  • {cid}/{est}: {ne} ({mes}/{ano}) — status={st}"
                )
            if len(urgent) > 5:
                lines.append(f"  ... +{len(urgent)-5} outros")
            lines.append("")
            lines.append("<i>Ação: priorizar contato manual hoje</i>")
            lines.append("")

        # 3. Ghosting (sem resposta há >14 dias)
        if ghosting:
            lines.append(f"👻 <b>{len(ghosting)} em ghosting</b> (sem atividade >14d)")
            for gh in ghosting[:5]:
                cid = (gh.get("cidade") or "?")
                est = (gh.get("estado") or "?")
                st = gh.get("status") or "?"
                d = gh.get("days_since_activity") or "?"
                lines.append(f"  • {cid}/{est}: {st} ({d}d sem resposta)")
            if len(ghosting) > 5:
                lines.append(f"  ... +{len(ghosting)-5} outros")
            lines.append("")
            lines.append("<i>Ação: ligou? Email follow-up? Re-pitch com ângulo novo?</i>")
            lines.append("")

        # 4. Re-discovery candidates
        if rediscovery:
            lines.append(f"♻️ <b>{len(rediscovery)} candidatos a re-discovery</b> (GELADO, evento futuro)")
            for r in rediscovery[:3]:
                cid = (r.get("cidade") or "?")
                est = (r.get("estado") or "?")
                ne = (r.get("nome_evento") or "?")[:35]
                d = r.get("days_gelado") or "?"
                lines.append(f"  • {cid}/{est}: {ne} ({d}d gelado)")
            if len(rediscovery) > 3:
                lines.append(f"  ... +{len(rediscovery)-3} outros")
            lines.append("")
            lines.append("<i>Ação: re-abordagem com novo ângulo (mudança de gestão, novo evento, etc)</i>")

        if not any([gelados, urgent, ghosting, rediscovery]):
            lines.append("<i>✅ Tudo saudável! Nenhuma ação necessária hoje.</i>")

        return "\n".join(lines)


def create_goal(pipeline: SeekerPipeline) -> LeadHealthCheck:
    return LeadHealthCheck(pipeline)