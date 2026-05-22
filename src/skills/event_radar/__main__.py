"""
CLI para consulta rápida do EventRadar.

Uso:
    python -m src.skills.event_radar                  # próximos 30 dias
    python -m src.skills.event_radar --mes 6          # junho
    python -m src.skills.event_radar --dias 60        # próximos 60 dias
    python -m src.skills.event_radar --demand         # sinais de demanda por cidade
    python -m src.skills.event_radar --stats          # distribuição mensal
"""

import argparse
import json

from src.skills.event_radar.query import EventQuery, _MONTH_NAMES


def cmd_upcoming(q: EventQuery, days: int):
    events = q.upcoming(days=days)
    if not events:
        print(f"Nenhum evento nos próximos {days} dias.")
        return
    print(f"\n=== Próximos {days} dias — {len(events)} eventos ===\n")
    for e in events:
        mes = _MONTH_NAMES[e["mes"]] if e.get("mes") else "?"
        print(f"  [{mes:>8}] {e.get('cidade','?'):25s} {e.get('nome','?')}")
        if e.get("data_estimada"):
            print(f"             {e['data_estimada']}")


def cmd_by_month(q: EventQuery, mes: int):
    events = q.by_month(mes)
    nome_mes = _MONTH_NAMES[mes]
    print(f"\n=== {nome_mes} — {len(events)} eventos ===\n")
    for e in events:
        print(f"  {e.get('cidade','?'):25s} {e.get('nome','?')}")
        if e.get("data_estimada"):
            print(f"  {'':25s} {e['data_estimada']}")
        print()


def cmd_demand(q: EventQuery, days: int):
    signals = q.demand_signals(days=days)
    if not signals:
        print("Sem sinais de demanda.")
        return
    print(f"\n=== Sinais de Demanda — próximos {days} dias (top 20) ===\n")
    print(f"  {'Cidade':25s} {'Eventos':>7}  Exemplos")
    print("  " + "-" * 70)
    for s in signals[:20]:
        mes = _MONTH_NAMES[s["mes"]] if s.get("mes") else "?"
        exemplos = "; ".join(s["nomes"][:2])
        print(f"  {s['cidade']:25s} {s['total_eventos']:>7}  [{mes}] {exemplos}")


def cmd_stats(q: EventQuery):
    all_events = q.all()
    from collections import Counter
    dist = Counter(e.get("mes") for e in all_events if e.get("mes"))
    prec = Counter(e.get("precisao", "?") for e in all_events)
    total = len(all_events)
    sem_mes = sum(1 for e in all_events if not e.get("mes"))

    print(f"\n=== EventRadar Stats — {total} eventos totais ===\n")
    print(f"  Com mês resolvido : {total - sem_mes} ({(total-sem_mes)/total*100:.1f}%)")
    print(f"  Indeterminados    : {sem_mes}\n")
    print("  Precisão:")
    for p, n in prec.most_common():
        print(f"    {p:15s} {n:5d}")
    print("\n  Distribuição mensal:")
    for m in range(1, 13):
        bar = "█" * (dist[m] // 5)
        print(f"    {_MONTH_NAMES[m]:9s} {dist[m]:4d}  {bar}")


def main():
    parser = argparse.ArgumentParser(
        prog="python -m src.skills.event_radar",
        description="Consulta eventos mapeados pelo EventRadar",
    )
    parser.add_argument("--mes", type=int, help="Mês (1-12)")
    parser.add_argument("--dias", type=int, default=30, help="Janela em dias (default: 30)")
    parser.add_argument("--demand", action="store_true", help="Sinais de demanda por cidade")
    parser.add_argument("--stats", action="store_true", help="Distribuição e estatísticas")
    parser.add_argument("--json", action="store_true", help="Output em JSON")
    args = parser.parse_args()

    q = EventQuery()

    if args.stats:
        cmd_stats(q)
    elif args.demand:
        if args.json:
            print(json.dumps(q.demand_signals(days=args.dias), ensure_ascii=False, indent=2))
        else:
            cmd_demand(q, days=args.dias)
    elif args.mes:
        if args.json:
            print(json.dumps(q.by_month(args.mes), ensure_ascii=False, indent=2))
        else:
            cmd_by_month(q, args.mes)
    else:
        if args.json:
            print(json.dumps(q.upcoming(days=args.dias), ensure_ascii=False, indent=2))
        else:
            cmd_upcoming(q, days=args.dias)


if __name__ == "__main__":
    main()
