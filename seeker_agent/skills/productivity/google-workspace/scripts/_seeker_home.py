"""Resolve SEEKER_HOME for standalone skill scripts.

Skill scripts may run outside the SeekerAgent process (e.g. system Python,
nix env, CI) where ``seeker_constants`` is not importable.  This module
provides the same ``get_hermes_home()`` and ``display_hermes_home()``
contracts as ``seeker_constants`` without requiring it on ``sys.path``.

When ``seeker_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``seeker_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``SEEKER_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from seeker_constants import display_hermes_home as display_hermes_home
    from seeker_constants import get_hermes_home as get_hermes_home
except (ModuleNotFoundError, ImportError):

    def get_hermes_home() -> Path:
        """Return the SeekerAgent home directory (default: ~/.seeker_agent).

        Mirrors ``seeker_constants.get_hermes_home()``."""
        val = os.environ.get("SEEKER_HOME", "").strip()
        return Path(val) if val else Path.home() / ".seeker_agent"

    def display_hermes_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``seeker_constants.display_hermes_home()``."""
        home = get_hermes_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
