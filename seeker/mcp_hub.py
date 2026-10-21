"""Cliente MCP. Ferramenta de leitura segue. O resto para e pede licença."""

from __future__ import annotations

import asyncio
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from seeker.skills.contract import Catalog, Skill, SkillError

READ_PREFIXES = ("get", "list", "search", "read", "find", "fetch")


@dataclass
class McpServer:
    name: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    url: str = ""


@dataclass
class McpReport:
    name: str
    ok: bool
    tools: int
    error: str = ""


def load_servers(path: Path) -> list[McpServer]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = []
    for item in data.get("servers") or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        env = item.get("env")
        servers.append(
            McpServer(
                name=name,
                command=str(item.get("command") or ""),
                args=tuple(str(arg) for arg in item.get("args") or []),
                env=dict(env) if isinstance(env, dict) else None,
                url=str(item.get("url") or ""),
            )
        )
    return servers


def needs_approval(tool) -> bool:
    if _flag(tool, "destructiveHint", "destructive_hint"):
        return True
    if _flag(tool, "readOnlyHint", "read_only_hint") is True:
        return False
    name = str(getattr(tool, "name", "")).casefold().replace("-", "_")
    if any(name.startswith(prefix) or f"_{prefix}" in name for prefix in READ_PREFIXES):
        return False
    return True


def server_prefix(server: str) -> str:
    clean = re.sub(r"\W+", "_", server).strip("_") or "server"
    return f"mcp_{clean}_"


def skill_name(server: str, tool: str) -> str:
    clean = re.sub(r"\W+", "_", tool).strip("_") or "tool"
    return (server_prefix(server) + clean)[:64]


def parse_servers(arguments: dict) -> list[McpServer]:
    raw = arguments.get("config")
    data: object = raw if raw not in (None, "") else arguments
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
    if not isinstance(data, dict):
        return []
    if "mcpServers" in data and isinstance(data["mcpServers"], dict):
        specs = []
        for name, item in data["mcpServers"].items():
            if isinstance(item, dict):
                specs.extend(_specs_from({**item, "name": name}))
        return specs
    if "servers" in data and isinstance(data["servers"], list):
        specs = []
        for item in data["servers"]:
            if isinstance(item, dict):
                specs.extend(_specs_from(item))
        return specs
    return _specs_from(data)


def upsert_server(path: Path, spec: McpServer) -> None:
    current = []
    if path.exists():
        try:
            current = load_servers(path)
        except json.JSONDecodeError:
            current = []
    current = [item for item in current if item.name != spec.name]
    current.append(spec)
    path.write_text(json.dumps({"servers": [_as_dict(item) for item in current]}, ensure_ascii=False, indent=2), encoding="utf-8")


def describe_server(spec: McpServer) -> str:
    if spec.url:
        head = f"Conectar MCP {spec.name} em {spec.url}"
    else:
        head = f"Conectar MCP {spec.name}: {spec.command} {' '.join(spec.args)}".strip()
    if spec.env:
        head += "\nVariáveis: " + ", ".join(sorted(spec.env))
    return head


def configure_mcp_skill(hub, catalog: Catalog, path: Path) -> Skill:
    def run(arguments: dict) -> str:
        specs = parse_servers(arguments)
        if not specs:
            return "Não entendi o servidor. Mande o nome e o command, a url, ou o JSON do MCP."
        lines = []
        for spec in specs:
            upsert_server(path, spec)
            catalog.drop_prefix(server_prefix(spec.name))
            report = hub.connect_one(spec, catalog)
            if report.ok:
                names = [name for name in catalog._skills if name.startswith(server_prefix(spec.name))]
                listed = ", ".join(names) if names else "nenhuma ferramenta"
                lines.append(f"{spec.name} conectado. {report.tools} ferramentas: {listed}")
            else:
                lines.append(f"{spec.name} não conectou: {report.error}")
        return "\n".join(lines)

    return Skill(
        name="configure_mcp",
        when=(
            "Grava um servidor MCP no mcp.json, conecta e lista as ferramentas. "
            "Use quando a pessoa colar um comando, uma URL ou um JSON de configuração MCP."
        ),
        risk="altera",
        needs_approval=True,
        parameters={
            "type": "object",
            "properties": {
                "config": {
                    "type": "string",
                    "description": "JSON do servidor, no formato mcp.json ou mcpServers, ou um objeto com name, command, args e url.",
                },
                "name": {"type": "string"},
                "command": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
                "url": {"type": "string"},
            },
        },
        run=run,
    )


def format_call_result(result) -> str:
    if getattr(result, "is_error", False):
        text = _content_text(result) or "A ferramenta MCP falhou."
        return text[:8000]
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False)[:8000]
    return (_content_text(result) or "A ferramenta não devolveu texto.")[:8000]


def tool_skill(server: str, tool, call) -> Skill:
    remote = str(tool.name)
    description = str(getattr(tool, "description", "") or "").strip()
    when = description if len(description) >= 20 else f"Ferramenta MCP {server}/{remote}. {description}".strip()
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {
        "type": "object",
        "properties": {},
    }
    approval = needs_approval(tool)

    def run(arguments: dict) -> str:
        try:
            result = call(remote, arguments)
        except Exception as exc:
            return f"A ferramenta MCP falhou: {exc}"[:500]
        return format_call_result(result)

    return Skill(
        name=skill_name(server, remote),
        when=when,
        risk="altera" if approval else "leitura",
        needs_approval=approval,
        parameters=schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
        run=run,
    )


