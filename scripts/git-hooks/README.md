# Git hooks for Seeker.Bot

Tracked copies of git hooks. The actual hook files live in `.git/hooks/` which
is untracked, so we keep the source-of-truth here and bootstrap with
`install.sh`.

## Install (once after clone)

```bash
bash scripts/git-hooks/install.sh
```

On Windows / Git Bash this copies the hooks into `.git/hooks/`. On *nix it
symlinks them so edits here propagate immediately.

## Hooks

### `pre-commit`

Blocks any staged diff that contains a GitHub Personal Access Token,
Anthropic/OpenAI/DeepSeek-style API key, Google API key, NVIDIA NIM key,
or Groq key.

Patterns currently detected:
- `ghp_…` (classic PAT)
- `github_pat_…` (fine-grained PAT)
- `gho_…`, `ghs_…` (OAuth / server-to-server)
- `sk-…` (OpenAI, DeepSeek)
- `AIzaSy…` (Google)
- `nvapi-…` (NVIDIA NIM)
- `gsk_…` (Groq)

Excluded paths (kept out of the scan because they're documentation
or the hook itself):
- `docs/PAT_ROTATION_RUNBOOK.md`
- `.git/hooks/pre-commit`

To bypass in a true emergency: `git commit --no-verify`. Don't.
