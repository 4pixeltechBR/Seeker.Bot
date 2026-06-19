"""
viralx9.goal — Goal autônomo: minera canais concorrentes (US/EU/Ásia), nas
janelas 08:00 e 20:00 BRT, e notifica temas quentes no Telegram com
justificativa + botões Aprovar/Rejeitar.

Aprovar -> bridge.create_project cria um projeto VAZIO (source=seeker) na
curadoria do Modo Manual do ViralClip; a produção (script/visual/motion/seo)
é 100% manual a partir daí.

Scheduler roda por intervalo (interval_seconds) — este goal "acorda" a cada
~30min e só executa a mineração de fato dentro das janelas configuradas
(gate por horário + last_run por janela/dia).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.core.goals.protocol import (
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)
from src.skills.viralx9 import store
from src.skills.viralx9.miner import mine_nicho

log = logging.getLogger("seeker.viralx9")

try:
    from zoneinfo import ZoneInfo

    BRT = ZoneInfo("America/Sao_Paulo")
except Exception:  # pragma: no cover - fallback sem tzdata
    BRT = None

# Janelas de mineração (HH:MM, BRT). Soft — o método de outlier numa janela de
# frescor de ~14 dias captura o breakout na rodada seguinte de qualquer forma.
WINDOWS = ["08:00", "14:00", "20:00"]

MAX_NOTIFY_PER_CYCLE = 8  # evita flood de mensagens num único ciclo


def _now_brt() -> datetime:
    if BRT is not None:
        return datetime.now(BRT)
    return datetime.now()


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _channels_path() -> Path:
    return _project_root() / "config" / "viralx9_channels.yaml"


def _load_channels() -> dict[str, Any]:
    path = _channels_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log.error(f"[viralx9] Falha ao carregar {path}: {e}")
        return {}


_YAML_HEADER = (
    "# viralx9_channels.yaml - Seed de canais concorrentes para mineracao do ViralX9.\n"
    "# URLs canonicas /channel/UCID (nao quebram se o @handle mudar).\n"
    "# 'nome' e rotulo humano; o miner usa url+regiao. 'ativo: false' pausa o canal\n"
    "# (gerenciavel via /vx9_pausar | /vx9_ativar | /vx9_remover no Telegram).\n"
    "# 'expansao_sugerida' e preenchido pelo goal e aprovado via Telegram.\n\n"
)


def _save_channels(cfg: dict[str, Any]) -> None:
    path = _channels_path()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_YAML_HEADER)
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    tmp.replace(path)


class ViralX9Goal:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.20, max_daily_usd=1.0)

    @property
    def name(self) -> str:
        return "viralx9"

    @property
    def interval_seconds(self) -> int:
        return 1800  # 30 min — gate por horário decide se minera de fato

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    def serialize_state(self) -> dict:
        return {}  # estado persistido em data/viralx9/state.json (store.py)

    def load_state(self, state: dict) -> None:
        pass

    # ── janela de horário ────────────────────────────────────────────────
    def _due_window(self, state: dict) -> str | None:
        now = _now_brt()
        today = now.date().isoformat()
        now_minutes = now.hour * 60 + now.minute
        last_run = state.get("last_run", {})

        for window in WINDOWS:
            if last_run.get(window) == today:
                continue
            w_hour, w_min = (int(p) for p in window.split(":"))
            if now_minutes >= w_hour * 60 + w_min:
                return window
        return None

    # ── ciclo principal ──────────────────────────────────────────────────
    async def run_cycle(self) -> GoalResult:
        state = store.load_state()

        window = self._due_window(state)
        if window is None:
            return GoalResult(success=True, summary="Fora da janela de mineração.", notification=None)

        self._status = GoalStatus.RUNNING

        channels_cfg = _load_channels()
        if not channels_cfg:
            log.warning("[viralx9] config/viralx9_channels.yaml vazio ou ausente.")
            state.setdefault("last_run", {})[window] = _now_brt().date().isoformat()
            store.save_state(state)
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary=f"Janela {window}: sem canais configurados (seed vazia).",
                notification=None,
            )

        vistos = set(state.get("vistos", []))
        candidatos_dict = state.setdefault("candidatos", {})

        novos: list[dict] = []
        total_cost = 0.0

        # Throttle para não estourar rate-limit do YouTube (no máximo 2 recálculos de mediana por ciclo)
        throttle_context = {"uncached_allowed": 2}

        for nicho, cfg in channels_cfg.items():
            # Pula canais pausados (ativo: false) — curadoria via Telegram.
            seed = [c for c in ((cfg or {}).get("seed") or []) if c.get("ativo", True)]
            if not seed:
                continue
            try:
                medians_cache = state.setdefault("medians", {})
                found, n_cost = await mine_nicho(
                    nicho, seed, vistos, self.pipeline, medians_cache, throttle_context
                )
                total_cost += n_cost
            except Exception as e:
                log.error(f"[viralx9] Erro minerando nicho {nicho}: {e}")
                continue

            for cand in found:
                vid = cand["video_id"]
                if vid in vistos:
                    continue
                cid = store.short_id(vid)
                cand["id"] = cid
                cand["status"] = "pending"
                cand["created_at"] = datetime.now().isoformat()
                candidatos_dict[cid] = cand
                vistos.add(vid)
                novos.append(cand)

        state["vistos"] = list(vistos)
        state.setdefault("last_run", {})[window] = _now_brt().date().isoformat()
        store.save_state(state)
        self._status = GoalStatus.IDLE

        if not novos:
            return GoalResult(
                success=True,
                summary=f"Janela {window}: nenhum candidato novo (outlier >= 2x).",
                cost_usd=total_cost,
            )

        novos = novos[:MAX_NOTIFY_PER_CYCLE]

        lines = [f"🔭 <b>ViralX9 — Janela {window} BRT</b>", f"{len(novos)} tema(s) em alta nos concorrentes:\n"]
        buttons: list[list[dict]] = []
        for idx, cand in enumerate(novos, 1):
            # Tema numerado; botões com o MESMO número → mapeamento inequívoco.
            lines.append(f"<b>{idx}.</b> 💡 <b>{cand['tema']}</b>\n   {cand['justificativa']}")
            buttons.append(
                [
                    {"text": f"{idx} ✅ Aprovar", "callback_data": f"vx9_ok:{cand['id']}"},
                    {"text": f"{idx} ❌ Rejeitar", "callback_data": f"vx9_no:{cand['id']}"},
                ]
            )

        notification = "\n\n".join(lines)

        return GoalResult(
            success=True,
            summary=f"Janela {window}: {len(novos)} candidato(s) notificado(s).",
            notification=notification,
            cost_usd=total_cost,
            data={"buttons": buttons},
        )


def create_goal(pipeline) -> ViralX9Goal:
    """Factory chamada pelo Goal Registry."""
    return ViralX9Goal(pipeline)
