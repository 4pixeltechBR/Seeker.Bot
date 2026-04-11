"""
Monitor Crew - Always-on sensing of system health
Latency: <500ms, Cost: $0.0 (no LLM calls)
Confidence: 0.95 healthy, 0.4-0.7 degraded

Monitors:
  1. CPU usage (alert >90%)
  2. RAM usage (alert >90%)
  3. Disk space (C: alert <4GB, others <15GB)
  4. Ollama LLM service (health check + auto-heal)
  5. Email connectivity (placeholder)
"""

import psutil
import logging
import urllib.request
import urllib.error
import subprocess
import time
from typing import Optional

from ..interfaces import CrewRequest, CrewResult, CrewPriority
from . import BaseCrew

log = logging.getLogger("seeker.monitor_crew")


class MonitorCrew(BaseCrew):
    """System health monitoring crew - always operational"""

    def __init__(self):
        super().__init__("monitor", CrewPriority.HIGH)
        self._last_ollama_restart = 0
        self._status_history = []  # Track last 10 checks

    async def _execute_internal(self, request: CrewRequest) -> CrewResult:
        """
        Execute comprehensive health monitoring
        Returns structured status with alerts and overall confidence
        """
        import time as time_module
        start_time = time_module.time()

        alerts = []
        metrics = {}

        # ──────────────────────────────────────────────────────────
        # CHECK 1: CPU USAGE
        # ──────────────────────────────────────────────────────────
        try:
            cpu_usage = psutil.cpu_percent(interval=0.5)
            metrics["cpu_percent"] = cpu_usage

            if cpu_usage > 95.0:
                alerts.append(f"🔥 CPU em nível crítico: {cpu_usage}%")
            elif cpu_usage > 85.0:
                alerts.append(f"⚠️ CPU elevado: {cpu_usage}%")
            else:
                metrics["cpu_status"] = "ok"
        except Exception as e:
            log.warning(f"[monitor] CPU check failed: {e}")
            metrics["cpu_error"] = str(e)

        # ──────────────────────────────────────────────────────────
        # CHECK 2: RAM USAGE
        # ──────────────────────────────────────────────────────────
        try:
            ram = psutil.virtual_memory()
            metrics["ram_percent"] = ram.percent
            metrics["ram_available_gb"] = ram.available / (1024**3)

            if ram.percent > 95.0:
                alerts.append(f"🧠 RAM quase esgotada: {ram.percent}% (Livre: {ram.available / (1024**3):.1f} GB)")
            elif ram.percent > 85.0:
                alerts.append(f"⚠️ RAM elevado: {ram.percent}%")
            else:
                metrics["ram_status"] = "ok"
        except Exception as e:
            log.warning(f"[monitor] RAM check failed: {e}")
            metrics["ram_error"] = str(e)

        # ──────────────────────────────────────────────────────────
        # CHECK 3: DISK SPACE
        # ──────────────────────────────────────────────────────────
        disk_alerts = []
        disk_status = {}
        for disk in ['C:\\', 'D:\\', 'E:\\', 'H:\\']:
            try:
                usage = psutil.disk_usage(disk)
                free_gb = usage.free / (1024**3)

                # C: tem threshold menor (4GB), outros drivers maior (15GB)
                threshold = 4.0 if disk.upper().startswith('C') else 15.0

                disk_status[disk] = {
                    "free_gb": round(free_gb, 1),
                    "percent_used": usage.percent,
                    "threshold_gb": threshold,
                    "ok": free_gb > threshold
                }

                if free_gb < threshold:
                    disk_alerts.append(f"💾 Disco {disk} com pouco espaço: {free_gb:.1f} GB livres")
                else:
                    disk_status[disk]["status"] = "ok"
            except Exception:
                disk_status[disk] = {"error": "not found"}

        if disk_alerts:
            alerts.extend(disk_alerts)

        metrics["disks"] = disk_status

        # ──────────────────────────────────────────────────────────
        # CHECK 4: OLLAMA SERVICE
        # ──────────────────────────────────────────────────────────
        ollama_ok = False
        ollama_status = "offline"
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/", method="GET")
            with urllib.request.urlopen(req, timeout=3) as response:
                if response.status == 200:
                    ollama_ok = True
                    ollama_status = "online"
                    metrics["ollama_status"] = "operational"
        except Exception as e:
            ollama_status = f"offline ({type(e).__name__})"
            log.warning(f"[monitor] Ollama offline: {e}")

        if not ollama_ok:
            # Auto-heal: Tenta reiniciar o Ollama (máximo 1x a cada 4 horas)
            now = time_module.time()
            if (now - self._last_ollama_restart) > (4 * 3600):
                log.warning("[monitor] Ollama local offline. Tentando auto-cura...")
                try:
                    subprocess.Popen(
                        "ollama serve",
                        shell=True,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                    )
                    self._last_ollama_restart = now
                    alerts.append("🔴 Ollama caiu. Disparei o processo de auto-cura (ollama serve).")
                    metrics["ollama_restart_triggered"] = True
                except Exception as e:
                    alerts.append(f"🔴 Ollama caiu e falha na auto-cura: {e}")
                    log.error(f"[monitor] Ollama restart failed: {e}")
            else:
                alerts.append("🔴 Ollama está offline (auto-cura em cooldown de 4h).")
                metrics["ollama_cooldown"] = True

        metrics["ollama"] = ollama_status

        # ──────────────────────────────────────────────────────────
        # CHECK 5: EMAIL CONNECTIVITY (placeholder)
        # ──────────────────────────────────────────────────────────
        # TODO: Implement IMAP health check if email is configured
        metrics["email"] = "not_configured"

        # ──────────────────────────────────────────────────────────
        # AGGREGATE RESULTS
        # ──────────────────────────────────────────────────────────
        latency_ms = int((time_module.time() - start_time) * 1000)

        # Confidence scoring:
        # - All green: 0.95
        # - Minor warnings (CPU/RAM high): 0.80
        # - Offline service or disk critical: 0.50
        # - Multiple failures: 0.30
        confidence = 0.95
        if alerts:
            if any("Ollama" in a for a in alerts):
                confidence = min(confidence, 0.50)
            if any("Disco" in a for a in alerts):
                confidence = min(confidence, 0.60)
            if any("CPU" in a or "RAM" in a for a in alerts):
                confidence = min(confidence, 0.80)

        # Build response
        if not alerts:
            response_text = (
                "✅ Sistema operando nominalmente\n\n"
                f"CPU: {metrics.get('cpu_percent', 0):.0f}%\n"
                f"RAM: {metrics.get('ram_percent', 0):.0f}% ({metrics.get('ram_available_gb', 0):.1f} GB livre)\n"
                f"Discos: OK (C: {disk_status.get('C:', {}).get('free_gb', 0):.1f}GB, "
                f"E: {disk_status.get('E:', {}).get('free_gb', 0):.1f}GB)\n"
                f"Ollama: {ollama_status}"
            )
        else:
            alert_list = "\n".join([f"  • {a}" for a in alerts])
            response_text = (
                f"⚠️ Sistema com {len(alerts)} alerta(s):\n\n{alert_list}\n\n"
                f"Métricas:\n"
                f"  CPU: {metrics.get('cpu_percent', 0):.0f}%\n"
                f"  RAM: {metrics.get('ram_percent', 0):.0f}%\n"
                f"  Ollama: {ollama_status}"
            )

        # Store in history
        self._status_history.append({
            "timestamp": time_module.time(),
            "alerts": len(alerts),
            "confidence": confidence,
            "metrics": metrics
        })
        if len(self._status_history) > 10:
            self._status_history.pop(0)

        return CrewResult(
            response=response_text,
            crew_id=self.crew_id,
            cost_usd=0.0,  # No LLM calls
            llm_calls=0,
            confidence=confidence,
            latency_ms=latency_ms,
            sources=[],
            should_save_fact=False,
        )

    def get_status(self) -> dict:
        """Extended status with health metrics"""
        base_status = super().get_status()
        base_status.update({
            "recent_checks": len(self._status_history),
            "last_ollama_restart": self._last_ollama_restart,
            "history": self._status_history[-3:] if self._status_history else [],
        })
        return base_status


# Singleton instance
monitor = MonitorCrew()
