#!/bin/sh
# s6-overlay stage2 hook — runs as root after the supervision tree is
# up but before user services start. Handles UID/GID remap, volume
# chown, config seeding, and skills sync.
#
# Per-service privilege drop happens inside each service's `run` script
# (and in main-wrapper.sh) via s6-setuidgid, not here.
#
# Wired into the image as /etc/cont-init.d/01-seeker_agent-setup by the
# Dockerfile. The shim at docker/entrypoint.sh forwards to this script
# so external references to docker/entrypoint.sh still work.
#
# NB: cont-init.d scripts run with no arguments — the user's CMD args
# are NOT visible here. That's fine: we use Architecture B (s6-overlay
# main-program model), so main-wrapper.sh runs the CMD with full
# stdin/stdout/stderr access and handles arg parsing there.

set -eu

SEEKER_HOME="${SEEKER_HOME:-/opt/data}"
INSTALL_DIR="/opt/seeker_agent"

# --- Bootstrap SEEKER_HOME as root ---
# Create the directory (and any missing parents) while we still have root
# privileges so the chown checks below see real metadata and the later
# `s6-setuidgid seeker_agent mkdir -p` block doesn't EACCES on root-owned
# ancestors. Without this, custom SEEKER_HOME paths whose parents only
# root can create (e.g. `SEEKER_HOME=/home/seeker_agent/.seeker_agent` in a Compose
# file, or any path under a fresh / not pre-populated by the image)
# fail on first boot with `mkdir: cannot create directory '/...': Permission
# denied` and the cont-init hook exits non-zero. Idempotent — `mkdir -p`
# is a no-op if the dir already exists. (#18482, salvages #18488)
mkdir -p "$SEEKER_HOME"

# --- UID/GID remap ---
# Accept PUID/PGID as aliases for HERMES_UID/HERMES_GID.  NAS users (UGOS,
# Synology, unRAID) expect the LinuxServer.io PUID/PGID convention and
# bind-mount /opt/data from a host directory owned by their own UID; without
# this alias those vars are silently ignored and the s6-setuidgid drop to
# UID 10000 leaves the runtime unable to read the volume.  HERMES_UID/
# HERMES_GID still win when both are set.  See #15290, salvages #25872.
HERMES_UID="${HERMES_UID:-${PUID:-}}"
HERMES_GID="${HERMES_GID:-${PGID:-}}"

if [ -n "${HERMES_UID:-}" ] && [ "$HERMES_UID" != "$(id -u seeker_agent)" ]; then
    echo "[stage2] Changing seeker_agent UID to $HERMES_UID"
    usermod -u "$HERMES_UID" seeker_agent
fi
if [ -n "${HERMES_GID:-}" ] && [ "$HERMES_GID" != "$(id -g seeker_agent)" ]; then
    echo "[stage2] Changing seeker_agent GID to $HERMES_GID"
    # -o allows non-unique GID (e.g. macOS GID 20 "staff" may already
    # exist as "dialout" in the Debian-based container image).
    groupmod -o -g "$HERMES_GID" seeker_agent 2>/dev/null || true
fi

