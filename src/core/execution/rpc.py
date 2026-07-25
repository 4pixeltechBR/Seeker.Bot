import logging
from aiohttp import web
from src.core.execution.registry import (
    execute_read_file,
    execute_write_file,
    execute_patch_file,
    execute_terminal_command,
)
from src.core.execution.sandbox import execute_in_sandbox

log = logging.getLogger("seeker.execution.rpc")

class RPCServer:
    def __init__(self, host: str = "127.0.0.1", port: int = None):
        if port is None:
            import os
            try:
                port = int(os.getenv("RPC_PORT", "8000"))
            except ValueError:
                port = 8000
        self.host = host
        self.port = port
        self.app = web.Application()
        self.app.router.add_post("/rpc", self.handle_rpc)

        # MCP server routes (v3.11) — expõe tools do Seeker para clientes MCP
        # externos (opencode, Claude Desktop). Auth via Bearer (loopback bypass).
        try:
            from src.core.execution import mcp_server
            mcp_server.register_routes(self.app)
            log.info("[rpc] MCP server routes registradas (POST /mcp, GET /mcp/sse)")
        except ImportError as ie:
            log.warning(f"[rpc] MCP server NÃO registrado (import falhou): {ie}")

        self.runner = None

    async def handle_rpc(self, request: web.Request) -> web.Response:
        # Segurança: permite apenas conexões de loopback local
        client_ip = request.remote
        if client_ip not in ("127.0.0.1", "::1", "localhost"):
            log.warning(f"[rpc] Acesso bloqueado de IP não autorizado: {client_ip}")
            return web.json_response({"error": "Forbidden: Localhost only"}, status=403)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        method = data.get("method")
        params = data.get("params", {})

        if not method:
            return web.json_response({"error": "Missing method"}, status=400)

        log.info(f"[rpc] Chamada RPC recebida: method={method}")
        result = None
        error = None

        try:
            if method == "read_file":
                path = params.get("path")
                if not path:
                    error = "Missing 'path' parameter"
                else:
                    result = await execute_read_file(path)
            elif method == "write_file":
                path = params.get("path")
                content = params.get("content")
                if not path or content is None:
                    error = "Missing 'path' or 'content' parameter"
                else:
                    result = await execute_write_file(path, content)
            elif method == "patch_file":
                patch_data = params.get("patch_data")
                path = params.get("path")
                if not patch_data or not path:
                    error = "Missing 'patch_data' or 'path' parameter"
                else:
                    result = await execute_patch_file(patch_data, path)
            elif method == "execute_command":
                command = params.get("command")
                if not command:
                    error = "Missing 'command' parameter"
                else:
                    result = await execute_terminal_command(command)
            elif method == "execute_code":
                code = params.get("code")
                if not code:
                    error = "Missing 'code' parameter"
                else:
                    result = await execute_in_sandbox(code)
            else:
                error = f"Unknown method: {method}"
        except Exception as e:
            error = f"Execution error: {str(e)}"
            log.error(f"[rpc] Erro ao executar método {method}: {e}", exc_info=True)

        if error:
            return web.json_response({"error": error}, status=400)

        return web.json_response({"result": result})

    async def start(self) -> None:
        """Inicia o servidor RPC em background.

        Robusto contra porta ocupada: se a porta configurada estiver em uso
        (típico quando o bot foi morto sem cleanup ou há instância órfã),
        tenta portas adjacentes (port+1, port+2, ...) até achar uma livre.
        Se nenhuma porta livre for encontrada nas próximas 10 tentativas,
        loga warning e segue SEM RPC server (não bloqueia o bot).
        """
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        # Tenta porta configurada + 9 fallbacks
        for attempt in range(10):
            try_port = self.port + attempt
            site = web.TCPSite(self.runner, self.host, try_port)
            try:
                await site.start()
                self.port = try_port  # atualiza porta real em uso
                if attempt > 0:
                    log.warning(
                        f"[rpc] Porta {self.port - attempt} ocupada; "
                        f"RPC server subiu em fallback port {try_port}"
                    )
                log.info(f"[rpc] Servidor RPC Local ativo em http://{self.host}:{try_port}/rpc")
                return
            except OSError as e:
                # winerror 10048 / errno 98 = address already in use
                if attempt == 0:
                    log.warning(f"[rpc] Porta {try_port} ocupada ({e}); tentando fallback...")
                # tenta próxima porta
                continue

        # Nenhuma porta livre nas 10 tentativas — segue sem RPC
        log.error(
            f"[rpc] Nenhuma porta livre encontrada entre {self.port} e {self.port + 9}. "
            f"Bot seguirá SEM servidor RPC local."
        )
        try:
            await self.runner.cleanup()
        except Exception:
            pass
        self.runner = None

    async def stop(self) -> None:
        """Encerra o servidor RPC."""
        if self.runner:
            await self.runner.cleanup()
            log.info("[rpc] Servidor RPC Local encerrado.")
