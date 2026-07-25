# GCP Service Account Rotation Runbook

**Severity:** Medium (file exists locally in feature branches of `E:\`, never reached public GitHub).
**Linked finding:** F-07 in `.planning/phases/00-production-hardening/00-VERIFICATION.md`.
**Status as of 2026-07-16:** File present at `E:\Seeker.Bot\Credenciais\service-account.json.json`. **Rotation at GCP console still required.**

---

## Why this matters

The file `E:\Seeker.Bot\Credenciais\service-account.json.json` is a GCP service account key in JSON form. Service account keys:

1. **Cannot be scoped** — anyone with the JSON file has full IAM permissions of that service account until revoked.
2. **Survive in git history** — even if the working copy is deleted, any branch where it was committed retains it. The audit confirmed it appeared in feature branches of `E:\` but never in tracked files of `origin/main`.
3. **Trigger GCP Secret Manager compromise** — if any process loads this file (e.g., Drive exporter at `src/core/exporters/drive.py`), the key is sent over the network to `oauth2.googleapis.com`. If a network intermediary is compromised, the key is captured mid-flight.

## What you need to do

### Step 1 — Identify which service account this key belongs to (2 min)

Open `E:\Seeker.Bot\Credenciais\service-account.json.json` in any text editor (NOT a browser; local file is fine). Look for the `client_email` field, e.g.:

```json
{
  "type": "service_account",
  "project_id": "your-project-12345",
  "private_key_id": "abcd1234...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...",
  "client_email": "seeker-bot-exporter@your-project-12345.iam.gserviceaccount.com",
  ...
}
```

The `client_email` is the canonical identifier. The `project_id` is the GCP project that owns it.

### Step 2 — Disable the leaked key (3 min)

1. Open https://console.cloud.google.com/iam-admin/serviceaccounts?project=YOUR_PROJECT_ID
2. Find the service account by `client_email`.
3. Click on it → **Keys** tab.
4. Find the key whose `Key ID` matches the `private_key_id` in the local JSON. If unsure, look at the **Created** date — older is the leaked one.
5. Click the trash icon → **Delete key**.

This revokes the leaked key immediately. The local JSON file becomes worthless for authentication.

### Step 3 — Create a fresh key (3 min)

Still on the Keys tab of the same service account:

1. **Add Key** → **Create new key** → **JSON** → **Create**.
2. A new JSON downloads. Save it to `E:\Seeker.Bot\Credenciais\service-account.json.json` (overwrite the old one).
3. Set restrictive file permissions:
   ```powershell
   icacls "E:\Seeker.Bot\Credenciais\service-account.json.json" /inheritance:r /grant:r "$env:USERNAME:R"
   ```
   (Owner-only read. Blocks accidental reads by other local users.)

### Step 4 — Verify Drive exporter still works

```powershell
cd E:\Seeker.Bot
.venv\Scripts\activate
python -c "from src.core.exporters.drive import DriveExporter; print('OK')"
```

If you see `OK`, the new key is being picked up. The Drive exporter reads the JSON at module init.

### Step 5 — Audit git history (defensive)

The audit said this file **never reached origin/main**, but let's confirm:

```powershell
# Run on E: — searches all refs for the private_key_id (or the first 16 chars of it)
$keyid = "abcd1234efgh5678"   # from Step 1
git -C E:\Seeker.Bot log -p --all -S "$keyid" -- 'Credenciais/*'
```

If any commits match, those branches still contain the leaked key. Options:

- **Option A** — if the branch's work is already in `main`, delete the branch:
  ```powershell
  git push origin --delete feature/<branch-name>
  git branch -D feature/<branch-name>
  ```
- **Option B** — rewrite history with `git-filter-repo` (heavy; only if the branch must be preserved).

Either way, the leak is closed because **Step 2 already revoked the key**. Old key strings in git history are inert.

### Step 6 — Defense in depth (prevent recurrence)

1. **Never commit `Credenciais/*` to git.** Verify `.gitignore`:
   ```powershell
   findstr /B "Credenciais" E:\Seeker.Bot\.gitignore
   ```
   Expected line: `Credenciais/`. If missing, add it.

2. **Consider Workload Identity Federation** instead of static keys. If the Seeker.Bot process runs on a VM you control (GCE, GKE, Cloud Run), bind the service account to the instance metadata and let GCP mint short-lived tokens. No JSON file needed.

3. **Migrate the key to Google Secret Manager** and have the Seeker.Bot process fetch it at boot. The Drive exporter would need a one-time refactor (read from Secret Manager instead of disk).

4. **Add a pre-commit hook** to block JSON files under `Credenciais/`:
   ```bash
   # .git/hooks/pre-commit
   if git diff --cached --name-only | grep -q '^Credenciais/.*\.json$'; then
       echo "BLOCKED: GCP credential JSON detected in staged files."
       exit 1
   fi
   ```

## Tracking

Linked UAT: `.planning/phases/00-production-hardening/00-UAT.md` — item **T-02** (GCP exposure subset) / **F-07** in VERIFICATION.md.
Once Step 2 (revocation) is confirmed at GCP, mark F-07 as `resolved` with the date.

---

## Quick checklist

- [ ] Step 1 — `client_email` identified
- [ ] Step 2 — Leaked key deleted at console.cloud.google.com
- [ ] Step 3 — Fresh key generated and saved
- [ ] Step 4 — Drive exporter boots with new key
- [ ] Step 5 — `git log -S <keyid>` returns no tracked files
- [ ] Step 6 — `.gitignore` confirmed; pre-commit hook in place

Date completed: __________
