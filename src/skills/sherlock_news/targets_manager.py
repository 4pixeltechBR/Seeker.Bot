"""
Seeker.Bot — SherlockNews Targets Manager
src/skills/sherlock_news/targets_manager.py
"""

import json
import os
from datetime import datetime

TARGETS_FILE = os.path.join(os.path.dirname(__file__), "targets.json")

def add_target(model_name: str) -> bool:
    if not model_name:
        return False
        
    targets = []
    if os.path.exists(TARGETS_FILE):
        try:
            with open(TARGETS_FILE, "r", encoding="utf-8") as f:
                targets = json.load(f)
        except:
            targets = []

    # Evita duplicatas
    for t in targets:
        if t["name"].lower() == model_name.lower() and t["status"] == "pending":
            return True

    targets.append({
        "name": model_name,
        "status": "pending",
        "added_at": datetime.now().isoformat()
    })

    with open(TARGETS_FILE, "w", encoding="utf-8") as f:
        json.dump(targets, f, indent=4)
    
    return True

def list_targets() -> list[str]:
    if not os.path.exists(TARGETS_FILE):
        return []
    try:
        with open(TARGETS_FILE, "r", encoding="utf-8") as f:
            targets = json.load(f)
            return [t["name"] for t in targets if t["status"] == "pending"]
    except:
        return []
