---
project: Seeker.Bot
type: brownfield
created: 2026-05-11
runtime: python-3.10
language: python
license: Apache-2.0
---

# Seeker.Bot — Project Spec

## What

Autonomous cognitive agent for Telegram with persistent memory, computer vision,
multi-provider LLM cascade, and 14+ modular background skills.

## Repo Layout

- `src/core/` — Pipeline, cognition, providers, safety, memory, hierarchy
- `src/skills/` — Autonomous background goals (briefing, health_monitor, sense_news,
  self_improvement S.A.R.A, knowledge_vault, etc)
- `src/channels/telegram/` — Aiogram 3 bot, command handlers, middlewares
- `src/providers/` — LLM provider adapters (NVIDIA, Groq, Gemini, DeepSeek, Mistral, Ollama)
- `config/` — model routing, skill toggles, .env templates
- `tests/` — pytest suite (~660 tests, 89% pass on last baseline)

## Architecture (at a glance)

- **CognitiveLoadRouter** (regex, 0ms) → REFLEX / DELIBERATE / DEEP
- **6-tier provider cascade** with RL Bandit (LinUCB shadow mode)
- **Evidence Arbitrage** (triangulation across providers)
- **VerificationGate / Judge** (separate model validates output)
- **Goal Scheduler** with priority + preemption + concurrent goal pool

## Two Repos

- **`E:\Seeker.Bot`** — production (commercial skills + dev work)
- **`D:\Seeker GitHub`** — public mirror at `github.com/4pixeltechBR/Seeker.Bot`
  (commercial skills stripped via `scripts/sync_to_public.bat`)

## State of v3.2

Current commit on `origin/main`: `530fa98` (post v3.2 hotfix + skill_creator fix).
S.A.R.A. has CodeValidator + ApprovalEngine + ErrorDatabase (Day 2-5 of the
v3 refactor master plan — landed via `feature/seeker-v3-refactor` work).

See `docs/SEEKER_MASTER_PLAN_2026.md` for the larger 4-week roadmap context
and `docs/SEEKER_CODE_REVIEW_2026-04-25.md` for the most recent code audit.
