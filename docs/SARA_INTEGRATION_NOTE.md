# SARA CodeValidator — Integration Status

**Source:** commit `d7b6cc3` on `origin/feature/seeker-v3-refactor` (Apr 2026)
**Status (2026-05-15):** Library code imported to `main`, integration into `goal.py` and `bot.py` deferred.

---

## What landed in `main`

Two standalone, no-dependency-on-existing-code modules cherry-picked from the feature branch:

- `src/skills/self_improvement/code_validator.py` — 261 lines
  - Three-stage pipeline: `ast.parse` → `compile` → `pyright` (optional).
  - Fails fast at the cheapest stage. Skips gracefully when `pyright` is not installed.
  - `get_validator()` returns a process-wide singleton.

- `src/skills/self_improvement/error_database.py` — 496 lines
  - SQLite tables: `errors`, `patches`, `pending_patches`.
  - `sanitize_traceback()` — strips absolute paths and embedded secrets before sending to LLM.
  - `hash_traceback()` — SHA256 over the last 3 significant lines, stable across cosmetic re-formats.
  - 6-hour dedup window via `is_recent_duplicate()`.
  - `PendingPatchStore` — patches awaiting human approval, 24h expiry.
  - `get_pending_store()` returns a singleton shared with `bot.py`.

Both modules pass `ruff check` and import cleanly. They are dormant until wired in.

---

## What's NOT done — integration debt

The feature branch commit also modified `goal.py` (+145/-49) and `bot.py` (+159) to actually use these modules. Those edits are **not** in `main` because:

1. `bot.py` on `main` has post-April changes (load_dotenv reorder, `/rl_stats`, feedback buttons, etc.). Replaying the SARA approval-callback edits as a straight diff would conflict.
2. `goal.py` in `self_improvement/` has been touched by other commits since April. Diff replay would conflict.

Rather than do a large manual reconciliation in this audit pass, the modules are landed as **available primitives** and the integration is tracked here.

### Concrete TODOs to finish T-12

**`src/skills/self_improvement/goal.py`** — wire the modules in:

```python
from .code_validator import get_validator
from .error_database import ErrorDatabase, get_pending_store, sanitize_traceback, hash_traceback

# In __init__:
self.validator = get_validator()
self.error_db = ErrorDatabase()
self.pending = get_pending_store()

# In the patch-application path (before writing the fixed file):
# 1. Dedup check
if self.error_db.is_recent_duplicate(hash_traceback(tb)):
    return GoalResult(success=False, summary="Duplicate within 6h, skipped")

# 2. Validate the LLM's proposed patch
result = self.validator.validate(proposed_code)
if not result.ok:
    self.error_db.record_rejected_patch(...)
    return GoalResult(success=False, summary=f"Validator: {result.reason}")

# 3. Park as pending (don't overwrite the file yet)
patch_id = self.pending.create(file_path, proposed_code, expires_in_hours=24)

# 4. Return inline keyboard buttons
return GoalResult(
    success=True,
    summary=f"Patch pronto, aguardando aprovação (id={patch_id})",
    notification=f"S.A.R.A propôs patch para {file_path}. Aprove?",
    data={"buttons": [
        {"text": "✅ Aprovar", "callback_data": f"sara_approve:{patch_id}"},
        {"text": "❌ Rejeitar", "callback_data": f"sara_reject:{patch_id}"},
    ]},
)
```

**`src/channels/telegram/bot.py`** — add two callback handlers:

```python
@dp.callback_query(F.data.startswith("sara_approve:"))
async def cb_sara_approve(cq: CallbackQuery):
    patch_id = cq.data.split(":", 1)[1]
    store = get_pending_store()
    patch = store.get(patch_id)
    if patch is None or patch.is_expired():
        await cq.answer("Patch expirado ou não encontrado", show_alert=True)
        return
    # Backup original, write fixed code
    shutil.copy(patch.file_path, patch.file_path + ".bak")
    Path(patch.file_path).write_text(patch.code, encoding="utf-8")
    store.mark_applied(patch_id)
    await cq.message.edit_text("✅ Patch aplicado. Backup salvo em .bak.")

@dp.callback_query(F.data.startswith("sara_reject:"))
async def cb_sara_reject(cq: CallbackQuery):
    patch_id = cq.data.split(":", 1)[1]
    get_pending_store().mark_rejected(patch_id)
    await cq.message.edit_text("❌ Patch rejeitado. Arquivo original preservado.")
```

Place these next to the existing `cb_feedback_button` handler in `commands/system.py` for consistency.

---

## Acceptance criteria (UAT T-12)

> `src/skills/self_improvement/code_validator.py` existe na branch `main` e é chamado antes de qualquer write em `goal.py`.

- [x] File exists on `main`.
- [ ] Called before `goal.py` writes a patch (pending integration above).

Recommendation: ship the integration as a separate, focused phase (`01-sara-integration`) so the `goal.py` and `bot.py` edits can be planned and tested in isolation.