# --- Docker socket group membership (docker-in-docker / DooD) ---
# When the user bind-mounts the host Docker daemon socket
# (`-v /var/run/docker.sock:/var/run/docker.sock`) to use the `docker`
# terminal backend from inside the container, the socket is owned by the
# host's `docker` group (or root). The supervised seeker_agent user (UID 10000)
# is not a member of any group that matches the socket's GID, so every
# `docker` invocation EACCES'es and `check_terminal_requirements()` fails.
# See #16703.
#
# Granting the supp group via `docker run --group-add <gid>` alone is
# NOT sufficient with our s6-setuidgid privilege drop: s6-setuidgid (and
# gosu, the older shim) calls initgroups() for the target user, which
# rebuilds the supplementary group list from /etc/group. Without an
# /etc/group entry whose GID matches the socket, the kernel-granted
# supp group is silently wiped between PID 1 and the dropped process.
# Confirmed empirically: `--group-add 998` alone leaves the dropped
# seeker_agent process with `Groups: 10000` (998 gone); after this hook adds
# the entry, the dropped process has `Groups: 998 10000` as expected.
#
# Fix: detect the socket's GID at boot and ensure /etc/group has a
# matching entry that includes seeker_agent. Idempotent across container
# restarts. Skipped silently when no socket is bind-mounted.
#
# Handles the awkward corner cases:
#   - socket owned by GID 0 (root) — some Podman setups; usermod -aG root
#   - socket GID already used by a known container group (e.g. tty=5):
#     reuse that group's name rather than creating a duplicate
#   - seeker_agent is already a member of the right group (idempotent restart)
#   - chown/groupadd failures under rootless containers — non-fatal
for sock in /var/run/docker.sock /run/docker.sock; do
    [ -S "$sock" ] || continue
    sock_gid=$(stat -c '%g' "$sock" 2>/dev/null) || continue
    [ -n "$sock_gid" ] || continue
    # Already a member? Nothing to do.
    if id -G seeker_agent 2>/dev/null | tr ' ' '\n' | grep -qx "$sock_gid"; then
        echo "[stage2] seeker_agent already in group $sock_gid for $sock"
        break
    fi
    # Resolve or create a group name for this GID.
    sock_group=$(getent group "$sock_gid" 2>/dev/null | cut -d: -f1)
    if [ -z "$sock_group" ]; then
        sock_group="hostdocker"
        if ! groupadd -g "$sock_gid" "$sock_group" 2>/dev/null; then
            echo "[stage2] Warning: groupadd -g $sock_gid $sock_group failed; skipping docker socket group setup"
            break
        fi
        echo "[stage2] Created group $sock_group (GID $sock_gid) for Docker socket"
    fi
    if usermod -aG "$sock_group" seeker_agent 2>/dev/null; then
        echo "[stage2] Added seeker_agent to group $sock_group (GID $sock_gid) for $sock"
    else
        echo "[stage2] Warning: usermod -aG $sock_group seeker_agent failed; docker backend may fail with EACCES"
    fi
    break
done

# --- Fix ownership of data volume ---
# When HERMES_UID is remapped or the top-level $SEEKER_HOME isn't owned by
# the runtime seeker_agent UID, restore ownership to seeker_agent — but ONLY for the
# directories seeker_agent actually writes to. The full $SEEKER_HOME may be a
# host-mounted bind containing unrelated user files; `chown -R` would
# silently destroy host ownership of those (see issue #19788).
#
# The canonical list of seeker_agent-owned subdirs is the same one the s6-setuidgid
# mkdir -p block below seeds. Keep them in sync if the seed list changes.
actual_hermes_uid=$(id -u seeker_agent)
needs_chown=false
if [ -n "${HERMES_UID:-}" ] && [ "$HERMES_UID" != "10000" ]; then
    needs_chown=true
elif [ "$(stat -c %u "$SEEKER_HOME" 2>/dev/null)" != "$actual_hermes_uid" ]; then
    needs_chown=true
fi
if [ "$needs_chown" = true ]; then
    echo "[stage2] Fixing ownership of $SEEKER_HOME (targeted) to seeker_agent ($actual_hermes_uid)"
    # In rootless Podman the container's "root" is mapped to an
    # unprivileged host UID — chown will fail. That's fine: the volume
    # is already owned by the mapped user on the host side.
    #
    # Top-level $SEEKER_HOME: chown the directory itself (not its contents)
    # so seeker_agent can mkdir new subdirs but bind-mounted host files keep
    # their existing ownership.
    chown seeker_agent:seeker_agent "$SEEKER_HOME" 2>/dev/null || \
        echo "[stage2] Warning: chown $SEEKER_HOME failed (rootless container?) — continuing"
    # SeekerAgent-owned subdirs: recursive chown is safe here because these are
    # created and managed exclusively by seeker_agent (see the s6-setuidgid mkdir
    # -p block below for the canonical list).
    for sub in cron sessions logs hooks memories skills skins plans workspace home profiles; do
        if [ -e "$SEEKER_HOME/$sub" ]; then
            chown -R seeker_agent:seeker_agent "$SEEKER_HOME/$sub" 2>/dev/null || \
                echo "[stage2] Warning: chown $SEEKER_HOME/$sub failed (rootless container?) — continuing"
        fi
    done
    # SeekerAgent-owned trees under $INSTALL_DIR must be re-chowned when the UID
    # is remapped — otherwise:
    #   - .venv: lazy_deps.py cannot install platform packages (discord.py,
    #     telegram, slack, etc.) with EACCES (#15012, #21100)
    #   - ui-tui: esbuild rebuilds dist/entry.js on every TUI launch (when
    #     the source mtime is newer than dist/ or when HERMES_TUI_FORCE_BUILD
    #     is set) and writes to ui-tui/dist/. Without this chown the new
    #     seeker_agent UID can't write the build output (#28851).
    #   - node_modules: root-level dependencies (puppeteer, web tooling)
    #     that runtime code may walk/update.
    # The set mirrors the build-time `chown -R seeker_agent:seeker_agent` line in the
    # Dockerfile — keep them in sync if the Dockerfile chown set changes.
    # These are under $INSTALL_DIR (not $SEEKER_HOME), so the bind-mount
    # concern doesn't apply — recursive is fine.
    chown -R seeker_agent:seeker_agent \
        "$INSTALL_DIR/.venv" \
        "$INSTALL_DIR/ui-tui" \
        "$INSTALL_DIR/node_modules" \
        2>/dev/null || \
        echo "[stage2] Warning: chown of build trees failed (rootless container?) — continuing"
