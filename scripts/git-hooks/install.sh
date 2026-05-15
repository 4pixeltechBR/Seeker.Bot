#!/usr/bin/env bash
# Install Seeker.Bot git hooks into the local clone.
# Run once after clone:    bash scripts/git-hooks/install.sh
#
# Hooks live under scripts/git-hooks/ in the tracked tree so they're versioned
# alongside the code. .git/hooks/ is untracked, so this script symlinks (or
# copies on Windows) each tracked hook into place.

set -euo pipefail

cd "$(dirname "$0")/../.."  # repo root

if [ ! -d .git/hooks ]; then
    echo "ERR: .git/hooks not found — is this a git repo?"
    exit 1
fi

for hook in scripts/git-hooks/*; do
    name=$(basename "$hook")
    [ "$name" = "install.sh" ] && continue
    [ "$name" = "README.md" ] && continue

    target=".git/hooks/$name"

    # On *nix, symlink. On Windows (or if ln fails), copy.
    if ln -sf "../../$hook" "$target" 2>/dev/null; then
        echo "linked: $target -> $hook"
    else
        cp "$hook" "$target"
        chmod +x "$target"
        echo "copied: $hook -> $target"
    fi
done

echo "Done. Run 'git commit' to test the pre-commit hook."
