# Python Migration Plan — 3.10 → 3.12

**Status:** Active migration in progress
**Deadline:** 2026-10-04 (Google API Core EOL for Python 3.10)
**Last updated:** 2026-05-15

---

## Why this matters

`google-api-core` (transitive dep of every Gemini / Drive / GCS path) drops Python 3.10 on **2026-10-04**. After that date, security patches and new Gemini features will only land for 3.11+.

The `FutureWarning` you see at every Seeker.Bot startup is the upstream advance notice:

```
FutureWarning: You are using a Python version (3.10.11) which Google
will stop supporting in new releases of google.api_core once it
reaches its end of life (2026-10-04). Please upgrade to the latest
Python version, or at least Python 3.11, to continue receiving
updates for google.api_core past that date.
```

---

## Current state

| Surface | Version | Notes |
|---------|---------|-------|
| `pyproject.toml` `requires-python` | `>=3.12` | Declared minimum, **not yet enforced at install** |
| `.github/workflows/ci.yml` | `python-version: '3.11'` | CI tests on 3.11 |
| Local runtime (Victor's machine) | `3.10.11` | Source of FutureWarning |
| Production runtime | same as local | Single-user deployment |

**Mismatch:** the project metadata declares 3.12 but the running interpreter is 3.10. The CI gate is 3.11, so we haven't actually validated 3.12 yet.

---

## Target

Settle on **Python 3.12** for both local and CI. Rationale:

- 3.12 is the current stable and the version `pyproject.toml` already declares.
- Faster comprehensions (PEP 709) and per-interpreter GIL groundwork (PEP 684) — both relevant to the pipeline's hot paths.
- Improved error messages reduce time spent diagnosing the cascade-bandit and reward-collector tracebacks.
- Long-term support window through 2028-10.

Not 3.13 because:
- Several scientific deps (numpy 1.x, some torch wheels) still lag on 3.13.
- We'd reopen the wheel compatibility surface we just closed for 3.12.

---

## Migration steps

### Phase 1 — Pre-flight (this PR)

- [x] Bump `pyproject.toml` `requires-python` to `>=3.12`
- [ ] Bump CI matrix from 3.11 to 3.12 in `.github/workflows/ci.yml`
- [ ] Add a `python --version` echo to the bot startup so the actual runtime is visible in logs
- [ ] Document this plan (this file)

### Phase 2 — Local upgrade

1. Install Python 3.12 alongside 3.10 (do **not** uninstall 3.10 yet — rollback safety).
2. Recreate the venv against 3.12:
   ```powershell
   py -3.12 -m venv .venv312
   .venv312\Scripts\activate
   pip install -e .[dev]
   ```
3. Run the full test suite + smoke tests:
   ```powershell
   python -m pytest tests/smoke_cache_phase*.py -q
   python -m src  # boot the bot, send a few queries, verify /perf and /rl_stats work
   ```
4. Watch for deprecation warnings — 3.12 deprecated `datetime.utcnow()`, several `asyncio` patterns, and the `imp` module. Fix at source, do not silence.

### Phase 3 — Production cutover

1. Verify all 13 skills boot:
   - `event_radar`, `tech_scout`, `sense_news`, `sherlock_news`, `email_monitor`, `briefing`, `desktop_watch`, `health_monitor`, `git_automation`, `knowledge_vault`, `skill_creator`, `self_improvement`, `remote_executor`.
2. Verify all 6 providers respond:
   - DeepSeek, Gemini, Groq, Mistral, NVIDIA NIM, Kimi (if configured).
3. Verify Google Drive exporter init path (the codepath that uses the just-fixed `import json` at `pipeline.py:234`).
4. Verify `FutureWarning` is gone from startup logs.

### Phase 4 — Cleanup

- [ ] Remove 3.10 from PATH and uninstall once 3.12 has run clean for 7 days.
- [ ] Drop any `# type: ignore` or `sys.version_info < (3, 11)` shims that exist for back-compat.
- [ ] Update README to state 3.12 minimum.

---

## Known compatibility risks

| Lib | 3.12 status | Mitigation |
|-----|-------------|-----------|
| `numpy` (used by `cascade.py` LinUCB) | 1.x supported on 3.12; 2.0+ ships 3.12 wheels | Pin to `>=1.26,<2.0` if 2.0 breaks anything else |
| `torch` (vision benchmark) | 2.2+ ships 3.12 wheels | `pip install --index-url https://download.pytorch.org/whl/cu121` may be needed |
| `playwright` | Full 3.12 support since 1.42 | None |
| `aiogram 3.x` | 3.12 supported | None |
| `fpdf` (event_radar PDF reports) | Pure Python, no issue | None |
| `psutil` (profiler) | 3.12 supported since 5.9.7 | Bump if pinned older |

---

## Rollback

If Phase 2 fails:
1. `deactivate && rm -rf .venv312`
2. Re-activate the original 3.10 venv.
3. Revert `pyproject.toml` to `requires-python = ">=3.10"` temporarily.
4. File a follow-up issue with the specific failure and dep stack.

Keep 3.10 installed until Phase 3 finishes clean.

---

## Tracking

Linked UAT: `.planning/phases/00-production-hardening/00-UAT.md` — item **T-08**.
Once Phase 3 lands, mark T-08 as `resolved` in the UAT file with the commit SHA.
