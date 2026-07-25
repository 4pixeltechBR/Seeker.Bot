"""
MCP Wrapper — Launches Node.js MCP servers without spawning a visible terminal window.

Usage in config/mcp_servers.json:
  "command": "E:\\Seeker.Bot\\.venv\\Scripts\\pythonw.exe",
  "args": ["E:\\Seeker.Bot\\scripts\\mcp_wrapper.py", "npx", "-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\Victor"]

Why: On Windows, `npx` is a .CMD file that the OS runs via cmd.exe, creating
a console window. Worse, npx-cli.js itself spawns cmd.exe to execute the
target package's bin shim, creating yet another console window.

This wrapper bypasses both layers:
  1. Resolves `npx` to `node.exe` + `npx-cli.js` directly (no cmd.exe)
  2. Intercepts the npx output to find the package's actual entry point
  3. Runs the entry point via node.exe directly (no cmd.exe shim)

The result: zero console windows, MCP servers run in the background.
"""

import os
import re
import subprocess
import sys

# CREATE_NO_WINDOW = 0x08000000 (Windows). Avoid console popup for child processes.
CREATE_NO_WINDOW = 0x08000000


_NODEJS_DIR = os.environ.get("ProgramFiles", r"C:\Program Files") + r"\nodejs"
_NODE_EXE = os.path.join(_NODEJS_DIR, "node.exe")
_NPX_CLI_JS = os.path.join(_NODEJS_DIR, "node_modules", "npm", "bin", "npx-cli.js")
_NPM_CACHE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "npm-cache", "_npx",
)


def _find_cached_package_index_js(package_name: str) -> str | None:
    """Search npm-cache/_npx for the most recent cached version of `package_name`
    and return the path to its `dist/index.js` (or `index.js`).

    The cache layout is: %LOCALAPPDATA%\\npm-cache\\_npx\\<hash>\\node_modules\\<package>\\
    Each npx run uses a fresh hash directory.
    """
    if not os.path.isdir(_NPM_CACHE_DIR):
        return None

    # Find all directories matching <hash>/node_modules/<package_name>
    candidates = []
    try:
        for hash_dir in os.listdir(_NPM_CACHE_DIR):
            nm_dir = os.path.join(_NPM_CACHE_DIR, hash_dir, "node_modules", package_name)
            if os.path.isdir(nm_dir):
                mtime = os.path.getmtime(nm_dir)
                candidates.append((mtime, nm_dir))
    except OSError:
        return None

    if not candidates:
        return None

    # Use the most recently modified cache
    candidates.sort(reverse=True)
    pkg_dir = candidates[0][1]

    # Look for the entry point: dist/index.js or index.js
    for rel in ("dist/index.js", "index.js", "dist/cli.js", "bin/cli.js"):
        candidate = os.path.join(pkg_dir, rel)
        if os.path.isfile(candidate):
            return candidate

    return None


def _resolve_npx_args(package_name: str, original_args: list[str]) -> list[str] | None:
    """If the npx args are `-y <package> <user-args>...`, return the cached
    entry point path and the user-args. Otherwise return None.
    """
    # original_args like: ['-y', '@modelcontextprotocol/server-filesystem', 'C:\\Users\\Victor']
    if "-y" in original_args:
        idx = original_args.index("-y")
        if idx + 1 < len(original_args):
            pkg = original_args[idx + 1]
            user_args = original_args[idx + 2:]
            index_js = _find_cached_package_index_js(pkg)
            if index_js:
                return [index_js, *user_args]
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: mcp_wrapper.py <command> [args...]", file=sys.stderr)
        return 2

    raw_command = sys.argv[1]
    raw_args = sys.argv[2:]
    base = os.path.basename(raw_command).lower()

    command: str
    args: list[str]

    # Strategy A: command is "npx" — try to bypass npx entirely and run the
    # cached package's index.js directly via node.exe.
    if base in ("npx", "npx.cmd"):
        if os.path.isfile(_NODE_EXE):
            direct_args = _resolve_npx_args(
                # extract package name from raw_args
                *[a for a in raw_args if a.startswith("@")] or [""],
                raw_args,
            ) if any(a.startswith("@") for a in raw_args) else None

            if direct_args is not None:
                command, args = _NODE_EXE, direct_args
            else:
                # Fallback: run npx via node (still avoids the .cmd shim)
                if os.path.isfile(_NPX_CLI_JS):
                    command, args = _NODE_EXE, [_NPX_CLI_JS, *raw_args]
                else:
                    command, args = raw_command, raw_args
        else:
            command, args = raw_command, raw_args
    else:
        # Non-npx command: run as-is with CREATE_NO_WINDOW
        command, args = raw_command, raw_args

    # Verify the resolved executable exists.
    if not os.path.isfile(command):
        print(f"[mcp_wrapper] command not found: {command}", file=sys.stderr)
        return 127

    # Launch with CREATE_NO_WINDOW so no console pops up.
    try:
        proc = subprocess.Popen(
            [command, *args],
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
            env=os.environ.copy(),
            creationflags=CREATE_NO_WINDOW,
        )
    except FileNotFoundError as e:
        print(f"[mcp_wrapper] command not found: {command}", file=sys.stderr)
        print(f"[mcp_wrapper] {e}", file=sys.stderr)
        return 127
    except Exception as e:
        print(f"[mcp_wrapper] failed to launch: {e}", file=sys.stderr)
        return 1

    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 130


if __name__ == "__main__":
    sys.exit(main())
