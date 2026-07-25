"""
core.execution.mcp_client — Cliente MCP (Model Context Protocol) leve.

Carrega servidores MCP de config/mcp_servers.json, conecta via stdio transport
e expõe API para listar/invocar tools.

Suporta:
  - stdio transport (subprocesso com JSON-RPC via stdin/stdout)
  - auto-connect em background no boot
  - cache de tools por servidor
  - substituição de env (${VAR_NAME} -> os.environ)

Uso:
    from src.core.execution.mcp_client import MCPClient

    client = MCPClient.get()
    await client.connect_all()

    servers = await client.list_servers()
    tools = await client.list_tools("filesystem")
    result = await client.call_tool("filesystem", "read_file", {"path": "/tmp/x"})
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("seeker.execution.mcp_client")


# ── Paths ──────────────────────────────────────────────────────────────


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _config_path() -> Path:
    """Path do config mcp_servers.json — usa data/ se gravável, senão config/."""
    custom = os.getenv("MCP_SERVERS_CONFIG")
    if custom:
        return Path(custom)
    return _project_root() / "config" / "mcp_servers.json"


# ── Models ─────────────────────────────────────────────────────────────


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPConnection:
    server_name: str
    config: MCPServerConfig
    session: Any = None          # mcp.ClientSession
    transport: Any = None        # stdio transport
    tools: list[MCPToolInfo] = field(default_factory=list)
    connected_at: float = 0.0
    error: str = ""


# ── Env substitution ───────────────────────────────────────────────────


_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _expand_env(value: str) -> str:
    """Substitui ${VAR} por os.environ.get(VAR, '')."""

    def repl(match: re.Match) -> str:
        var_name = match.group(1)
        val = os.environ.get(var_name, "")
        return val
    return _ENV_VAR_RE.sub(repl, value)


def _expand_env_dict(env: dict[str, str]) -> dict[str, str]:
    """Expande ${VAR} em todas as chaves e valores."""
    out = {}
    for k, v in env.items():
        out[_expand_env(k)] = _expand_env(v)
    return out


# ── MCP Client ─────────────────────────────────────────────────────────


class MCPClient:
    """Cliente MCP singleton para o Seeker.

    Mantém conexões stdio abertas por servidor, com auto-reconnect em falha.
    Thread-safe via asyncio.Lock.
    """

    _instance: "MCPClient | None" = None

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or _config_path()
        self.connections: dict[str, MCPConnection] = {}
        self._exit_stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()
        self._initialized = False
        self._tool_timeout = 120.0  # 2 min default

    @classmethod
    def get(cls, config_path: Path | None = None) -> "MCPClient":
        if cls._instance is None:
            cls._instance = cls(config_path)
        return cls._instance

    # ── Lifecycle ───────────────────────────────────────────────────

    async def connect_all(self) -> dict[str, str]:
        """Conecta a todos os servidores do config.

        Returns dict {server_name: status} onde status é "connected" ou mensagem de erro.
        Não levanta exceção em falha — segue fail-open.
        """
        async with self._lock:
            if self._exit_stack is None:
                self._exit_stack = AsyncExitStack()
            self._initialized = True

        configs = self._load_config()
        if not configs:
            log.warning(f"[mcp] Nenhum servidor em {self.config_path}")
            return {}

        results: dict[str, str] = {}
        for cfg in configs:
            try:
                await self._connect_one(cfg)
                results[cfg.name] = "connected"
                log.info(
                    f"[mcp] Conectado a '{cfg.name}' "
                    f"({len(self.connections[cfg.name].tools)} tools)"
                )
            except Exception as e:
                results[cfg.name] = f"error: {e}"
                log.warning(f"[mcp] Falha ao conectar '{cfg.name}': {e}")
        return results

    async def disconnect_all(self) -> None:
        """Encerra todas as conexões."""
        async with self._lock:
            if self._exit_stack is not None:
                try:
                    await self._exit_stack.aclose()
                except Exception as e:
                    log.debug(f"[mcp] Erro no shutdown: {e}")
                self._exit_stack = None
            self.connections.clear()

    async def reconnect(self, server_name: str | None = None) -> dict[str, str]:
        """Reconecta um servidor (ou todos se None)."""
        if server_name:
            old = self.connections.get(server_name)
            if old:
                await self._disconnect_one(server_name)

        configs = self._load_config()
        if server_name:
            configs = [c for c in configs if c.name == server_name]

        results: dict[str, str] = {}
        for cfg in configs:
            try:
                await self._connect_one(cfg)
                results[cfg.name] = "connected"
            except Exception as e:
                results[cfg.name] = f"error: {e}"
        return results

    # ── API pública ──────────────────────────────────────────────────

    async def list_servers(self) -> list[dict[str, Any]]:
        """Lista servidores configurados e seu status."""
        out: list[dict[str, Any]] = []
        for name, conn in self.connections.items():
            out.append({
                "name": name,
                "command": conn.config.command,
                "args": conn.config.args,
                "connected": conn.session is not None,
                "tool_count": len(conn.tools),
                "tools": [t.name for t in conn.tools],
                "connected_at": conn.connected_at,
                "error": conn.error,
            })
        # Inclui servidores do config que falharam ao conectar
        configured = {c.name for c in self._load_config()}
        connected_names = set(self.connections.keys())
        for name in configured - connected_names:
            out.append({
                "name": name,
                "connected": False,
                "tool_count": 0,
                "tools": [],
                "error": "not connected (veja logs)",
            })
        return out

    async def list_tools(self, server_name: str) -> list[MCPToolInfo]:
        """Retorna tools disponíveis em um servidor."""
        conn = self.connections.get(server_name)
        if not conn:
            raise ValueError(f"Servidor MCP '{server_name}' não está conectado")
        return list(conn.tools)

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Invoca uma tool MCP e retorna o resultado como string."""
        conn = self.connections.get(server_name)
        if not conn or not conn.session:
            raise ValueError(f"Servidor MCP '{server_name}' não está conectado")
        if arguments is None:
            arguments = {}

        # Valida que a tool existe
        tool_names = {t.name for t in conn.tools}
        if tool_name not in tool_names:
            raise ValueError(
                f"Tool '{tool_name}' não existe no servidor '{server_name}'. "
                f"Disponíveis: {sorted(tool_names)}"
            )

        timeout = timeout or self._tool_timeout
        log.info(
            f"[mcp] {server_name}.{tool_name}({json.dumps(arguments)[:200]}) "
            f"timeout={timeout}s"
        )

        try:
            result = await asyncio.wait_for(
                conn.session.call_tool(tool_name, arguments),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"MCP call '{server_name}.{tool_name}' excedeu {timeout}s"
            )

        # Formata resultado (pode ser texto, ou lista de content blocks)
        return self._format_tool_result(result)

    # ── Internals ────────────────────────────────────────────────────

    def _load_config(self) -> list[MCPServerConfig]:
        """Lê config/mcp_servers.json e retorna lista de MCPServerConfig."""
        if not self.config_path.exists():
            log.info(f"[mcp] {self.config_path} não existe — sem servidores")
            return []
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            log.error(f"[mcp] Falha ao ler {self.config_path}: {e}")
            return []

        servers_raw = raw.get("mcpServers", {})
        configs: list[MCPServerConfig] = []
        for name, conf in servers_raw.items():
            # Ignora chaves de comentário (_comment)
            if name.startswith("_") or not isinstance(conf, dict):
                continue
            command = conf.get("command")
            if not command:
                log.warning(f"[mcp] Servidor '{name}' sem 'command' — pulando")
                continue
            configs.append(MCPServerConfig(
                name=name,
                command=_expand_env(command),
                args=[_expand_env(a) for a in conf.get("args", [])],
                env=_expand_env_dict(conf.get("env", {})),
            ))
        return configs

    async def _connect_one(self, cfg: MCPServerConfig) -> None:
        """Conecta a um servidor MCP via stdio transport."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        # Verifica que o command existe
        cmd_path = shutil.which(cfg.command)
        if not cmd_path:
            raise FileNotFoundError(
                f"Command '{cfg.command}' não encontrado no PATH. "
                f"Instale ou configure caminho absoluto."
            )

        # Monta env final = env do server + env do processo
        full_env = dict(os.environ)
        full_env.update(cfg.env)

        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=full_env,
        )

        # Cria stdio_client (entra no contexto AsyncExitStack)
        assert self._exit_stack is not None
        transport = await self._exit_stack.enter_async_context(
            stdio_client(params)
        )
        read_stream, write_stream = transport

        # Cria session
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        # Lista tools
        tools_result = await session.list_tools()
        tool_infos: list[MCPToolInfo] = []
        for tool in tools_result.tools:
            schema = tool.inputSchema or {}
            if hasattr(schema, "model_dump"):
                schema = schema.model_dump()
            tool_infos.append(MCPToolInfo(
                name=tool.name,
                description=tool.description or "",
                input_schema=schema,
            ))

        # Substitui conexão existente
        if cfg.name in self.connections:
            await self._disconnect_one(cfg.name)

        import time
        self.connections[cfg.name] = MCPConnection(
            server_name=cfg.name,
            config=cfg,
            session=session,
            transport=transport,
            tools=tool_infos,
            connected_at=time.time(),
        )

    async def _disconnect_one(self, server_name: str) -> None:
        """Desconecta um servidor específico. Não fecha o exit_stack inteiro."""
        conn = self.connections.pop(server_name, None)
        if conn and conn.session:
            try:
                # AsyncExitStack vai fechar quando disconnect_all rodar
                pass
            except Exception:
                pass

    def _format_tool_result(self, result: Any) -> str:
        """Formata o resultado de uma tool MCP em string."""
        # Content blocks (text/image/resource)
        if hasattr(result, "content") and result.content:
            parts: list[str] = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                elif hasattr(block, "data"):
                    parts.append(f"[binary data: {len(block.data)} bytes]")
                elif hasattr(block, "uri"):
                    parts.append(f"[resource: {block.uri}]")
                else:
                    parts.append(str(block))
            return "\n".join(parts) if parts else "(vazio)"

        # Fallback: str() do resultado
        return str(result)


# ── Helper: smoke test ─────────────────────────────────────────────────


async def smoke_test(server_name: str = "filesystem") -> None:
    """Smoke test rápido: conecta, lista tools, executa 1 tool."""
    client = MCPClient.get()
    results = await client.connect_all()
    print(f"[smoke] connect_all results: {results}")

    if server_name not in client.connections:
        print(f"[smoke] Servidor '{server_name}' não conectou")
        return

    tools = await client.list_tools(server_name)
    print(f"[smoke] {server_name} tem {len(tools)} tools:")
    for t in tools[:5]:
        print(f"  - {t.name}: {t.description[:80]}")

    await client.disconnect_all()
