---
project: Seeker.Bot
created: 2026-05-11
status: active
---

# Seeker.Bot — Roadmap

Brownfield init focused on production hardening. Existing code already covers
the major architectural goals (cognitive routing, multi-provider cascade,
autonomous skills). Roadmap below addresses **open production issues** surfaced
by the most recent code review and runtime log analysis.

## Phase 0 — Production Hardening

**Goal:** Eliminate the open production-impact issues found in the
2026-04-25 code review and the 2026-05-11 runtime log analysis. Establish
clean baseline (UAT + verification) for future phases.

**Scope:**

- Tavily 432 resilience: circuit breaker + null-safety in reset path
- NVIDIA tier health investigation (0.1% success rate)
- Python 3.10 deprecation tracking (Google API Core EOL: 2026-10-04)
- Credentials hygiene (rotation of exposed GCP keys + PAT in `.git/config`)
- `tech_scout` query batching (15 calls/cycle → 1-3)
- Pipeline backpressure: extractor sync path adds 300-800ms to P95

**Status:** in-progress. UAT and VERIFICATION documents track the granular items.

## Phase 1 — Performance Sprint (planned, post-Phase 0)

**Goal:** P95 latency 16s → 4s; cost/cycle $0.008 → $0.005.

## Phase 2 — Robustez Sprint (planned)

**Goal:** Test pass-rate 89% → 95%; flaky tests eliminated.

## Phase 3 — Observability Sprint (planned)

**Goal:** Prometheus exporter + dashboard endpoints fully wired; `/saude`
shows real-time provider success rates.
