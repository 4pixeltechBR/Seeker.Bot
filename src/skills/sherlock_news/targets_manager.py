"""
Seeker.Bot — SherlockNews Targets Manager
src/skills/sherlock_news/targets_manager.py
"""

import json
import os
from datetime import datetime

TARGETS_FILE = os.path.join(os.path.dirname(__file__), "targets.json")


import uuid

def add_target(model_name: str, category: str = "LLM") -> bool:
    if not model_name:
        return False

    targets = []
    if os.path.exists(TARGETS_FILE):
        try:
            with open(TARGETS_FILE, "r", encoding="utf-8") as f:
                targets = json.load(f)
        except:
            targets = []

    # Evita duplicatas (mesmo nome e categoria)
    for t in targets:
        if t["name"].lower() == model_name.lower() and t.get("category", "LLM") == category:
            return True

    targets.append(
        {
            "id": str(uuid.uuid4())[:8],
            "name": model_name,
            "category": category,
            "status": "pending",
            "added_at": datetime.now().isoformat(),
        }
    )

    with open(TARGETS_FILE, "w", encoding="utf-8") as f:
        json.dump(targets, f, indent=4)

    return True


def list_targets() -> list[str]:
    """Retorna apenas nomes dos alvos pendentes (compatibilidade)."""
    if not os.path.exists(TARGETS_FILE):
        return []
    try:
        with open(TARGETS_FILE, "r", encoding="utf-8") as f:
            targets = json.load(f)
            return [t["name"] for t in targets if t["status"] == "pending"]
    except:
        return []


def list_all_targets() -> list[dict]:
    """Retorna lista completa de objetos alvo."""
    if not os.path.exists(TARGETS_FILE):
        return []
    try:
        with open(TARGETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def remove_target(target_id: str) -> bool:
    """Remove um alvo pelo ID ou Nome."""
    if not os.path.exists(TARGETS_FILE):
        return False
    try:
        with open(TARGETS_FILE, "r", encoding="utf-8") as f:
            targets = json.load(f)
        
        new_targets = [t for t in targets if t.get("id") != target_id and t.get("name") != target_id]
        
        if len(new_targets) == len(targets):
            return False
            
        with open(TARGETS_FILE, "w", encoding="utf-8") as f:
            json.dump(new_targets, f, indent=4)
        return True
    except:
        return False
