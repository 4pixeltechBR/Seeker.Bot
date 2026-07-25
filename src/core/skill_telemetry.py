"""
skill_telemetry — coleta métricas de uso das skills.

Resolve: hoje você não sabe quais skills estão sendo usadas, com que
frequência, com quanto custo e se dão sucesso. Sem isso, S.A.R.A.
(self-improvement) não tem dados para podar skills zumbis nem
promover skills que o usuário realmente usa.

Schema de cada evento (1 linha JSON em data/skill_telemetry.jsonl):
    {
        "ts": 1782676163.456,
        "skill": "custom_extension",
        "goal": "custom_extension",
        "success": true,
        "cost_usd": 0.0042,
        "latency_ms": 1234,
        "items_processed": 5,
        "error": null
    }

API:
    from src.core.skill_telemetry import record_skill_invocation, get_skill_stats

    record_skill_invocation("custom_extension", success=True, cost_usd=0.004, latency_ms=1234)
    stats = get_skill_stats("custom_extension", days=30)
    # -> {"calls": 142, "success_rate": 0.85, "total_cost_usd": 1.42, "avg_latency_ms": 2300}
"""

import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from threading import Lock
from typing import Any

log = logging.getLogger("seeker.skill_telemetry")

_TELEMETRY_FILE = Path("data/skill_telemetry.jsonl")
_TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
_file_lock = Lock()


def record_skill_invocation(
    skill: str,
    success: bool,
    cost_usd: float = 0.0,
    latency_ms: int = 0,
    items_processed: int = 0,
    error: str | None = None,
    goal: str | None = None,
) -> None:
    """Registra uma invocação de skill. Thread-safe, fire-and-forget.

    Args:
        skill: nome da skill (ex: "custom_extension", "knowledge_vault").
        success: True se completou sem exception.
        cost_usd: custo da execução em USD.
        latency_ms: latência total em milissegundos.
        items_processed: quantidade de items processados (ex: 5 leads minerados).
        error: mensagem de erro se success=False, None caso contrário.
        goal: nome do goal (se diferente da skill; ex: skill="scout" mas goal="custom_extension").
    """
    event = {
        "ts": time.time(),
        "skill": skill,
        "goal": goal or skill,
        "success": success,
        "cost_usd": cost_usd,
        "latency_ms": latency_ms,
        "items_processed": items_processed,
        "error": (error[:500] if error else None),
    }
    try:
        with _file_lock:
            with _TELEMETRY_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        # Telemetria NUNCA pode quebrar a skill.
        log.debug(f"[skill_telemetry] Falha ao registrar evento: {e}")


def get_skill_stats(skill: str, days: int = 30) -> dict[str, Any]:
    """Retorna stats agregados de uma skill nos últimos N dias.

    Returns:
        Dict com: calls, success_rate, total_cost_usd, avg_latency_ms,
        last_used_ts, zombie (True se success_rate < 50% e calls >= 10).
    """
    cutoff = time.time() - (days * 86400)
    calls = 0
    successes = 0
    total_cost = 0.0
    total_latency = 0
    last_used_ts = 0.0

    if not _TELEMETRY_FILE.exists():
        return _empty_stats(skill)

    try:
        with _TELEMETRY_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("skill") != skill:
                    continue
                if event.get("ts", 0) < cutoff:
                    continue
                calls += 1
                if event.get("success"):
                    successes += 1
                total_cost += event.get("cost_usd", 0.0)
                total_latency += event.get("latency_ms", 0)
                last_used_ts = max(last_used_ts, event.get("ts", 0))
    except Exception as e:
        log.debug(f"[skill_telemetry] Falha ao ler stats: {e}")
        return _empty_stats(skill)

    success_rate = (successes / calls) if calls > 0 else 0.0
    avg_latency = (total_latency / calls) if calls > 0 else 0
    zombie = (calls >= 10) and (success_rate < 0.5)

    return {
        "skill": skill,
        "days": days,
        "calls": calls,
        "successes": successes,
        "success_rate": success_rate,
        "total_cost_usd": round(total_cost, 6),
        "avg_latency_ms": int(avg_latency),
        "last_used_ts": last_used_ts,
        "zombie": zombie,
    }


def get_all_skills_stats(days: int = 30) -> list[dict[str, Any]]:
    """Retorna stats de todas as skills, ordenadas por calls desc."""
    cutoff = time.time() - (days * 86400)
    skills: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "successes": 0,
            "total_cost": 0.0,
            "total_latency": 0,
            "last_used_ts": 0.0,
        }
    )

    if not _TELEMETRY_FILE.exists():
        return []

    try:
        with _TELEMETRY_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("ts", 0) < cutoff:
                    continue
                skill = event.get("skill")
                if not skill:
                    continue
                s = skills[skill]
                s["calls"] += 1
                if event.get("success"):
                    s["successes"] += 1
                s["total_cost"] += event.get("cost_usd", 0.0)
                s["total_latency"] += event.get("latency_ms", 0)
                s["last_used_ts"] = max(s["last_used_ts"], event.get("ts", 0))
    except Exception as e:
        log.debug(f"[skill_telemetry] Falha ao agregar stats: {e}")
        return []

    result = []
    for name, s in skills.items():
        calls = s["calls"]
        result.append({
            "skill": name,
            "calls": calls,
            "success_rate": (s["successes"] / calls) if calls > 0 else 0.0,
            "total_cost_usd": round(s["total_cost"], 6),
            "avg_latency_ms": int(s["total_latency"] / calls) if calls > 0 else 0,
            "last_used_ts": s["last_used_ts"],
            "zombie": (calls >= 10) and ((s["successes"] / calls) < 0.5),
        })
    result.sort(key=lambda x: -x["calls"])
    return result


def _empty_stats(skill: str) -> dict[str, Any]:
    return {
        "skill": skill,
        "days": 0,
        "calls": 0,
        "successes": 0,
        "success_rate": 0.0,
        "total_cost_usd": 0.0,
        "avg_latency_ms": 0,
        "last_used_ts": 0.0,
        "zombie": False,
    }
