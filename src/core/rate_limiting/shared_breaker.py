"""
Seeker.Bot — Shared Rate Limit Breaker
src/core/rate_limiting/shared_breaker.py

Gerencia de forma persistente os cooldowns e contagem de falhas das APIs de busca (Tavily/Brave).
Salva o estado no arquivo centralizado data/rate_limits.json para compartilhar o bloqueio
entre diferentes execuções e tarefas paralelas.
"""

import os
import json
import time
import asyncio
import logging

log = logging.getLogger("seeker.rate_limiting.shared")


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