def register_tools(catalog: Catalog, server: str, tools, call) -> int:
    added = 0
    for tool in tools:
        try:
            catalog.add(tool_skill(server, tool, call))
        except SkillError:
            continue
        added += 1
    return added


class McpHub:
    def __init__(self):
        self.reports: list[McpReport] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._clients: list = []
        self._by_name: dict[str, object] = {}

    def status(self) -> list[dict]:
        return [
            {"name": item.name, "ok": item.ok, "tools": item.tools, "error": item.error}
            for item in self.reports
        ]

    def start(self, path: Path, catalog: Catalog) -> None:
        specs = []
        try:
            specs = load_servers(path)
        except json.JSONDecodeError:
            self.reports = [McpReport("mcp.json", False, 0, "Arquivo mcp.json inválido.")]
            return
        if not specs:
            return
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(self._connect_all(specs, catalog), self._loop)
        try:
            future.result(timeout=40)
        except Exception as exc:
            self.reports.append(McpReport("mcp", False, 0, str(exc)[:200]))

    def stop(self) -> None:
        loop = self._loop
        if loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(self._close_all(), loop)
        try:
            future.result(timeout=5)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)

    def connect_one(self, spec: McpServer, catalog: Catalog) -> McpReport:
        self._ensure_loop()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(self._connect_one(spec, catalog), self._loop)
        return future.result(timeout=40)

    def _ensure_loop(self) -> None:
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="seeker-mcp", daemon=True)
        self._thread.start()

    async def _connect_all(self, specs: list[McpServer], catalog: Catalog) -> None:
        for spec in specs:
            await self._connect_one(spec, catalog)

    async def _connect_one(self, spec: McpServer, catalog: Catalog) -> McpReport:
        catalog.drop_prefix(server_prefix(spec.name))
        old = self._by_name.pop(spec.name, None)
        if old is not None:
            await self._close_client(old)
        try:
            client = await self._open(spec)
            self._clients.append(client)
            self._by_name[spec.name] = client
            tools = await _list_all(client)
            count = register_tools(catalog, spec.name, tools, _caller(self._loop, client))
            report = McpReport(spec.name, True, count)
        except Exception as exc:
            report = McpReport(spec.name, False, 0, str(exc)[:200])
        self._set_report(report)
        return report

    async def _open(self, spec: McpServer):
        try:
            from mcp import Client, StdioServerParameters
        except ImportError as exc:
            raise RuntimeError("Instale o pacote mcp para conectar servidores.") from exc
        if spec.url:
            target = spec.url
        elif spec.command:
            target = StdioServerParameters(command=spec.command, args=list(spec.args), env=spec.env)
        else:
            raise RuntimeError(f"{spec.name} precisa de url ou command.")
        client = Client(target)
        await client.__aenter__()
        return client

    async def _close_all(self) -> None:
        for client in list(self._clients):
            await self._close_client(client)
        self._clients.clear()
        self._by_name.clear()

    async def _close_client(self, client) -> None:
        try:
            await client.__aexit__(None, None, None)
        except Exception:
            pass
        if client in self._clients:
            self._clients.remove(client)

    def _set_report(self, report: McpReport) -> None:
        self.reports = [item for item in self.reports if item.name != report.name]
        self.reports.append(report)


def _specs_from(data: dict) -> list[McpServer]:
    name = str(data.get("name") or "").strip()
    command = str(data.get("command") or "").strip()
    url = str(data.get("url") or "").strip()
    args = tuple(str(arg) for arg in data.get("args") or [])
    env = data.get("env") if isinstance(data.get("env"), dict) else None
    if not name or not (command or url):
        return []
    return [McpServer(name=name, command=command, args=args, env=dict(env) if env else None, url=url)]


def _as_dict(spec: McpServer) -> dict:
    item: dict = {"name": spec.name}
    if spec.url:
        item["url"] = spec.url
    if spec.command:
        item["command"] = spec.command
    if spec.args:
        item["args"] = list(spec.args)
    if spec.env:
        item["env"] = spec.env
    return item


def _caller(loop: asyncio.AbstractEventLoop | None, client):
    def call(name: str, arguments: dict):
        if loop is None:
            raise RuntimeError("MCP parado.")
        future = asyncio.run_coroutine_threadsafe(client.call_tool(name, arguments), loop)
        return future.result(timeout=60)

    return call


async def _list_all(client) -> list:
    tools = []
    cursor = None
    while True:
        page = await client.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = getattr(page, "next_cursor", None)
        if not cursor:
            return tools


def _flag(tool, camel: str, snake: str):
    annotations = getattr(tool, "annotations", None)
    if annotations is None:
        return None
    if isinstance(annotations, dict):
        if camel in annotations:
            return annotations[camel]
        return annotations.get(snake)
    if hasattr(annotations, snake):
        return getattr(annotations, snake)
    return getattr(annotations, camel, None)


def _content_text(result) -> str:
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    return "\n".join(parts).strip()
