"""
viralx9.bridge — Cria projetos vazios no ViralClip (Modo Manual) a partir de
candidatos aprovados, via subprocess no mesmo CLI usado pelo frontend
(frontend/app/api/generate/manual-steps/route.ts).

Reutiliza a ação `init` de viral_ai_step_generator.py com os novos args
--source / --seeker-meta (sem duplicar lógica).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

log = logging.getLogger("seeker.viralx9.bridge")


def _viral_root() -> Path:
    root = os.getenv("VIRALCLIP_ROOT") or os.getenv("VIRAL_ROOT") or r"E:\ViralClip"
    return Path(root)


def create_project(candidato: dict) -> dict:
    """
    Roda `viral_ai_step_generator.py init --source seeker --seeker-meta {...}`
    e retorna o JSON emitido pelo script (success/projectId/projectDir/...).
    Síncrono — chamar via asyncio.to_thread no goal.
    """
    viral_root = _viral_root()
    script = viral_root / "backend" / "core" / "services" / "viral_ai_step_generator.py"
    python_exe = viral_root / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        python_exe = Path("python")  # fallback p/ ambientes sem venv local

    seeker_meta = {
        "justificativa": candidato.get("justificativa", ""),
        "tema_original": candidato.get("tema_original", ""),
        "idioma_original": candidato.get("idioma_original", ""),
        "video_url": candidato.get("video_url", ""),
        "canal": candidato.get("canal", ""),
        "regiao": candidato.get("regiao", ""),
        "outlier": candidato.get("outlier", 0),
        "velocity": candidato.get("velocity", 0),
    }

    args = [
        str(python_exe),
        str(script),
        "init",
        "--nicho", candidato["nicho"],
        "--tema", candidato["tema"],
        "--source", "seeker",
        "--seeker-meta", json.dumps(seeker_meta, ensure_ascii=False),
    ]

    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(viral_root),
        "PYTHONIOENCODING": "utf-8",
        "VIRAL_OUTPUT_DIR": str(viral_root / "data" / "output"),
    }

    import subprocess

    try:
        proc = subprocess.run(
            args,
            cwd=str(viral_root / "backend" / "core" / "services"),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    except Exception as e:
        log.error(f"[viralx9] Falha ao executar bridge: {e}")
        return {"success": False, "error": str(e)}

    if proc.returncode != 0:
        log.error(f"[viralx9] bridge retornou código {proc.returncode}: {proc.stderr[-500:]}")

    last_line = ""
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line:
            last_line = line

    if not last_line:
        return {"success": False, "error": f"Sem saída do script. stderr: {proc.stderr[-500:]}"}

    try:
        return json.loads(last_line)
    except Exception as e:
        return {"success": False, "error": f"Saída inválida ({e}): {last_line[:200]}"}


async def create_project_async(candidato: dict) -> dict:
    return await asyncio.to_thread(create_project, candidato)
