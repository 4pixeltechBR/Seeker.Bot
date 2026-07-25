"""
core.execution.mcp_server — Handler JSON-RPC 2.0 + MCP protocol.

Implementa dois endpoints MCP no RPC server existente:

  POST /mcp           — Streamable HTTP (MCP spec moderna, 2025-03-26+)
                          Aceita JSON-RPC request, retorna JSON ou SSE response.

  GET  /mcp/sse       — Legacy SSE transport (MCP 2024-11-05)
  POST /mcp/messages  — Endpoint de mensagens do SSE legacy

Auth via Bearer token (mcp_auth.check_bearer). Loopback bypass.
Rate limit 10 req/s por IP (token bucket em mcp_auth).

NOTA: Implementação manual do protocolo MCP (JSON-RPC 2.0 sobre HTTP),
não usa `mcp.server` library para manter zero deps extras e full control
sobre o transporte (Streamable HTTP + SSE legacy).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from aiohttp import web

from src.core.execution import mcp_auth
from src.core.execution import mcp_tools

log = logging.getLogger("seeker.execution.mcp_server")

# Server identity (capabilities advertised)
SERVER_INFO = {
    "name": "seeker-bot",
    "version": "3.11.0",
}

SERVER_CAPABILITIES = {
    "tools": {},          # we provide tools
    "resources": {},      # we provide resources
    "prompts": {},        # we provide prompts
}

JSONRPC_VERSION = "2.0"


# ── JSON-RPC helpers ──────────────────────────────────────────────────


def _jsonrpc_response(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "error": err}


# MCP-specific error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32653


# ── MCP method dispatch ───────────────────────────────────────────────


async def _dispatch(method: str, params: dict[str, Any] | None) -> Any:
    """Dispatch a single MCP method call. Returns the result field."""
    params = params or {}

    if method == "initialize":
        # Client handshake
        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": SERVER_INFO,
            "capabilities": SERVER_CAPABILITIES,
        }

    if method == "ping":
        return {}

    if method == "tools/list":
        return {"tools": mcp_tools.TOOLS}

    if method == "tools/call":
        name = params.get("name")
        if not name:
            raise ValueError("'name' is required for tools/call")
        arguments = params.get("arguments") or {}
        # Returns list of content blocks
        return {
            "content": await mcp_tools.call_tool(name, arguments),
            "isError": False,
        }

    if method == "resources/list":
        return {"resources": mcp_tools.RESOURCES}

    if method == "resources/read":
        uri = params.get("uri")
        if not uri:
            raise ValueError("'uri' is required for resources/read")
        contents = await mcp_tools.read_resource(uri)
        return {"contents": contents}

    if method == "resources/templates/list":
        # Resource templates (we don't have any beyond what's in RESOURCES list)
        return {"resourceTemplates": []}

    if method == "prompts/list":
        return {"prompts": mcp_tools.PROMPTS}

    if method == "prompts/get":
        name = params.get("name")
        if not name:
            raise ValueError("'name' is required for prompts/get")
        arguments = params.get("arguments") or {}
        return await mcp_tools.get_prompt(name, arguments)

    raise ValueError(f"Method not found: {method!r}")


# ── Streamable HTTP endpoint (POST /mcp) ──────────────────────────────


async def handle_mcp_post(request: web.Request) -> web.Response:
    """POST /mcp — Streamable HTTP endpoint.

    - Aceita 1 ou mais JSON-RPC requests (batch)
    - Retorna JSON ou application/json+body SSE
    - Auth via Bearer (mcp_auth)
    """
    # Auth
    remote_ip = request.remote or "unknown"
    headers = dict(request.headers)
    allowed, reason = mcp_auth.check_bearer(headers, remote_ip)
    if not allowed:
        log.warning(f"[mcp_server] Auth FAIL from IP={remote_ip}: {reason}")
        resp = web.json_response(
            {"error": "Unauthorized", "reason": reason},
            status=401,
        )
        for k, v in mcp_auth.format_401(reason).items():
            resp.headers[k] = v
        return resp

    # Parse body
    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        return web.json_response(
            _jsonrpc_error(None, PARSE_ERROR, f"Parse error: {e}"),
            status=400,
        )

    # Handle batch or single request
    if isinstance(body, list):
        responses = []
        for req in body:
            responses.append(await _handle_single_request(req, remote_ip))
        # Filter out notifications (responses with id=None) for non-streaming
        responses = [r for r in responses if r is not None]
        if not responses:
            # All notifications → 204 No Content
            return web.Response(status=204)
        return web.json_response(responses)
    else:
        response = await _handle_single_request(body, remote_ip)
        if response is None:
            return web.Response(status=204)
        return web.json_response(response)


async def _handle_single_request(req: dict[str, Any], remote_ip: str) -> dict[str, Any] | None:
    """Process one JSON-RPC request. Returns None if it's a notification (no id)."""
    method = req.get("method")
    params = req.get("params") or {}
    req_id = req.get("id")

    if not method:
        return _jsonrpc_error(req_id, INVALID_REQUEST, "Missing 'method'")

    try:
        result = await _dispatch(method, params)
        return _jsonrpc_response(req_id, result)
    except ValueError as ve:
        # Method not found or invalid params
        if "Method not found" in str(ve):
            return _jsonrpc_error(req_id, METHOD_NOT_FOUND, str(ve))
        return _jsonrpc_error(req_id, INVALID_PARAMS, str(ve))
    except Exception as e:
        log.exception(f"[mcp_server] Internal error in {method} from IP={remote_ip}")
        return _jsonrpc_error(req_id, INTERNAL_ERROR, f"Internal error: {e}")


