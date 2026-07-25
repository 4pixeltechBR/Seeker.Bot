"""PromptographDailyReport — Relatorio diario 08:00 no Telegram.

Roda as 08:00 todo dia. Cobia o estado do system Promptograph integrado:
  - Notas criadas no Obsidian Inbox hoje (dd/mm/yyyy) + no ultimo 7d (tendencia)
  - Notas detectadas como 'prompt' (via detectors.detect_content_class)
  - Empresas/modelos detectados nos prompts do dia
  - Status da conexao WhatsApp (Evolution API) + grupo alvo
  - Estatisticas do catalogo Promptograph (MCP, 5317 prompts)
  - Score medio das validacoes feitas via /validate nas ultimas 24h (via log
    file heuristic se disponivel, ou médio dos presets como baseline)

Zero custo de LLM (tudo heuristico, stdlib + glob). Pattern espelhado em
custom_extension/goal.py.
"""

from __future__ import annotations

import logging
import os
import re
import textwrap
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.core.pipeline import SeekerPipeline
from src.core.goals.protocol import (
    GoalBudget, GoalResult, GoalStatus, NotificationChannel,
)
from src.skills.promptograph import PRESET_TEMPLATES

log = logging.getLogger("seeker.promptograph_daily")


# Path do Inbox do Obsidian (mesmo usado pelo vault_writer.py:14)
def _vault_inbox() -> Path:
    """Res pathwayvault Inbox - espelha knowledge_vault/vault_writer.py."""
    try:
        from src.skills.knowledge_vault.vault_writer import INBOX_PATH
        return Path(INBOX_PATH)
    except Exception:
        return Path(r"D:\Obsidian\Segundo Cérebro\Segundo Cérebro\Inbox")


