# GitHub PAT Rotation Runbook

**Severity:** High (token was in plaintext in `D:\Seeker GitHub\.git\config`).
**Status as of 2026-05-15:** Token removed from local config. **Rotation at GitHub still required.**

---

## What was wrong

`D:\Seeker GitHub\.git\config` contained:

```
[remote "origin"]
    url = https://ghp_REDACTED@github.com/4pixeltechBR/Seeker.Bot.git
```

The personal access token was embedded as the URL username. Any backup, screenshot, accidental `cat` in a Slack paste, or stolen disk image would expose it. Git tools also occasionally print remote URLs in error messages.

## What this fix already did

Ran on `D:\Seeker GitHub`:

```bash
git remote set-url origin https://github.com/4pixeltechBR/Seeker.Bot.git
git config --local credential.helper manager-core
```

The token is no longer in `.git/config`. Future pushes will use Windows Credential Manager (`manager-core`) to look up credentials. On the **next push**, Windows will prompt once, store the credential in the Credential Manager vault, and reuse it from there.

## What you still need to do

The token `ghp_REDACTED` is **still valid at GitHub** — removing it from the local config doesn't revoke it. To close the loop:

### Step 1 — Revoke the leaked PAT (5 min)

1. Open https://github.com/settings/tokens
2. Find the token whose name/scope matches the one used by `D:\Seeker GitHub`. If you can't identify it by name, revoke any token that has `repo` scope on `4pixeltechBR/Seeker.Bot` and was created before 2026-05-15.
3. Click **Delete** (or **Revoke**) on each. GitHub doesn't show the full token, only the prefix — `ghp_XhYY...` — match by prefix.

### Step 2 — Create a fresh PAT (3 min)

1. https://github.com/settings/tokens → **Generate new token (classic)** or **Fine-grained tokens** (preferred).
2. **Fine-grained recommended:**
   - Repository access: only `4pixeltechBR/Seeker.Bot`
   - Permissions: Contents = Read and write, Metadata = Read-only
   - Expiration: 90 days (set a calendar reminder)
3. Copy the token immediately — GitHub shows it only once.

### Step 3 — Save in Credential Manager (1 min, automatic)

On D:, just do a push:

```powershell
cd "D:\Seeker GitHub"
git push origin main
```

When prompted:
- **Username:** `4pixeltechBR` (or your GitHub login)
- **Password:** paste the new PAT

Windows Credential Manager stores it under `git:https://github.com`. Verify with:

```powershell
cmdkey /list:git:https://github.com
```

### Step 4 — Verify the cleanup

```powershell
# Should print 0
findstr /R "ghp_" "D:\Seeker GitHub\.git\config"

# Should show: https://github.com/4pixeltechBR/Seeker.Bot.git (no @ sign)
git -C "D:\Seeker GitHub" remote -v
```

### Step 5 — Check that E:\Seeker.Bot is clean

```powershell
findstr /R "ghp_" "E:\Seeker.Bot\.git\config"
```

If any match, repeat Steps 1-3 there. (As of the audit, E:'s config was already clean — this is a defensive double-check.)

### Step 6 — Audit history

The token was committed to the **local** D: config only; it never went to a tracked file, so `git log -p` won't find it in the public repo. But to be sure:

```powershell
# Run on both E: and D: — substitute the prefix you saw locally
$prefix = "ghp_XhYY"  # replace with the first 8 chars of the leaked token
git -C E:\Seeker.Bot log -p --all -S "$prefix"
git -C "D:\Seeker GitHub" log -p --all -S "$prefix"
```

If any commit contains the token, force-rotate **immediately** (Step 1 takes care of revocation; the commit history rewrite is a separate, larger operation — open a follow-up issue).

---

## Going forward — make this hard to repeat

1. **Never** put a PAT in a URL. Always rely on `credential.helper`.
2. Use **fine-grained tokens** scoped to one repo with minimum permissions.
3. **Rotate every 90 days.** Set a calendar reminder.
4. Add a pre-commit hook on both E: and D: that blocks any commit whose diff contains `ghp_`:

   ```bash
   # .git/hooks/pre-commit
   if git diff --cached | grep -qE 'ghp_[A-Za-z0-9]{30,}'; then
       echo "BLOCKED: GitHub PAT detected in staged diff."
       exit 1
   fi
   ```

5. Run `git secrets` or `gitleaks` periodically. Both can scan history retroactively.

---

## Tracking

Linked UAT: `.planning/phases/00-production-hardening/00-UAT.md` — item **T-09**.
Once Step 1 (revocation) is confirmed at GitHub, mark T-09 as `resolved` with the date.