# ── Legacy SSE endpoint (GET /mcp/sse + POST /mcp/messages) ───────────


# Map of session_id -> asyncio.Queue for SSE responses
_sse_queues: dict[str, asyncio.Queue] = {}


async def handle_mcp_sse_get(request: web.Request) -> web.StreamResponse:
    """GET /mcp/sse — establishes SSE stream for legacy MCP transport."""
    # Auth
    remote_ip = request.remote or "unknown"
    headers = dict(request.headers)
    allowed, reason = mcp_auth.check_bearer(headers, remote_ip)
    if not allowed:
        log.warning(f"[mcp_server] SSE auth FAIL from IP={remote_ip}: {reason}")
        return web.json_response(
            {"error": "Unauthorized", "reason": reason},
            status=401,
        )

    session_id = uuid.uuid4().hex
    queue: asyncio.Queue = asyncio.Queue()
    _sse_queues[session_id] = queue

    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    log.info(f"[mcp_server] SSE stream established session={session_id} from IP={remote_ip}")

    # Send the endpoint event so client knows where to POST messages
    await response.write(
        f"event: endpoint\ndata: /mcp/messages?session_id={session_id}\n\n".encode("utf-8")
    )

    try:
        while True:
            # Wait for messages or timeout (heartbeat)
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                # Heartbeat to keep connection alive
                await response.write(b": heartbeat\n\n")
                continue
            if msg is None:  # Sentinel to close
                break
            await response.write(f"data: {json.dumps(msg)}\n\n".encode("utf-8"))
    except asyncio.CancelledError:
        log.info(f"[mcp_server] SSE stream cancelled session={session_id}")
    except Exception as e:
        log.warning(f"[mcp_server] SSE stream error session={session_id}: {e}")
    finally:
        _sse_queues.pop(session_id, None)
        log.info(f"[mcp_server] SSE stream closed session={session_id}")

    return response


async def handle_mcp_messages_post(request: web.Request) -> web.Response:
    """POST /mcp/messages?session_id=... — receives messages for SSE stream."""
    session_id = request.query.get("session_id", "")
    if not session_id or session_id not in _sse_queues:
        return web.json_response(
            {"error": "Unknown or missing session_id"}, status=404
        )

    # Auth (also required here)
    remote_ip = request.remote or "unknown"
    headers = dict(request.headers)
    allowed, reason = mcp_auth.check_bearer(headers, remote_ip)
    if not allowed:
        return web.json_response(
            {"error": "Unauthorized", "reason": reason}, status=401
        )

    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        return web.json_response({"error": f"Invalid JSON: {e}"}, status=400)

    queue = _sse_queues[session_id]

    # Process request and queue response back to SSE stream
    response = await _handle_single_request(body, remote_ip)
    if response is not None:
        await queue.put(response)
    return web.Response(status=202)  # Accepted


# aiohttp SSE response needs asyncio — import here to avoid top-level
import asyncio  # noqa: E402


# ── Register routes on existing RPC app ───────────────────────────────


def register_routes(app: web.Application) -> None:
    """Registra rotas MCP no web.Application do RPCServer."""
    app.router.add_post("/mcp", handle_mcp_post)
    app.router.add_get("/mcp/sse", handle_mcp_sse_get)
    app.router.add_post("/mcp/messages", handle_mcp_messages_post)
    log.info(
        "[mcp_server] Rotas registradas: POST /mcp, GET /mcp/sse, "
        "POST /mcp/messages"
    )
