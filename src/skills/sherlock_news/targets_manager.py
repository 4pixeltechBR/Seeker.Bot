"""
Seeker.Bot — SherlockNews Targets Manager
src/skills/sherlock_news/targets_manager.py
"""

import json
import os
import uuid
from datetime import datetime

TARGETS_FILE = os.path.join(os.path.dirname(__file__), "targets.json")

def _load_targets() -> list:
    if not os.path.exists(TARGETS_FILE):
        return []
    try:
        with open(TARGETS_FILE, "r", encoding="utf-8") as f:
            targets = json.load(f)
            # Migration to add ID and category to old targets
            changed = False
            for t in targets:
                if "id" not in t:
                    t["id"] = str(uuid.uuid4())
                    changed = True
                if "category" not in t:
                    t["category"] = "llm" # default legacy
                    changed = True
            if changed:
                _save_targets(targets)
            return targets
    except Exception:
        return []

def _save_targets(targets: list) -> None:
    with open(TARGETS_FILE, "w", encoding="utf-8") as f:
        json.dump(targets, f, indent=4)

def add_target(model_name: str, category: str = "llm") -> str:
    if not model_name:
        return ""
        
    targets = _load_targets()

    # Evita duplicatas
    for t in targets:
        if t.get("name", "").lower() == model_name.lower() and t.get("status") == "pending":
            return t.get("id", "")

    new_id = str(uuid.uuid4())
    targets.append({
        "id": new_id,
        "name": model_name,
        "category": category,
        "status": "pending",
        "added_at": datetime.now().isoformat()
    })

    _save_targets(targets)
    return new_id

def remove_target(target_id: str) -> bool:
    targets = _load_targets()
    initial_len = len(targets)
    targets = [t for t in targets if t.get("id") != target_id]
    if len(targets) < initial_len:
        _save_targets(targets)
        return True
    return False

def update_status(target_id: str, status: str) -> bool:
    targets = _load_targets()
    for t in targets:
        if t.get("id") == target_id:
            t["status"] = status
            _save_targets(targets)
            return True
    return False

def list_targets() -> list[str]:
    """Legacy compatibility"""
    targets = _load_targets()
    return [t.get("name", "") for t in targets if t.get("status") == "pending"]

def list_all_targets() -> list[dict]:
    """Returns full target dicts"""
    return _load_targets()