fi

# Always reset ownership of $SEEKER_HOME/profiles to seeker_agent on every
# boot. Profile dirs and files can land owned by root when commands
# are invoked via `docker exec <container> seeker_agent …` (which defaults
# to root unless `-u` is passed), and that breaks the cont-init
# reconciler (02-reconcile-profiles) which runs as seeker_agent and walks
# the profiles dir. Idempotent; skipped on rootless containers where
# chown would fail.
if [ -d "$SEEKER_HOME/profiles" ]; then
    chown -R seeker_agent:seeker_agent "$SEEKER_HOME/profiles" 2>/dev/null || true
fi

# --- config.yaml permissions ---
# Ensure config.yaml is readable by the seeker_agent runtime user even if it
# was edited on the host after initial ownership setup.
if [ -f "$SEEKER_HOME/config.yaml" ]; then
    chown seeker_agent:seeker_agent "$SEEKER_HOME/config.yaml" 2>/dev/null || true
    chmod 640 "$SEEKER_HOME/config.yaml" 2>/dev/null || true
fi

# --- Seed directory structure as seeker_agent user ---
# Run as seeker_agent via s6-setuidgid so dirs end up owned correctly (matters
# under rootless Podman where chown back to root would fail).
#
# Use direct `mkdir -p` invocation (no `sh -c "..."` wrapper) so the
# shell isn't a second interpreter — defends against $SEEKER_HOME values
# containing shell metacharacters. PR #30136 review item O2.
s6-setuidgid seeker_agent mkdir -p \
    "$SEEKER_HOME/cron" \
    "$SEEKER_HOME/sessions" \
    "$SEEKER_HOME/logs" \
    "$SEEKER_HOME/hooks" \
    "$SEEKER_HOME/memories" \
    "$SEEKER_HOME/skills" \
    "$SEEKER_HOME/skins" \
    "$SEEKER_HOME/plans" \
    "$SEEKER_HOME/workspace" \
    "$SEEKER_HOME/home"

# --- Install-method stamp (read by detect_install_method() in seeker_agent status) ---
# Preserved from the tini-era entrypoint (PR #27843). Must be written as
# the seeker_agent user so ownership matches the file's documented owner.
# tee is invoked directly via s6-setuidgid (no `sh -c` wrapper) for the
# same shell-metacharacter safety described above.
printf 'docker\n' | s6-setuidgid seeker_agent tee "$SEEKER_HOME/.install_method" >/dev/null \
    || true

# --- Seed config files (only on first boot) ---
seed_one() {
    dest=$1
    src=$2
    if [ ! -f "$SEEKER_HOME/$dest" ] && [ -f "$INSTALL_DIR/$src" ]; then
        s6-setuidgid seeker_agent cp "$INSTALL_DIR/$src" "$SEEKER_HOME/$dest"
    fi
}
seed_one ".env" ".env.example"
seed_one "config.yaml" "cli-config.yaml.example"
seed_one "SOUL.md" "docker/SOUL.md"

