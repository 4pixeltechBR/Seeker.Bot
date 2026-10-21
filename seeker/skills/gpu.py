"""VRAM por programa. No Windows o nvidia-smi não separa isso; o contador do sistema separa."""

from __future__ import annotations

import re
import subprocess

from seeker.skills.contract import Skill

CREATE_NO_WINDOW = 0x08000000
COUNTER = (
    "(Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage').CounterSamples | "
    "ForEach-Object { '{0}={1}' -f $_.InstanceName, [int64]$_.CookedValue }"
)
_SAMPLE = re.compile(r"pid_(\d+)_luid_0x[0-9a-fA-F]+_0x([0-9a-fA-F]+)_phys_\d+=(\d+)")


def parse_summary(text: str) -> tuple[int, int, int] | None:
    line = next((item.strip() for item in (text or "").splitlines() if item.strip()), "")
    parts = [item.strip() for item in line.split(",")]
    if len(parts) < 3:
        return None
    try:
        return int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
    except ValueError:
        return None


def parse_samples(text: str) -> dict[str, dict[int, int]]:
    found: dict[str, dict[int, int]] = {}
    for line in (text or "").splitlines():
        match = _SAMPLE.search(line.strip())
        if not match:
            continue
        pid = int(match.group(1))
        luid = match.group(2).lower()
        used = int(match.group(3))
        bucket = found.setdefault(luid, {})
        bucket[pid] = bucket.get(pid, 0) + used
    return found


def busiest(samples: dict[str, dict[int, int]]) -> dict[int, int]:
    if not samples:
        return {}
    return max(samples.values(), key=lambda item: sum(item.values()))


def format_gpu(summary: tuple[int, int, int] | None, pid_bytes: dict[int, int], names: dict[int, str]) -> str:
    lines: list[str] = []
    if summary is None:
        lines.append("Não li o total da placa pelo nvidia-smi.")
    else:
        used, total, util = summary
        lines.append(f"A placa está usando {used} MiB de {total} MiB, com {util}% de uso.")
    grouped: dict[str, dict[str, int]] = {}
    for pid, amount in pid_bytes.items():
        if amount < 1024 * 1024:
            continue
        name = names.get(pid) or f"pid {pid}"
        if name.lower().endswith(".exe"):
            name = name[:-4]
        row = grouped.setdefault(name, {"bytes": 0, "count": 0})
        row["bytes"] += amount
        row["count"] += 1
    ranked = sorted(grouped.items(), key=lambda item: item[1]["bytes"], reverse=True)[:10]
    if not ranked:
        lines.append("O contador do Windows não devolveu a memória de cada programa.")
        return "\n".join(lines)
    lines.append("")
    lines.append("O nvidia-smi não separa isso no Windows: volta N/A. A lista é a memória dedicada da GPU pelo Windows.")
    for name, row in ranked:
        amount = _mib(row["bytes"])
        if name == "dwm":
            lines.append(f"- dwm: {amount}. É o compositor da tela, então aparece maior do que a fatia exclusiva.")
            continue
        if row["count"] > 1:
            lines.append(f"- {name}, {row['count']} processos: {amount}")
        else:
            lines.append(f"- {name}: {amount}")
    lines.append("")
    lines.append("A soma não fecha com o total do nvidia-smi. O Windows e o driver medem de jeitos diferentes.")
    return "\n".join(lines)


def gpu_skill(run=None, names=None) -> Skill:
    runner = run or _run
    lookup = names or _process_name

    def execute(arguments: dict) -> str:
        del arguments
        summary_text = runner(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"]
        )
        counter_text = runner(["powershell", "-NoProfile", "-Command", COUNTER])
        pid_bytes = busiest(parse_samples(counter_text))
        found = {pid: lookup(pid) for pid in pid_bytes}
        return format_gpu(parse_summary(summary_text), pid_bytes, found)

    return Skill(
        name="gpu_memory",
        when=(
            "Mostra a VRAM usada e quanto cada programa ocupa na GPU. "
            "Use quando perguntarem de memória de vídeo, VRAM ou o que está pesado na placa."
        ),
        risk="leitura",
        needs_approval=False,
        parameters={"type": "object", "properties": {}},
        run=execute,
    )


def _mib(amount: int) -> str:
    value = amount / 1024 / 1024
    if value >= 100:
        return f"{round(value)} MiB"
    return f"{value:.1f} MiB"


def _run(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    return completed.stdout or completed.stderr


def _process_name(pid: int) -> str:
    try:
        import psutil

        return psutil.Process(pid).name()
    except Exception:
        return f"pid {pid}"
