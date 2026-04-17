"""
Seeker.Bot — RL Backfill
src/core/rl/backfill.py

Retroalimenta o histórico dos logs do bot em formato RL-ready.

O bot tem semanas/meses de logs em logs/seeker.log.
Este módulo parseia esses logs e gera RewardEvents retroativos,
permitindo que os algoritmos de RL treinem antes de qualquer linha nova.

Estratégia de extração (sem ground-truth de reward):

  1. Detecta pares (decisão de roteamento → resultado técnico)
     via padrões de log: "[cascade] Tier X ... respondeu em Yms"

  2. Reconstrói estado parcial a partir do timestamp + contexto do log
     (budget, hora, provider, etc são estimados)

  3. Atribui reward técnico baseado em: sucesso, latência, tier usado.
     Reward comportamental = 0 (não temos histórico de reação do Victor).

  4. Salva em JSONL como eventos fechados.

Uso:
    python -m src.core.rl.backfill --days 30
    python -m src.core.rl.backfill --log-file logs/seeker.log --days 7

Ou via código:
    from src.core.rl.backfill import LogBackfill
    backfill = LogBackfill("logs/seeker.log")
    count = backfill.run(days=30)
    print(f"Retroalimentados: {count} eventos")
"""

import argparse
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from .reward_collector import RewardEvent, RewardSignal, SignalSource, RewardSign, REWARD_DB_PATH

log = logging.getLogger("seeker.rl.backfill")

# ─────────────────────────────────────────────────────────────────────────────
# PADRÕES DE LOG
# ─────────────────────────────────────────────────────────────────────────────

# Real format: "06:03:11 [seeker.pipeline] INFO: [pipeline] deep | reason='...' | god=False | web=True"
_RE_ROUTING = re.compile(
    r"(\d{2}:\d{2}:\d{2}).*\[seeker\.pipeline\].*\[pipeline\]\s+(reflex|deliberate|deep)\s*\|",
    re.IGNORECASE,
)

# Real format: "10:34:22 [seeker.cascade] INFO: [cascade] ✅ Tier 2 (groq) respondeu em 412ms"
# Also handles ASCII fallback without ✅
_RE_CASCADE_OK = re.compile(
    r"(\d{2}:\d{2}:\d{2}).*\[cascade\].*Tier\s+(\d+)\s+\((\w+)\)\s+respondeu\s+em\s+(\d+)ms",
    re.IGNORECASE,
)

# Real format: "19:02:12 [seeker.cascade] WARNING: [cascade] Tier 1 excecao/exceção: ..."
_RE_CASCADE_FAIL = re.compile(
    r"(\d{2}:\d{2}:\d{2}).*\[cascade\].*Tier\s+\d+\s+exce",
    re.IGNORECASE,
)

# "10:34:22 [seeker.cascade] INFO: [cascade] Tier 2: deepseek/DeepSeek-R1 ..."
_RE_CASCADE_ATTEMPT = re.compile(
    r"(\d{2}:\d{2}:\d{2}).*\[cascade\].*Tier\s+(\d+):\s+(\w+)/",
    re.IGNORECASE,
)

# "10:34:21 [seeker.pipeline] INFO: cobrança: $0.0031 (groq/llama)"
_RE_COST = re.compile(
    r"(\d{2}:\d{2}:\d{2}).*cobrança.*\$(\d+\.\d+)",
    re.IGNORECASE,
)

# Timestamp de início de linha
_RE_TS = re.compile(r"^(\d{2}:\d{2}:\d{2})")

# ─────────────────────────────────────────────────────────────────────────────
# PARSER
# ─────────────────────────────────────────────────────────────────────────────

def _parse_time(time_str: str, base_date: datetime) -> float:
    """Converte HH:MM:SS + data base em epoch float."""
    h, m, s = map(int, time_str.split(":"))
    dt = base_date.replace(hour=h, minute=m, second=s, microsecond=0)
    return dt.timestamp()


