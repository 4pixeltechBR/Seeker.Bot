from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _data_dir() -> Path:
    return _project_root() / "data" / "research_machine"


def _runs_dir() -> Path:
    d = _data_dir() / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path() -> Path:
    return _data_dir() / "state.json"


def _empty_state() -> dict[str, Any]:
    return {
        "queries": [],
        "last_cursor": "",
        "total_cost_usd": 0.0,
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


def save_run(run_id: str, data: dict) -> None:
    path = _runs_dir() / f"{run_id}.json"
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_run(run_id: str) -> dict | None:
    path = _runs_dir() / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
