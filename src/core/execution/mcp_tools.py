"""
core.execution.mcp_tools — Definições de tools MCP expostas pelo Seeker.

Mapeia as funções do registry.py + session_store para tools MCP JSON-RPC
no formato padrão do protocolo MCP (tools/list + tools/call).

Tools expostas (7):
  - read_file, write_file, patch_file, execute_command, execute_code
  - read_session, record_session_turn

Resource exposto (1):
  - session://{session_id} (últimos 20 turnos de uma sessão)

Prompts expostos (2):
  - summarize_session, compare_sessions
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

log = logging.getLogger("seeker.execution.mcp_server.tools")


# ── Tool Schemas (formato MCP) ────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": (
            "Reads the contents of a text file from the local filesystem. "
            "Returns up to 5MB. Binary files return an error."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file (e.g. C:/Users/Victor/Documents/note.txt)",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": (
            "Creates or overwrites a file. Auto-checkpoint before mutation "
            "(workspace snapshot). Use with care — overwrites are not reversible."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path for the file."},
                "content": {"type": "string", "description": "Full content to write."},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "patch_file",
        "description": (
            "Surgical patch: replaces the FIRST occurrence of `target` text in `path` "
            "with `replacement` text. Auto-checkpoint before mutation. "
            "Preserves the rest of the file unchanged."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to file to patch."},
                "target": {"type": "string", "description": "Exact text to find (must match uniquely)."},
                "replacement": {"type": "string", "description": "New text to substitute."},
            },
            "required": ["path", "target", "replacement"],
            "additionalProperties": False,
        },
    },
    {
        "name": "execute_command",
        "description": (
            "Executes a shell command on the host (PowerShell on Windows, bash on Linux/Mac). "
            "Auto-checkpoint before execution. Tirith security blocks dangerous commands "
            "(rm, del, format, sudo, etc). 45s default timeout."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute."},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 45, max 300).",
                    "default": 45,
                    "minimum": 5,
                    "maximum": 300,
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "execute_code",
        "description": (
            "Executes Python code in a Docker sandbox (python:3.10-slim, --net=none). "
            "Isolated from host. 30s default timeout. Auto-starts Docker Desktop if needed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source code to execute."},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30, max 120).",
                    "default": 30,
                    "minimum": 5,
                    "maximum": 120,
                },
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_session",
        "description": (
            "Reads the last N turns of a Seeker session (typically telegram:<chat_id>). "
            "Used for session-to-session communication — fetch context from a "
            "previous conversation to continue it from another tool."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session identifier (e.g. 'telegram:7607235163').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of turns to return (default 20, max 100).",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["session_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_session_turn",
        "description": (
            "Appends a new turn (user or assistant message) to a Seeker session. "
            "Used to write to a session from another tool, enabling cross-session "
            "context persistence."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session identifier (e.g. 'telegram:7607235163').",
                },
                "role": {
                    "type": "string",
                    "enum": ["user", "assistant"],
                    "description": "Whose message this is.",
                },
                "content": {"type": "string", "description": "The message content."},
                "metadata": {
                    "type": "object",
                    "description": "Optional metadata as JSON object.",
                    "additionalProperties": True,
                },
            },
            "required": ["session_id", "role", "content"],
            "additionalProperties": False,
        },
    },
]


# ── Resource Templates ─────────────────────────────────────────────────

RESOURCES: list[dict[str, Any]] = [
    {
        "uri": "session://{session_id}",
        "name": "Seeker Session",
        "description": (
            "Read-only view of a Seeker session. Returns the last 20 turns as JSON. "
            "URI format: session://telegram:7607235163"
        ),
        "mimeType": "application/json",
    },
]


# ── Prompt Templates ──────────────────────────────────────────────────

PROMPTS: list[dict[str, Any]] = [
    {
        "name": "summarize_session",
        "description": "Returns the full content of a session, formatted for LLM summarization.",
        "arguments": [
            {
                "name": "session_id",
                "description": "Session identifier (e.g. 'telegram:7607235163').",
                "required": True,
            }
        ],
    },
    {
        "name": "compare_sessions",
        "description": "Returns the content of multiple sessions side-by-side for comparison.",
        "arguments": [
            {
                "name": "session_ids",
                "description": "List of session IDs (comma-separated string, e.g. 'telegram:123,external:abc').",
                "required": True,
            }
        ],
    },
]


# ── Tool Dispatcher ───────────────────────────────────────────────────


async def call_tool(name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """Dispatch a tool call to the Seeker implementation.

    Returns list of content blocks (MCP format).
    Raises ValueError on unknown tool.
    """
    log.info(f"[mcp_tool] call: {name}({_summarize_args(arguments)})")
    start = time.time()

    try:
        if name == "read_file":
            content = await _tool_read_file(arguments["path"])
        elif name == "write_file":
            content = await _tool_write_file(arguments["path"], arguments["content"])
        elif name == "patch_file":
            content = await _tool_patch_file(
                arguments["path"], arguments["target"], arguments["replacement"]
            )
        elif name == "execute_command":
            content = await _tool_execute_command(
                arguments["command"],
                int(arguments.get("timeout", 45)),
            )
        elif name == "execute_code":
            content = await _tool_execute_code(
                arguments["code"],
                int(arguments.get("timeout", 30)),
            )
        elif name == "read_session":
            content = await _tool_read_session(
                arguments["session_id"],
                int(arguments.get("limit", 20)),
            )
        elif name == "record_session_turn":
            content = await _tool_record_session_turn(
                arguments["session_id"],
                arguments["role"],
                arguments["content"],
                arguments.get("metadata") or {},
            )
        else:
            raise ValueError(f"Unknown tool: {name!r}")
    except KeyError as ke:
        raise ValueError(f"Missing required argument: {ke}")

    elapsed = time.time() - start
    log.info(f"[mcp_tool] done: {name} in {elapsed:.2f}s")

    # MCP format: list of content blocks
    return [{"type": "text", "text": content}]


def _summarize_args(args: dict[str, Any]) -> str:
    """Compact representation of args for logging."""
    parts = []
    for k, v in args.items():
        v_str = str(v)
        if len(v_str) > 50:
            v_str = v_str[:47] + "..."
        parts.append(f"{k}={v_str!r}")
    return ", ".join(parts)


# ── Tool Implementations ──────────────────────────────────────────────


async def _tool_read_file(path: str) -> str:
    from src.core.execution.registry import execute_read_file
    return await execute_read_file(path)


async def _tool_write_file(path: str, content: str) -> str:
    from src.core.execution.registry import execute_write_file
    return await execute_write_file(path, content)


async def _tool_patch_file(path: str, target: str, replacement: str) -> str:
    from src.core.execution.registry import execute_patch_file
    # A função espera response_text com [TARGET]...[/TARGET][REPLACEMENT]...[/REPLACEMENT]
    response_text = (
        f"[TARGET]{target}[/TARGET]"
        f"[REPLACEMENT]{replacement}[/REPLACEMENT]"
    )
    return await execute_patch_file(response_text, path)


async def _tool_execute_command(command: str, timeout: int) -> str:
    """Wrapper que respeita timeout customizado (registry usa 45s fixo)."""
    import asyncio
    from src.core.execution.registry import execute_terminal_command

    # Executa com timeout customizado via asyncio.wait_for
    try:
        return await asyncio.wait_for(
            execute_terminal_command(command), timeout=timeout
        )
    except asyncio.TimeoutError:
        return f"[ERRO: Comando atingiu timeout de {timeout}s]"


async def _tool_execute_code(code: str, timeout: int) -> str:
    from src.core.execution.sandbox import execute_in_sandbox
    return await execute_in_sandbox(code, timeout=timeout)


async def _tool_read_session(session_id: str, limit: int) -> str:
    """Lê últimos N turnos de uma sessão."""
    try:
        from src.core.memory.session_store import SessionStore
    except ImportError as e:
        return f"[ERRO: session_store indisponível: {e}]"

    store = SessionStore()  # usa path default
    try:
        await store.init()
        turns = await store.get_session_turns(session_id, limit=limit)
    except Exception as e:
        return f"[ERRO ao ler sessão: {e}]"

    if not turns:
        return f"(Sessão '{session_id}' vazia ou inexistente)"

    # Formata como texto human-readable
    lines = [f"# Sessão: {session_id}", f"(últimos {len(turns)} turnos)", ""]
    for t in turns:
        ts = t.get("timestamp", 0)
        ts_str = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
            if ts else "?"
        )
        role = t.get("role", "?")
        content = t.get("content", "")
        lines.append(f"[{ts_str}] {role}:")
        lines.append(content)
        lines.append("")

    return "\n".join(lines)


async def _tool_record_session_turn(
    session_id: str, role: str, content: str, metadata: dict[str, Any]
) -> str:
    """Grava novo turno em uma sessão."""
    try:
        from src.core.memory.session_store import SessionStore
    except ImportError as e:
        return f"[ERRO: session_store indisponível: {e}]"

    if role not in ("user", "assistant"):
        return f"[ERRO: role deve ser 'user' ou 'assistant', recebi: {role!r}]"

    store = SessionStore()
    try:
        await store.init()
        turn_id = await store.record_session_turn(
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata,
        )
    except Exception as e:
        return f"[ERRO ao gravar turno: {e}]"

    return f"Turno gravado: id={turn_id}, session={session_id}, role={role}"


# ── Resource Dispatcher ───────────────────────────────────────────────


async def read_resource(uri: str) -> list[dict[str, Any]]:
    """Read a resource by URI.

    Returns list of content blocks.
    """
    if not uri.startswith("session://"):
        raise ValueError(f"Unknown resource URI scheme: {uri!r}")

    session_id = uri[len("session://"):]
    if not session_id:
        raise ValueError("session URI missing session_id")

    text = await _tool_read_session(session_id, limit=20)
    return [{"type": "text", "text": text, "mimeType": "application/json"}]


# ── Prompt Dispatcher ─────────────────────────────────────────────────


async def get_prompt(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get a prompt by name with arguments.

    Returns MCP GetPromptResult with messages.
    """
    if name == "summarize_session":
        session_id = arguments.get("session_id")
        if not session_id:
            raise ValueError("summarize_session requires 'session_id'")
        turns_text = await _tool_read_session(session_id, limit=100)
        user_msg = (
            f"Please summarize the following Seeker session, extracting "
            f"key facts, decisions, and open questions:\n\n{turns_text}"
        )
        return {
            "messages": [
                {"role": "user", "content": {"type": "text", "text": user_msg}}
            ]
        }

    if name == "compare_sessions":
        ids_str = arguments.get("session_ids", "")
        ids = [s.strip() for s in ids_str.split(",") if s.strip()]
        if not ids:
            raise ValueError("compare_sessions requires non-empty 'session_ids'")
        sections = []
        for sid in ids:
            turns = await _tool_read_session(sid, limit=50)
            sections.append(f"--- SESSION {sid} ---\n{turns}\n")
        user_msg = (
            f"Please compare the following {len(ids)} Seeker sessions, "
            f"highlighting common themes and divergences:\n\n"
            + "\n".join(sections)
        )
        return {
            "messages": [
                {"role": "user", "content": {"type": "text", "text": user_msg}}
            ]
        }

    raise ValueError(f"Unknown prompt: {name!r}")
