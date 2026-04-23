import psutil
import logging
import urllib.request
import urllib.error
import subprocess
import os
import time

from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel
)
from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.health")

class SystemHealthMonitor:
    """
    Monitora a saúde do sistema hospedeiro (CPU, RAM, Disco)
    e garante que dependências críticas (como o Ollama local) estejam no ar.
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.0, max_daily_usd=0.0)
        self._last_ollama_restart = 0

    @property
    def name(self) -> str:
        return "health_monitor"

    @property
    def interval_seconds(self) -> int:
        return 1800  # A cada 30 minutos

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        # Queremos enviar alertas via Telegram se algo crítico acontecer
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    async def run_cycle(self) -> GoalResult:
        self._status = GoalStatus.RUNNING
        
        alerts = []
        
        # 1. Checagem de Recursos Físicos
        cpu_usage = psutil.cpu_percent(interval=1.0)
        if cpu_usage > 95.0:
            alerts.append(f"🔥 CPU em nível crítico: {cpu_usage}%")
            
        ram = psutil.virtual_memory()
        if ram.percent > 95.0:
            alerts.append(f"🧠 RAM quase esgotada: {ram.percent}% (Livre: {ram.available / (1024**3):.1f} GB)")

        # Checa disco primário e drives estendidos
        for disk in ['C:\\', 'D:\\', 'E:\\', 'H:\\']:
            try:
                usage = psutil.disk_usage(disk)
                free_gb = usage.free / (1024**3)
                
                # C: tem threshold menor (4GB), outros drivers maior (15GB)
                threshold = 4.0 if disk.upper().startswith('C') else 15.0
                
                if free_gb < threshold:
                    alerts.append(f"💾 Disco {disk} com pouco espaço: {free_gb:.1f} GB livres")
            except Exception:
                pass  # Ignora se o drive não existir

        # 2. Checagem do Ollama
        ollama_ok = False
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/", method="GET")
            with urllib.request.urlopen(req, timeout=3) as response:
                if response.status == 200:
                    ollama_ok = True
        except Exception:
            ollama_ok = False

        if not ollama_ok:
            # Auto-cura: Tenta reiniciar o Ollama (máximo 1x a cada 4 horas)
            now = time.time()
            if (now - self._last_ollama_restart) > (4 * 3600):
                log.warning("[health] Ollama local offline. Tentando auto-cura...")
                try:
                    subprocess.Popen(
                        "ollama serve",
                        shell=True,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                    )
                    self._last_ollama_restart = now
                    alerts.append("🔴 Ollama caiu. Disparei o processo de auto-cura (ollama serve).")
                except Exception as e:
                    alerts.append(f"🔴 Ollama caiu e falha na auto-cura: {e}")
            else:
                alerts.append("🔴 Ollama está offline (auto-cura em cooldown).")

        self._status = GoalStatus.IDLE

        if alerts:
            alert_text = "<b>🚨 ALERTA DE SAÚDE DO SISTEMA</b>\n\n" + "\n".join([f"• {a}" for a in alerts])
            return GoalResult(
                success=True,
                summary=f"Disparou {len(alerts)} alertas do sistema.",
                notification=alert_text,
                cost_usd=0.0
            )

        return GoalResult(
            success=True,
            summary="Sistema operando nominalmente (CPU/RAM/Disco/Ollama OK).",
            cost_usd=0.0
        )

    def serialize_state(self) -> dict:
        return {"last_ollama_restart": self._last_ollama_restart}

    def load_state(self, state: dict) -> None:
        self._last_ollama_restart = state.get("last_ollama_restart", 0)


def create_goal(pipeline) -> SystemHealthMonitor:
    return SystemHealthMonitor(pipeline)
