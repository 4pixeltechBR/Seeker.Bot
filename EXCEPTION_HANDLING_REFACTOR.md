# Exception Handling Refactoring Guide — 10/10 Code Quality Strategy

**Status:** Phase 2 - Exception Handler Refactoring (In Progress)  
**Total Violations Found:** 250+ generic `except Exception` handlers  
**Progress:** 3/43 refactored in bot.py (/email_test, /search, /memory)

---

## Summary

This document guides systematic refactoring of generic `except Exception` handlers to specific exception types across Seeker.Bot codebase, following the STRATEGY_10_10.md recommendations.

## Pattern Overview

### ❌ BEFORE (Generic - Problematic)
```python
try:
    result = await pipeline.operation()
    await message.answer(f"✅ Success: {result}")
except Exception as e:
    log.error(f"Error: {e}")
    await message.answer(f"❌ Error: {str(e)[:100]}")
```

### ✅ AFTER (Specific - Recommended)
```python
try:
    result = await pipeline.operation()
    await message.answer(f"✅ Success: {result}")
except (ValueError, KeyError) as e:
    log.error(f"[operation] Validation error: {e}", exc_info=True, extra={"error_type": type(e).__name__})
    await message.answer("❌ Invalid input or configuration")
except AttributeError as e:
    log.error(f"[operation] Resource unavailable: {e}", exc_info=True, extra={"error_type": "AttributeError"})
    await message.answer("❌ Required component not configured")
except asyncio.TimeoutError:
    log.warning("[operation] Operation timeout")
    await message.answer("⏱️ Operation took too long")
except RuntimeError as e:
    log.error(f"[operation] Execution error: {e}", exc_info=True, extra={"error_type": "RuntimeError"})
    await message.answer(f"❌ {str(e)[:100]}")
except Exception as e:
    # Catch-all for unexpected exceptions
    log.critical(f"[operation] Unexpected error: {e}", exc_info=True, extra={"error_type": type(e).__name__})
    await message.answer("❌ Operation failed unexpectedly")
```

## Exception Categories

### 1. **Validation Errors** (ValueError, KeyError, TypeError)
**When:** User input parsing, configuration validation, data validation  
**Examples:** Invalid JSON, missing dict keys, type mismatches  
**Response:** User-friendly message about what was invalid  
**Log Level:** ERROR with exc_info=True

```python
except (ValueError, KeyError, TypeError) as e:
    log.error(f"[operation] Validation error: {e}", exc_info=True, extra={"error_type": type(e).__name__})
    await message.answer("❌ Invalid input or configuration")
```

### 2. **Resource/Structure Errors** (AttributeError)
**When:** Missing methods, properties, or components  
**Examples:** Goal not found, pipeline attribute missing, service not initialized  
**Response:** User should check configuration or run diagnostics  
**Log Level:** ERROR with exc_info=True

```python
except AttributeError as e:
    log.error(f"[operation] Resource unavailable: {e}", exc_info=True, extra={"error_type": "AttributeError"})
    await message.answer("❌ Required component not configured")
```

### 3. **Timeout Errors** (asyncio.TimeoutError)
**When:** Async operations exceed time limits  
**Examples:** HTTP requests, long-running goals, database queries  
**Response:** Inform user about timeout, suggest retry  
**Log Level:** WARNING (expected in high-load scenarios)

```python
except asyncio.TimeoutError:
    log.warning(f"[operation] Timeout after {timeout}s")
    await message.answer(f"⏱️ Operation took too long (>{timeout}s)")
```

### 4. **Execution Errors** (RuntimeError, asyncio.CancelledError)
**When:** Operation fails during execution  
**Examples:** Goal cycle error, service returns error, resource exhausted  
**Response:** Include error details if user-safe  
**Log Level:** ERROR with exc_info=True

```python
except (RuntimeError, asyncio.CancelledError) as e:
    log.error(f"[operation] Execution error: {e}", exc_info=True, extra={"error_type": type(e).__name__})
    await message.answer(f"❌ Operation failed: {str(e)[:100]}")
```

### 5. **I/O Errors** (FileNotFoundError, OSError, IOError)
**When:** File operations, system calls  
**Examples:** Config file missing, permission denied, disk full  
**Response:** Inform about I/O problem  
**Log Level:** ERROR with exc_info=True

```python
except (FileNotFoundError, OSError) as e:
    log.error(f"[operation] I/O error: {e}", exc_info=True, extra={"error_type": type(e).__name__})
    await message.answer("❌ File or resource access failed")
```