# .env holds API keys and secrets — restrict to owner-only access. Applied
# unconditionally (not only on first-seed) so a host-mounted .env that was
# created with a permissive umask gets tightened on every container start.
if [ -f "$SEEKER_HOME/.env" ]; then
    chown seeker_agent:seeker_agent "$SEEKER_HOME/.env" 2>/dev/null || true
    chmod 600 "$SEEKER_HOME/.env" 2>/dev/null || true
fi

# auth.json: bootstrap from env on first boot only. Same semantics as the
# pre-s6 entrypoint — the [ ! -f ] guard is critical to avoid clobbering
# rotated refresh tokens on container restart.
if [ ! -f "$SEEKER_HOME/auth.json" ] && [ -n "${HERMES_AUTH_JSON_BOOTSTRAP:-}" ]; then
    printf '%s' "$HERMES_AUTH_JSON_BOOTSTRAP" > "$SEEKER_HOME/auth.json"
    chown seeker_agent:seeker_agent "$SEEKER_HOME/auth.json" 2>/dev/null || true
    chmod 600 "$SEEKER_HOME/auth.json"
fi

# --- Sync bundled skills ---
# Invoke the venv's python by absolute path so we don't need a `sh -c`
# wrapper to source the activate script. This is safe because
# skills_sync.py doesn't depend on any environment exports beyond what
# the python binary's own bin-stub already sets up (sys.path is rooted
# at the venv's site-packages by virtue of running .venv/bin/python).
if [ -d "$INSTALL_DIR/skills" ]; then
    s6-setuidgid seeker_agent "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/tools/skills_sync.py" \
        || echo "[stage2] Warning: skills_sync.py failed; continuing"
fi

# --- Discover agent-browser's Chromium binary ---
# The image's Dockerfile runs `npx playwright install chromium`, which
# populates ``$PLAYWRIGHT_BROWSERS_PATH`` (=/opt/seeker_agent/.playwright) with
# a ``chromium_headless_shell-<build>/chrome-headless-shell-linux64/``
# directory. agent-browser (the runtime CLI SeekerAgent spawns for the
# browser tool) doesn't recognise this layout in its own cache scan and
# fails with "Auto-launch failed: Chrome not found" — even though the
# binary is right there (#15697).
#
# Fix: locate the binary at boot and export ``AGENT_BROWSER_EXECUTABLE_PATH``
# via /run/s6/container_environment so the `with-contenv` shebang on
# main-wrapper.sh propagates it into the supervised ``seeker_agent`` process
# and thence to agent-browser subprocesses.
#
# - Skipped when the user has already set ``AGENT_BROWSER_EXECUTABLE_PATH``
#   (lets users override with a system Chrome install).
# - Filename-matched (not path-matched): the chromium dir contains many
#   shared libraries (libGLESv2.so, libEGL.so, ...) which inherit the
#   executable bit from Playwright's tarball but are NOT browser binaries.
#   We only accept files whose basename is chrome / chromium /
#   chrome-headless-shell / chromium-browser. Compare PR #18635's earlier
#   ``find | grep -Ei 'chrome|chromium'`` which would match the path
#   ``.../chrome-headless-shell-linux64/libGLESv2.so`` and pick a .so.
# - Quietly skipped when $PLAYWRIGHT_BROWSERS_PATH doesn't exist (e.g.
#   custom builds that strip Playwright).
if [ -z "${AGENT_BROWSER_EXECUTABLE_PATH:-}" ] && \
        [ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && \
        [ -d "$PLAYWRIGHT_BROWSERS_PATH" ]; then
    browser_bin=$(find "$PLAYWRIGHT_BROWSERS_PATH" -type f -executable \
        \( -name 'chrome' -o -name 'chromium' \
           -o -name 'chrome-headless-shell' -o -name 'chromium-browser' \) \
        2>/dev/null | head -n 1)
    if [ -n "$browser_bin" ]; then
        echo "[stage2] Found agent-browser Chromium binary: $browser_bin"
        # Write to s6's container_environment so with-contenv picks it
        # up for all supervised services (main-seeker_agent, dashboard, etc.).
        # Idempotent: each boot overwrites with the current path.
        printf '%s' "$browser_bin" > /run/s6/container_environment/AGENT_BROWSER_EXECUTABLE_PATH
    else
        echo "[stage2] Warning: no Chromium binary under $PLAYWRIGHT_BROWSERS_PATH; browser tool may fail"
    fi
fi

echo "[stage2] Setup complete; starting user services"
