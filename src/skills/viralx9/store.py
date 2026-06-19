"""
viralx9.store — Estado persistente (restart-safe) do goal ViralX9.

Arquivo: data/viralx9/state.json
Estrutura:
{
  "candidatos": {
    "<id curto (8 hex)>": {
        "id": "...",
        "tema": "... (PT-BR)",
        "tema_original": "...",
        "idioma_original": "en|de|ja|ko|...",
        "nicho": "microbiologia_ia",
        "justificativa": "🌏 Ásia · 🔥 2.4x a mediana do @Canal · ...",
        "video_id": "...",
        "video_url": "...",
        "canal": "@Canal",
        "regiao": "asia",
        "outlier": 2.4,
        "velocity": 9000.0,
        "status": "pending|approved|rejected",
        "created_at": "2026-06-15T08:00:00"
    }
  },
  "vistos": ["<video_id>", ...],
  "last_run": {"08:00": "2026-06-15", "20:00": "2026-06-14"},
  "canais_sugeridos": {
    "<hash curto>": {"url": "...", "nicho": "...", "regiao": "...", "ocorrencias": 2}
  }
}
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _data_dir() -> Path:
    gdrive_base = os.getenv("GDRIVE_PATH")
    if gdrive_base and os.path.exists(gdrive_base):
        return Path(gdrive_base) / "viralx9"
    return _project_root() / "data" / "viralx9"


def _state_path() -> Path:
    return _data_dir() / "state.json"


def short_id(*parts: str, length: int = 8) -> str:
    """Hash curto e estável (cabe em callback_data, limite de 64 bytes)."""
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def _empty_state() -> dict[str, Any]:
    return {
        "candidatos": {},
        "vistos": [],
        "last_run": {},
        "canais_sugeridos": {},
        "medians": {},
    }


def load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return _empty_state()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _empty_state()
    base = _empty_state()
    base.update(data)
    return base


def save_state(state: dict[str, Any]) -> None:
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    path = _state_path()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