class PromptographDailyReportGoal:
    """Daily 08:00 Telegram briefing do sistema Promptograph integrado.

    - Janela catch-up: 6h (como custom_extension)
    - Budget: $0 (heuristic-only)
    - Sem custo de LLM
    """

    SCHEDULE_HOUR = 8
    SCHEDULE_MINUTE = 0
    CATCHUP_WINDOW_HOURS = 6

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._last_runs: set[str] = set()
        self._budget = GoalBudget(max_per_cycle_usd=0.0, max_daily_usd=0.0)

    @property
    def name(self) -> str:
        return "promptograph_daily"

    @property
    def interval_seconds(self) -> int:
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
        now = datetime.now()
        target_today = now.replace(hour=self.SCHEDULE_HOUR, minute=self.SCHEDULE_MINUTE,
                                   second=0, microsecond=0)
        window_end = target_today + timedelta(hours=self.CATCHUP_WINDOW_HOURS)

        run_id = now.strftime("%Y-%m-%d")
        if run_id in self._last_runs:
            return GoalResult(success=True, summary=f"Ja executado hoje ({run_id})",
                              cost_usd=0.0)

        if not (target_today <= now <= window_end):
            return GoalResult(
                success=True,
                summary=f"Fora da janela de catch-up ({self.SCHEDULE_HOUR:02d}:00 -> +{self.CATCHUP_WINDOW_HOURS}h)",
                cost_usd=0.0,
            )

        self._status = GoalStatus.RUNNING

        try:
            report = await self._build_report(now)
        except Exception as e:
            log.exception("[promptograph_daily] falhou ao montar relatorio")
            self._status = GoalStatus.ERROR
            return GoalResult(success=False, summary=f"Erro: {e}", cost_usd=0.0)

        self._last_runs.add(run_id)
        self._status = GoalStatus.IDLE
        return GoalResult(
            success=True,
            summary="Relatorio enviado",
            notification=report,
            cost_usd=0.0,
            data={"date": run_id},
        )

    # ── Coleta de dados ───────────────────────────────────────────

    async def _build_report(self, now: datetime) -> str:
        today_str = now.strftime("%Y-%m-%d")
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        header = [f"<b>深海 Promptograph — Relatorio diario ({now.strftime('%d/%m/%Y')})</b>", ""]

        # ── Bloco 1: Inbox Obsidian ──
        inbox = _vault_inbox()
        notes_today, prompts_today, companies_today = self._scan_inbox(inbox, today_str)
        notes_week = self._count_inbox_last_n_days(inbox, n=7, ref=now.date())

        if notes_today == 0:
            header.append("<b>Inbox Obsidian</b>: <i>nenhuma nota criada hoje</i>")
        else:
            header.append(f"<b>Inbox Obsidian</b>: <b>{notes_today}</b> nota(s) hoje | "
                          f"<b>{notes_week}</b> nos ultimos 7d")
            if prompts_today > 0:
                comp_str = ", ".join(sorted(companies_today)) if companies_today else "?"
                header.append(f"   🤖 <b>{prompts_today}</b> detectada(s) como <i>prompt de IA</i> "
                              f"(via detector heuristico)")
                if companies_today:
                    header.append(f"   🏢 Empresas: <code>{comp_str}</code>")

        # ── Bloco 2: WhatsApp Evolution API ──
        wa_block = await self._whatsapp_block()
        header.append("")
        header.append(wa_block)

        # ── Bloco 3: Catalogo MCP Promptograph ──
        catalog = self._catalog_stats()
        header.append("")
        header.append("<b>🔌 MCP Promptograph</b>")
        for line in catalog:
            header.append(line)

        # ── Bloco 4: Validacoes /generate presets (baseline score) ──
        scores = self._compute_preset_scores()
        header.append("")
        header.append("<b>✨ Presets disponiveis (/generate)</b>")
        for name, info in scores.items():
            mark = "✅" if info["grade"].startswith("A") else ("🟡" if info["grade"].startswith("B") else "❌")
            header.append(
                f"{mark} <code>{name}</code> - {info['score']}% ({info['grade']}), ~{info['tokens']} tok"
            )

        # ── Bloco 5: Comandos disponiveis ──
        header.append("")
        header.append(
            "<b>Comandos:</b> "
            "<code>/validate</code> (auditar prompt) | "
            "<code>/generate</code> (gerar) | "
            "<code>/wa</code> (status WhatsApp) | "
            "<code>/mcp</code> (tools)"
        )
        return "\n".join(header)

    def _scan_inbox(self, inbox: Path, today_str: str) -> tuple[int, int, set[str]]:
        """Conta notas criadas hoje + detecta prompts por tag frontmatter type=prompt."""
        notes_today = 0
        prompts_today = 0
        companies: set[str] = set()
        if not inbox.exists():
            return 0, 0, set()
        for f in inbox.glob(f"{today_str} - *.md"):
            notes_today += 1
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            # Frontmatter type: prompt -> detectado pela heuristica
            m = re.search(r"^type:\s*(\S+)", content, re.MULTILINE)
            if m and m.group(1).strip().lower() == "prompt":
                prompts_today += 1
            # Tag de empresa (lowercased by analyzer: "anthropic", "openai")
            tag_match = re.search(r"^tags:\s*\[(.*?)\]", content, re.MULTILINE)
            if tag_match:
                tags_str = tag_match.group(1)
                for known in ["anthropic", "openai", "google", "xai", "meta",
                              "mistral", "deepseek", "cursor", "devin", "perplexity"]:
                    if known in tags_str.lower():
                        companies.add(known.capitalize())
        return notes_today, prompts_today, companies

    def _count_inbox_last_n_days(self, inbox: Path, n: int, ref: date) -> int:
        if not inbox.exists():
            return 0
        total = 0
        for i in range(n):
            d = (ref - timedelta(days=i)).strftime("%Y-%m-%d")
            total += sum(1 for _ in inbox.glob(f"{d} - *.md"))
        return total

    async def _whatsapp_block(self) -> str:
        """Status do Evolution API + grupo alvo. Tolerante a falhas."""
        try:
            from src.channels.whatsapp.client import WhatsAppClient
            from src.channels.telegram.commands.whatsapp_config import _load_config
            client = WhatsAppClient()
            if not client.is_configured:
                return ("<b>WhatsApp</b>: <i>nao configurado</i> "
                        "(<code>EVOLUTION_API_KEY</code> faltando)")
            cfg = _load_config()
            target = cfg.get("target", {}) or {}
            group_id = target.get("group_id", "")
            state = await client.connection_state()
            await client.close()
            conn = state.get("state", "?") if isinstance(state, dict) else "?"
            icon = "🟢" if conn == "open" else "🔴"
            g_short = group_id.split("@")[0][-12:] if group_id else "?"
            mode = cfg.get("mode", "evolution_api")
            return (
                f"<b>WhatsApp</b>: {icon} <code>{conn}</code> "
                f"(instance: <code>{getattr(client, 'instance', '?')}</code>)\n"
                f"   Grupo: <code>{g_short}</code> | Modo: <code>{mode}</code>"
            )
        except Exception as e:
            return f"<b>WhatsApp</b>: <i>erro ao ler status</i> - <code>{e}</code>"

    def _catalog_stats(self) -> list[str]:
        """Stats do catalogo MCP indexado (5317 prompts) - stdlib only."""
        try:
            from src.skills.promptograph import PRESET_TEMPLATES
            idx_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "promptograph" / "index_filtered.json"
            if not idx_path.exists():
                return [f"<i>Catalogo offline ({idx_path.name} ausente)</i>"]
            import json
            data = json.loads(idx_path.read_text(encoding="utf-8"))
            total = len(data)
            comp_count = Counter(p.get("company", "?") for p in data)
            top5 = comp_count.most_common(5)
            top_str = ", ".join(f"{c}:{n}" for c, n in top5)
            return [
                f"Catalogo: <b>{total:,}</b> prompts indexados",
                f"Top 5 empresas: <code>{top_str}</code>",
            ]
        except Exception as e:
            return [f"<i>Catalogo indisponivel</i> (<code>{e}</code>)"]

    def _compute_preset_scores(self) -> dict[str, dict]:
        """Re-valida os 5 presets pra mostrar score baseline atual."""
        from src.skills.promptograph import build_prompt, validate_prompt
        out = {}
        for name, p in PRESET_TEMPLATES.items():
            try:
                prompt = build_prompt(p["spec"])
                v = validate_prompt(prompt)
                out[name] = {
                    "score": v["score"],
                    "grade": v["grade"],
                    "tokens": v["stats"]["tokens_estimate"],
                }
            except Exception:
                out[name] = {"score": 0, "grade": "?", "tokens": 0}
        return out

    # ── Estado (serialize/load - igual custom_extension) ──────────
    def serialize_state(self) -> dict:
        return {"last_runs": list(self._last_runs)}

    def load_state(self, state: dict) -> None:
        self._last_runs = set(state.get("last_runs", []))


def create_goal(pipeline: SeekerPipeline) -> PromptographDailyReportGoal:
    return PromptographDailyReportGoal(pipeline)
