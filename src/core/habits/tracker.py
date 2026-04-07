"""
Seeker.Bot — Habit Tracker
src/core/habits/tracker.py

Aprende padrões de decisão do usuário baseado no histórico de
aprovações/rejeições no AFK Protocol.

Sem ML — contagem pura por (goal, action_type, weekday, hour_block).
Depois de N datapoints, infere se o usuário tende a aprovar ou rejeitar
naquele slot de tempo.

Exemplo aprendido após 2 semanas:
    - Segunda 09h, read: 8/8 aprovações → auto-approve
    - Sexta 15h, write: 1/5 aprovações → nem perguntar, enfileirar
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime

log = logging.getLogger("seeker.habits")

HABITS_PATH = os.path.join(os.getcwd(), "data", "habits.json")
MIN_SAMPLES = 5
APPROVE_THRESHOLD = 0.8
DENY_THRESHOLD = 0.2


class HabitTracker:
    """
    Registra decisões e infere padrões por slot de tempo.

    Uso:
        tracker = HabitTracker()
        tracker.record("revenue_hunter", "read", approved=True)
        suggestion = tracker.suggest("revenue_hunter", "read")
        # {"action": "auto_approve", "confidence": 0.9, "samples": 12}
    """

    def __init__(self):
        self._data: dict[str, dict[str, int]] = defaultdict(
            lambda: {"approved": 0, "denied": 0}
        )
        self._load()

    def record(self, goal_name: str, action_type: str, approved: bool):
        slot = self._make_slot(goal_name, action_type)
        if approved:
            self._data[slot]["approved"] += 1
        else:
            self._data[slot]["denied"] += 1

        total = self._data[slot]["approved"] + self._data[slot]["denied"]
        log.info(
            f"[habits] {slot} → {'✅' if approved else '❌'} "
            f"({self._data[slot]['approved']}/{total})"
        )
        self._save()

    def suggest(self, goal_name: str, action_type: str) -> dict:
        slot = self._make_slot(goal_name, action_type)
        counts = self._data.get(slot)

        if not counts:
            return self._result("insufficient_data", 0.0, 0, 0.0)

        total = counts["approved"] + counts["denied"]
        if total < MIN_SAMPLES:
            rate = counts["approved"] / total if total > 0 else 0
            return self._result("insufficient_data", 0.0, total, rate)

        rate = counts["approved"] / total

        if rate >= APPROVE_THRESHOLD:
            return self._result("auto_approve", rate, total, rate)
        elif rate <= DENY_THRESHOLD:
            return self._result("auto_deny", 1 - rate, total, rate)
        else:
            return self._result("ask", 0.5, total, rate)

    def get_report(self) -> str:
        if not self._data:
            return "<b>🧠 Habits</b>\nSem dados — preciso de mais interações."

        lines = ["<b>🧠 Habits</b>\n"]
        for slot, counts in sorted(self._data.items()):
            total = counts["approved"] + counts["denied"]
            if total == 0:
                continue
            rate = counts["approved"] / total
            parts = slot.split("|")
            goal = parts[0] if len(parts) > 0 else "?"
            action = parts[1] if len(parts) > 1 else "?"
            day = parts[2] if len(parts) > 2 else "?"
            hour = parts[3] if len(parts) > 3 else "?"

            if rate >= APPROVE_THRESHOLD and total >= MIN_SAMPLES:
                emoji = "🟢"
            elif rate <= DENY_THRESHOLD and total >= MIN_SAMPLES:
                emoji = "🔴"
            else:
                emoji = "🟡"

            lines.append(
                f"  {emoji} {goal}/{action} {day} {hour}h → "
                f"{rate:.0%} ({total}x)"
            )
        return "\n".join(lines)

    def _make_slot(self, goal_name: str, action_type: str) -> str:
        now = datetime.now()
        dias = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
        weekday = dias[now.weekday()]
        hour_block = f"{(now.hour // 3) * 3:02d}-{(now.hour // 3) * 3 + 2:02d}"
        return f"{goal_name}|{action_type}|{weekday}|{hour_block}"

    def _result(self, action, confidence, samples, rate):
        return {
            "action": action,
            "confidence": confidence,
            "samples": samples,
            "approve_rate": rate,
        }

    def _save(self):
        try:
            os.makedirs(os.path.dirname(HABITS_PATH), exist_ok=True)
            with open(HABITS_PATH, "w", encoding="utf-8") as f:
                json.dump(dict(self._data), f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"[habits] Falha ao salvar: {e}")

    def _load(self):
        if not os.path.exists(HABITS_PATH):
            return
        try:
            with open(HABITS_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self._data = defaultdict(lambda: {"approved": 0, "denied": 0}, raw)
            total = sum(v["approved"] + v["denied"] for v in self._data.values())
            log.info(f"[habits] Carregado: {len(self._data)} slots, {total} amostras")
        except Exception as e:
            log.warning(f"[habits] Falha ao carregar: {e}")
