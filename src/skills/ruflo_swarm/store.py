from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _data_dir() -> Path:
    return _project_root() / "data" / "ruflo_swarm"


def _state_path() -> Path:
    return _data_dir() / "state.json"


def short_id(*parts: str, length: int = 8) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def _empty_state() -> dict[str, Any]:
    return {
        "bandit": {"arms": {}, "rounds": 0},
        "task_history": {},
        "calibration_runs": [],
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