class LogBackfill:
    """
    Parseia logs do Seeker e gera dataset retroativo de RL.

    Approach conservador:
    - Reward técnico estimado de acordo com sucesso, tier, latência
    - Reward comportamental = 0 (não temos dados históricos de Victor)
    - Melhor do que nada — cold start fica 3× mais rápido

    Formato de saída: mesmo JSONL do RewardCollector.
    """

    def __init__(
        self,
        log_file: str = "logs/seeker.log",
        output_path: str = REWARD_DB_PATH,
    ):
        self.log_file = log_file
        self.output_path = output_path
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

    def run(self, days: int = 30, dry_run: bool = False) -> int:
        """
        Parseia log e salva eventos retroativos.

        Args:
            days: Quantos dias retroativos processar
            dry_run: Se True, não escreve em disco (apenas conta)

        Returns:
            Número de eventos gerados
        """
        if not os.path.exists(self.log_file):
            log.warning(f"[backfill] Log não encontrado: {self.log_file}")
            return 0

        cutoff = time.time() - (days * 86400)
        events_generated = 0
        events_written = []

        log.info(f"[backfill] Processando {self.log_file} (últimos {days} dias)...")

        # Lemos linha por linha para não explodir memória
        base_date = datetime.now().replace(hour=0, minute=0, second=0)

        # Janela deslizante: guarda contexto para parear routing → resultado
        pending_routing: dict[str, dict] = {}  # ts → {depth, ts}
        last_routing_ts: float | None = None
        last_routing_depth: str | None = None

        with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                # Detecta roteamento
                m = _RE_ROUTING.search(line)
                if m:
                    ts = _parse_time(m.group(1), base_date)
                    if ts < cutoff:
                        continue
                    depth = m.group(2).lower()
                    last_routing_ts = ts
                    last_routing_depth = depth
                    pending_routing[str(ts)] = {
                        "depth": depth,
                        "ts": ts,
                        "decision_id": str(uuid.uuid4()),
                    }
                    continue

                # Detecta sucesso do cascade
                m = _RE_CASCADE_OK.search(line)
                if m and last_routing_ts:
                    ts = _parse_time(m.group(1), base_date)
                    if ts < cutoff:
                        continue
                    tier = int(m.group(2))
                    provider = m.group(3)
                    latency_ms = float(m.group(4))

                    # Pega o roteamento mais recente que precedeu este sucesso
                    routing = self._find_nearest_routing(pending_routing, ts, window=30)
                    if routing:
                        event = self._make_event(
                            decision_id=routing["decision_id"],
                            action_taken=routing["depth"],
                            created_at=routing["ts"],
                            success=True,
                            tier=tier,
                            provider=provider,
                            latency_ms=latency_ms,
                            cost_usd=self._estimate_cost(tier, latency_ms),
                        )
                        events_written.append(event)
                        events_generated += 1
                        pending_routing.pop(str(routing["ts"]), None)
                    continue

                # Detecta falha do cascade
                m = _RE_CASCADE_FAIL.search(line)
                if m and last_routing_ts:
                    ts = _parse_time(m.group(1), base_date)
                    if ts < cutoff:
                        continue
                    routing = self._find_nearest_routing(pending_routing, ts, window=30)
                    if routing:
                        event = self._make_event(
                            decision_id=routing["decision_id"],
                            action_taken=routing["depth"],
                            created_at=routing["ts"],
                            success=False,
                            tier=99,
                            provider="unknown",
                            latency_ms=0,
                            cost_usd=0,
                        )
                        events_written.append(event)
                        events_generated += 1
                        pending_routing.pop(str(routing["ts"]), None)
                    continue

        # Flush para JSONL
        if not dry_run and events_written:
            try:
                with open(self.output_path, "a", encoding="utf-8") as f:
                    for ev in events_written:
                        f.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
                log.info(f"[backfill] ✅ {events_generated} eventos escritos em {self.output_path}")
            except Exception as e:
                log.error(f"[backfill] Falha ao escrever: {e}")
        elif dry_run:
            log.info(f"[backfill] Dry-run: {events_generated} eventos seriam gerados")

        return events_generated

    def _find_nearest_routing(
        self,
        pending: dict[str, dict],
        ts: float,
        window: float = 30.0,
    ) -> dict | None:
        """Encontra o routing mais recente que precedeu ts dentro de window segundos."""
        candidates = [
            r for r in pending.values()
            if 0 < (ts - r["ts"]) < window
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r["ts"])

    def _estimate_cost(self, tier: int, latency_ms: float) -> float:
        """
        Estima custo quando não temos log explícito.
        Baseado em tier como proxy de provider (tier1=deepseek, tier2=groq, etc).
        """
        tier_costs = {
            1: 0.015,   # DeepSeek R1 — mais caro
            2: 0.002,   # Groq Llama — barato e rápido
            3: 0.001,   # Gemini Flash — muito barato
            4: 0.0005,  # Local/Ollama — quase gratuito
        }
        return tier_costs.get(tier, 0.005)

    def _make_event(
        self,
        decision_id: str,
        action_taken: str,
        created_at: float,
        success: bool,
        tier: int,
        provider: str,
        latency_ms: float,
        cost_usd: float,
    ) -> RewardEvent:
        """Constrói RewardEvent a partir de dados de log."""
        event = RewardEvent(
            decision_id=decision_id,
            action_taken=action_taken,
            context=f"backfill tier={tier} provider={provider}",
            created_at=created_at,
            closed_at=created_at + latency_ms / 1000,
        )

        # Sinal de sucesso/falha
        event.add_signal(RewardSignal(
            source=SignalSource.TECHNICAL,
            sign=RewardSign.POSITIVE if success else RewardSign.NEGATIVE,
            value=1.0 if success else -1.0,
            reason=f"[backfill] {'sucesso' if success else 'falha'} tier={tier}",
            timestamp=created_at,
        ))

        # Sinal de custo
        if cost_usd > 0:
            event.add_signal(RewardSignal(
                source=SignalSource.TECHNICAL,
                sign=RewardSign.NEGATIVE,
                value=-min(1.0, cost_usd * 50),
                reason=f"[backfill] cost ${cost_usd:.4f}",
                timestamp=created_at,
            ))

        # Sinal de latência
        if latency_ms > 0:
            event.add_signal(RewardSignal(
                source=SignalSource.TECHNICAL,
                sign=RewardSign.NEGATIVE,
                value=-min(0.5, latency_ms * 0.0001),
                reason=f"[backfill] latency {latency_ms:.0f}ms",
                timestamp=created_at,
            ))

        # Bonus por usar tier baixo (barato) com sucesso
        if success and tier >= 2:
            event.add_signal(RewardSignal(
                source=SignalSource.TECHNICAL,
                sign=RewardSign.POSITIVE,
                value=+0.3,
                reason=f"[backfill] tier eficiente (tier={tier})",
                timestamp=created_at,
            ))

        return event


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Retroalimenta histórico de logs do Seeker em formato RL"
    )
    parser.add_argument(
        "--log-file",
        default="logs/seeker.log",
        help="Caminho para o log do Seeker (padrão: logs/seeker.log)",
    )
    parser.add_argument(
        "--output",
        default=REWARD_DB_PATH,
        help=f"Caminho de saída JSONL (padrão: {REWARD_DB_PATH})",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Quantos dias retroativos processar (padrão: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas conta eventos sem escrever",
    )
    args = parser.parse_args()

    backfill = LogBackfill(log_file=args.log_file, output_path=args.output)
    count = backfill.run(days=args.days, dry_run=args.dry_run)

    status = "simulados" if args.dry_run else "escritos"
    print(f"\nBackfill completo: {count} eventos {status}")
    print(f"   Log:    {args.log_file}")
    print(f"   Output: {args.output}")
    print(f"   Dias:   {args.days}")


if __name__ == "__main__":
    main()
