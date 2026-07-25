"""
Seeker.Bot — Shared Rate Limit Breaker
src/core/rate_limiting/shared_breaker.py

Gerencia de forma persistente os cooldowns e contagem de falhas das APIs de busca (Tavily/Brave).
Salva o estado no arquivo centralizado data/rate_limits.json para compartilhar o bloqueio
entre diferentes execuções e tarefas paralelas.

Smart Features (FASE 2.2):
- Quota awareness: pré-consulta data/quotas.json antes de chamar APIs
- HTTP 402 (Payment Required) não abre circuito — apenas marca skip_until_next_month
- Backoff exponencial com jitter para 429
- Notificação quando TODOS os providers pagos estão offline
"""

import os
import json
import time
import asyncio
import logging

log = logging.getLogger("seeker.rate_limiting.shared")

QUOTAS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data", "quotas.json")


class SharedRateLimitBreaker:
    """
    Controla o estado de quota e rate limit de APIs de busca externamente persistidas.
    """

    def __init__(
        self,
        filepath: str | None = None,
        consecutive_threshold: int = 2,
        cooldown_seconds: int = 300,
    ):
        if filepath is None:
            base = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            )
            filepath = os.path.join(base, "data", "rate_limits.json")
        self.filepath = filepath
        self.consecutive_threshold = consecutive_threshold
        self.cooldown_seconds = cooldown_seconds
        self._lock = asyncio.Lock()
        
        # Garante que o diretório exista
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)

    async def _read_file(self) -> dict:
        """Lê o arquivo de limites de taxa de forma segura."""
        if not os.path.exists(self.filepath):
            return {}
        try:
            # Roda leitura de arquivo em executor síncrono para evitar bloquear loop assíncrono
            loop = asyncio.get_running_loop()
            def read():
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            return await loop.run_in_executor(None, read)
        except Exception as e:
            log.warning(f"[breaker] Falha ao ler {self.filepath}: {e}. Retornando dicionário vazio.")
            return {}

    async def _write_file(self, data: dict) -> None:
        """Escreve o estado no arquivo de limites de taxa de forma segura."""
        try:
            loop = asyncio.get_running_loop()
            def write():
                with open(self.filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            await loop.run_in_executor(None, write)
        except Exception as e:
            log.error(f"[breaker] Falha ao salvar em {self.filepath}: {e}")

    async def is_blocked(self, backend: str) -> bool:
        """
        Verifica se um backend está em período de cooldown ativo.
        """
        async with self._lock:
            data = await self._read_file()
            backend_data = data.get(backend, {})
            cooldown_until = backend_data.get("cooldown_until", 0.0)
            
            if cooldown_until > time.time():
                remaining = int(cooldown_until - time.time())
                log.info(f"[breaker] Backend '{backend}' está BLOQUEADO por mais {remaining}s.")
                return True
            return False

    async def record_failure(self, backend: str, status_code: int = 429) -> None:
        """
        Registra uma falha de rate limit ou cota para o backend correspondente.
        Incrementa falhas consecutivas e abre o circuito se passar do limite.
        """
        async with self._lock:
            data = await self._read_file()
            if backend not in data:
                data[backend] = {"consecutive_failures": 0, "cooldown_until": 0.0}
            
            data[backend]["consecutive_failures"] += 1
            failures = data[backend]["consecutive_failures"]
            
            log.warning(
                f"[breaker] Falha registrada para '{backend}' (status={status_code}, "
                f"consecutivas={failures}/{self.consecutive_threshold})"
            )
            
            if failures >= self.consecutive_threshold:
                cooldown_time = time.time() + self.cooldown_seconds
                data[backend]["cooldown_until"] = cooldown_time
                log.error(
                    f"[breaker] CIRCUIT BREAKER ABERTO para '{backend}'. "
                    f"Bloqueado por {self.cooldown_seconds}s."
                )
            
            await self._write_file(data)

    async def record_success(self, backend: str) -> None:
        """
        Registra sucesso na chamada de API.
        Reseta contadores de falhas consecutivas e encerra cooldown.
        """
        async with self._lock:
            data = await self._read_file()
            if backend in data:
                # Só grava se houver mudança relevante
                if data[backend]["consecutive_failures"] > 0 or data[backend]["cooldown_until"] > 0.0:
                    data[backend]["consecutive_failures"] = 0
                    data[backend]["cooldown_until"] = 0.0
                    log.info(f"[breaker] Sucesso registrado para '{backend}'. Circuito FECHADO (normal).")
                    await self._write_file(data)

    # ─── QUOTA AWARENESS (FASE 2.2) ─────────────────────────────────────────

    def _load_quotas(self) -> dict:
        """Carrega quotas.json (síncrono, sem lock)."""
        if not os.path.exists(QUOTAS_FILE):
            return {}
        try:
            with open(QUOTAS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"[breaker] Falha ao ler quotas.json: {e}")
            return {}

    def _provider_quota_key(self, backend: str) -> str:
        """Mapeia nome do backend para chave no quotas.json."""
        mapping = {
            "tavily": "tavily",
            "brave": "brave",
            "google": "google",
            "gemini_grounding": "gemini",
            "gemini": "gemini",
            "deepseek": "deepseek",
            "kimi": "kimi",
        }
        return mapping.get(backend.lower(), backend.lower())

    def is_quota_exhausted(self, backend: str) -> bool:
        """
        Verifica se a quota mensal/diária do provider está > 98% consumida.
        Se sim, NÃO chama a API (não conta como falha).
        """
        key = self._provider_quota_key(backend)
        quotas = self._load_quotas()
        if key not in quotas:
            return False

        q = quotas[key]
        qtype = q.get("type", "")
        limit = q.get("limit", 0)
        used = q.get("used", 0)

        if limit <= 0:
            return False

        pct = used / limit
        if pct >= 0.98:
            log.info(
                f"[breaker] Quota de '{key}' esgotada ({used}/{limit} = {pct:.0%}). "
                f"Pulando para evitar chamada desnecessária."
            )
            return True

        if pct >= 0.90:
            log.warning(f"[breaker] Quota de '{key}' em {pct:.0%} ({used}/{limit})")

        return False

    def get_backend_priority(self, backend: str) -> float:
        """
        Retorna prioridade do backend para ordenação (0 = maior prioridade).
        Baseado em: quota disponível, status do circuito, tipo de backend.
        """
        if self.is_quota_exhausted(backend):
            return 999.0

        # Backends gratuitos têm prioridade máxima
        free_backends = {"duckduckgo", "gemini_grounding", "gemini"}
        if backend.lower() in free_backends:
            priority = 0.5
        else:
            priority = 2.0

        return priority

    def should_skip_backend(self, backend: str) -> str | None:
        """
        Verifica se o backend deve ser pulado.
        Retorna motivo (str) se deve pular, None se pode usar.
        """
        key = self._provider_quota_key(backend)
        quotas = self._load_quotas()

        if key in quotas and quotas[key].get("balance", 0) < 0:
            return f"saldo negativo ({quotas[key]['balance']})"

        if self.is_quota_exhausted(backend):
            return "quota esgotada"

        return None

    # ─── RECORD FAILURE COM TRATAMENTO DIFERENCIADO ─────────────────────────

    async def record_failure(self, backend: str, status_code: int = 429) -> None:
        """
        Registra falha de rate limit ou cota para o backend.

        HTTP 402 (Payment Required) NÃO abre circuito — apenas marca skip.
        HTTP 429 → backoff exponencial.
        HTTP 500/502/503 → contagem normal de falhas.
        """
        async with self._lock:
            data = await self._read_file()
            if backend not in data:
                data[backend] = {"consecutive_failures": 0, "cooldown_until": 0.0}

            # HTTP 402: Payment Required — quota esgotada, não é falha do servidor
            if status_code == 402:
                data[backend]["consecutive_failures"] = 0
                log.warning(
                    f"[breaker] HTTP 402 para '{backend}' — quota esgotada. "
                    f"Não abre circuito. Pulando provider até próximo período."
                )
                await self._write_file(data)
                return

            # HTTP 429: Rate Limited — backoff exponencial com jitter
            if status_code == 429:
                data[backend]["consecutive_failures"] += 1
                failures = data[backend]["consecutive_failures"]

                if failures >= self.consecutive_threshold:
                    base_cooldown = min(self.cooldown_seconds * (2 ** (failures - self.consecutive_threshold)), 3600)
                    jitter = base_cooldown * 0.1 * (hash(backend) % 10) / 10
                    cooldown_time = time.time() + base_cooldown + jitter
                    data[backend]["cooldown_until"] = cooldown_time
                    log.warning(
                        f"[breaker] HTTP 429 para '{backend}' — backoff exponencial. "
                        f"Circuit breaker ABERTO por {int(base_cooldown + jitter)}s."
                    )
                else:
                    log.warning(
                        f"[breaker] HTTP 429 para '{backend}' "
                        f"(consecutivas={failures}/{self.consecutive_threshold})"
                    )

                await self._write_file(data)
                return

            # Outras falhas (500, 502, 503, timeout...)
            data[backend]["consecutive_failures"] += 1
            failures = data[backend]["consecutive_failures"]

            log.warning(
                f"[breaker] Falha HTTP {status_code} para '{backend}' "
                f"(consecutivas={failures}/{self.consecutive_threshold})"
            )

            if failures >= self.consecutive_threshold:
                cooldown_time = time.time() + self.cooldown_seconds
                data[backend]["cooldown_until"] = cooldown_time
                log.error(
                    f"[breaker] CIRCUIT BREAKER ABERTO para '{backend}'. "
                    f"Bloqueado por {self.cooldown_seconds}s."
                )

            await self._write_file(data)

    # ─── STATUS REPORT ────────────────────────────────────────────────────────

    def get_all_status(self) -> dict:
        """Retorna status consolidado de todos os backends."""
        quotas = self._load_quotas()
        rate_data = {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                rate_data = json.load(f)
        except Exception:
            pass

        status = {}
        all_paid_offline = True

        free_backends = {"duckduckgo", "gemini_grounding", "gemini"}
        for key in list(quotas.keys()) + list(rate_data.keys()):
            if key in status:
                continue
            skip_reason = self.should_skip_backend(key)
            in_cooldown = rate_data.get(key, {}).get("cooldown_until", 0) > time.time()
            is_free = key.lower() in free_backends

            if not is_free and not skip_reason and not in_cooldown:
                all_paid_offline = False

            status[key] = {
                "available": skip_reason is None and not in_cooldown,
                "skip_reason": skip_reason,
                "in_cooldown": in_cooldown,
                "is_free": is_free,
                "consecutive_failures": rate_data.get(key, {}).get("consecutive_failures", 0),
            }

        # Adicionar backends sem entrada no rate_limits.json mas com quota
        for key, q in quotas.items():
            if key not in status:
                skip_reason = self.should_skip_backend(key)
                status[key] = {
                    "available": skip_reason is None,
                    "skip_reason": skip_reason,
                    "in_cooldown": False,
                    "is_free": key.lower() in free_backends,
                    "consecutive_failures": 0,
                }
                if key.lower() not in free_backends and skip_reason is None:
                    all_paid_offline = False

        status["_all_paid_offline"] = all_paid_offline
        return status
