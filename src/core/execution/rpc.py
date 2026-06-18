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
        """Inicia o servidor RPC em background."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        log.info(f"[rpc] Servidor RPC Local ativo em http://{self.host}:{self.port}/rpc")

    async def stop(self) -> None:
        """Encerra o servidor RPC."""
        if self.runner:
            await self.runner.cleanup()
            log.info("[rpc] Servidor RPC Local encerrado.")