### 6. **Unexpected Errors** (Generic Exception)
**When:** Any unexpected exception not caught above  
**Examples:** Library bugs, memory issues, unknown errors  
**Response:** Minimal info to user (don't expose internals)  
**Log Level:** CRITICAL with full context

```python
except Exception as e:
    log.critical(f"[operation] Unexpected error: {e}", exc_info=True, extra={"error_type": type(e).__name__})
    await message.answer("❌ Operation failed unexpectedly")
```

## Refactoring Checklist

For each exception handler, follow this checklist:

- [ ] **Identify exception types** likely to be raised in this code path
- [ ] **Catch specific exceptions** in order of specificity (most specific first)
- [ ] **Add logging context** with operation name and error type
- [ ] **Include exc_info=True** for all error-level logs
- [ ] **Provide user-friendly messages** (don't expose stack traces)
- [ ] **Add recovery hints** where applicable ("run /saude for diagnostics")
- [ ] **Keep catch-all Exception** as last handler for safety

## Files to Refactor (Priority Order)

### **Tier 1: Critical** (98 violations)
- [ ] `src/channels/telegram/bot.py` — **42 violations** (1/42 done)
  - Priority handlers: /email_test, /scout, /git_backup, /memory, /search, /rate
  - Other handlers: /status, /saude, /perf, /perf_detailed, /cascade_status, /recovery, /decay, /budget, /data_clean, /dashboard, /forecast, /print, /watch, /scout, /configure_news
  
- [ ] `src/core/executor/handlers/` — **35 violations**
  - Files to refactor: exception_handler.py, response_handler.py, goal_handler.py
  - Pattern: Goals may timeout, crash, or have invalid state
  
- [ ] `src/core/memory/storage.py` — **25 violations**
  - Database operations: INSERT, SELECT, UPDATE, DELETE
  - Patterns: Database locked, constraint violation, data type mismatch

### **Tier 2: High Priority** (50+ violations)
- [ ] `src/skills/*/` — Various skill handlers
  - Bug Analyzer, Email Monitor, Scout, Git Backup, News Skills
  - Pattern: External service calls, LLM API requests, web scraping

### **Tier 3: Medium Priority** (100+ violations)
- [ ] All remaining catch-all handlers
  - Message handlers, utility functions, goal implementations

## Implementation Progress

### Phase 1: Create Refactoring Infrastructure ✅ DONE
- [x] Create exceptions_handler.py with common patterns
- [x] Document specific exception types and responses
- [x] Create this refactoring guide

### Phase 2: Refactor Critical Handlers (IN PROGRESS)
- [x] Refactor bot.py /email_test handler (1/42)
- [ ] Refactor bot.py /scout handler (2/42)
- [ ] Refactor bot.py /git_backup handler (3/42)
- [ ] Refactor bot.py /memory handler (4/42)
- [ ] ... continue with remaining bot.py handlers
- [ ] Refactor executor handlers (35)
- [ ] Refactor storage handlers (25)

### Phase 3: Refactor Medium Priority Handlers
- [ ] Refactor skill handlers
- [ ] Refactor utility functions

### Phase 4: Testing and Validation
- [ ] Unit tests for each exception path
- [ ] Integration tests
- [ ] Manual testing of error scenarios
- [ ] Code coverage verification

## Example Refactoring: /scout Handler

**BEFORE:**
```python
except Exception as e:
    log.error(f"[scout] Erro ao disparar campanha: {e}", exc_info=True)
    await message.answer(
        f"❌ Erro ao disparar Scout: <code>{str(e)[:100]}</code>",
        parse_mode=ParseMode.HTML
    )
```

**AFTER:**
```python
except AttributeError as e:
    log.error(f"[scout] Scout skill not found or not ready: {e}", exc_info=True, 
              extra={"context": "scout_campaign", "error_type": "AttributeError"})
    await message.answer(
        "❌ Scout skill não está configurado.\nExecute `/saude` para verificar.",
        parse_mode=ParseMode.HTML
    )
except ValueError as e:
    log.error(f"[scout] Configuration error: {e}", exc_info=True,
              extra={"context": "scout_campaign", "error_type": "ValueError"})
    await message.answer(
        f"❌ Erro de configuração: {str(e)[:100]}",
        parse_mode=ParseMode.HTML
    )
except asyncio.TimeoutError:
    log.warning("[scout] Scout campaign timeout (>120s)")
    await message.answer(
        "⏱️ Timeout: Scout campaign demorou muito. Tente novamente.",
        parse_mode=ParseMode.HTML
    )
except (RuntimeError, OSError) as e:
    log.error(f"[scout] Execution error: {e}", exc_info=True,
              extra={"context": "scout_campaign", "error_type": type(e).__name__})
    await message.answer(
        f"❌ Erro ao executar Scout: {str(e)[:100]}",
        parse_mode=ParseMode.HTML
    )
except Exception as e:
    log.critical(f"[scout] Unexpected error in scout campaign: {e}", exc_info=True,
                 extra={"context": "scout_campaign", "error_type": type(e).__name__})
    await message.answer(
        "❌ Scout campaign failed unexpectedly",
        parse_mode=ParseMode.HTML
    )
```

## Validation Metrics

After refactoring is complete, verify:

```bash
# Count generic exception handlers remaining
grep -r "except Exception" src/ | wc -l  # Should be < 50

# Verify exc_info=True usage
grep -r "log.error.*except" src/ | grep -v "exc_info=True" | wc -l  # Should be 0

# Check for log context
grep -r "extra={.*error_type" src/ | wc -l  # Should match error count
```

## Testing Strategy

For each refactored handler, create tests:

```python
@pytest.mark.asyncio
async def test_email_test_timeout():
    """Verify timeout handling in /email_test"""
    # Mock goal to raise TimeoutError
    # Verify correct error message sent to user
    # Verify warning logged (not error)

@pytest.mark.asyncio
async def test_email_test_missing_goal():
    """Verify handling when email_monitor goal not found"""
    # Mock pipeline without email_monitor
    # Verify AttributeError caught
    # Verify helpful message with /saude hint
```

## Success Criteria

- [ ] Zero generic `except Exception` handlers in critical files
- [ ] All error handlers log with `exc_info=True`
- [ ] All errors include operation context in logs
- [ ] User-facing messages don't expose stack traces
- [ ] Test coverage of exception paths > 90%
- [ ] Code review score reaches 10/10

---

## Next Steps

1. **Immediately:** Continue refactoring bot.py handlers (currently at 1/42)
2. **Tomorrow:** Complete executor handlers and storage handlers
3. **Rest of week:** Skill handlers and utility functions
4. **Final:** Testing and validation phase

Estimated total time: **8-10 hours** for complete refactoring  
Estimated time savings in debugging: **5-10x** (specific exceptions vs generic)
