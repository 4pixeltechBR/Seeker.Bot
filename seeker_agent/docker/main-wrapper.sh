#!/command/with-contenv sh
# shellcheck shell=sh
# /opt/seeker_agent/docker/main-wrapper.sh — wraps the container's CMD with
# the same argument-routing logic the pre-s6 entrypoint.sh used. Runs
# as /init's "main program" (Docker CMD) so it inherits stdin/stdout/
# stderr from the container.
#
# Shebang note: /init scrubs env before invoking CMD, so a plain
# `#!/bin/sh` wrapper sees an empty environ and `ENV SEEKER_HOME=/opt/data`
# from the Dockerfile never reaches `seeker_agent`. with-contenv repopulates
# the env from /run/s6/container_environment before exec'ing, which is
# what s6-supervised services use too (see main-seeker_agent/run).
#
# Routing:
#   no args                       → exec `seeker_agent` (the default)
#   first arg is an executable    → exec it directly (sleep, bash, sh, …)
#   first arg is anything else    → exec `seeker_agent <args>` (subcommand passthrough)
#
# We drop to the seeker_agent user via `s6-setuidgid` so the supervised
# workload runs unprivileged (UID 10000 by default).
set -e

# HOME comes through with-contenv as /root (the /init context). Override
# to the seeker_agent user's home before dropping privileges so libraries that
# resolve paths via $HOME (e.g. discord lockfile under XDG_STATE_HOME)
# don't try to write to /root.
export HOME=/opt/data

cd /opt/data
# shellcheck disable=SC1091
. /opt/seeker_agent/.venv/bin/activate

if [ $# -eq 0 ]; then
    exec s6-setuidgid seeker_agent seeker_agent
fi

if command -v "$1" >/dev/null 2>&1; then
    # Bare executable — pass through directly.
    exec s6-setuidgid seeker_agent "$@"
fi

# SeekerAgent subcommand pass-through.
exec s6-setuidgid seeker_agent seeker_agent "$@"
