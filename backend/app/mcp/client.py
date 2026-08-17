import asyncio
import json
import uuid

from app.mcp.exceptions import MCPError, MCPTimeoutError, MCPConnectionError


class MCPClient:
    def __init__(self, command: str, args: list[str] | None = None, env: dict | None = None):
        self._command = command
        self._args = args or []
        self._env = env
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._request_id = 0
        self._pending: dict[str, asyncio.Future] = {}
        self._read_task: asyncio.Task | None = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, timeout: float = 10.0) -> None:
        try:
            self._process = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    self._command,
                    *self._args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=self._env,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise MCPConnectionError(
                f"Timeout connecting to MCP server: {self._command}"
            )
        except FileNotFoundError as e:
            raise MCPConnectionError(
                f"MCP server command not found: {self._command}"
            ) from e

        self._writer = self._process.stdin
        self._reader = self._process.stdout
        self._read_task = asyncio.create_task(self._read_loop())
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None
        if self._writer:
            self._writer.close()
            self._writer = None
        if self._process and self._process.returncode is None:
            try:
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass
            self._process = None
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    async def send_request(self, method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
        if not self._connected:
            raise MCPConnectionError("Not connected to MCP server")

        self._request_id += 1
        request_id = str(self._request_id)
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        try:
            line = json.dumps(request) + "\n"
            self._writer.write(line.encode("utf-8"))
            await self._writer.drain()

            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise MCPTimeoutError(
                f"Timeout after {timeout}s for method: {method}, request_id: {request_id}"
            )
        except Exception:
            self._pending.pop(request_id, None)
            raise

    async def _read_loop(self) -> None:
        try:
            while self._connected and self._reader:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    response = json.loads(line.decode("utf-8").strip())
                except json.JSONDecodeError:
                    continue

                rid = response.get("id")
                if rid and rid in self._pending:
                    future = self._pending.pop(rid)
                    if not future.done():
                        if "error" in response:
                            future.set_exception(
                                MCPError(
                                    response["error"].get("message", "Unknown MCP error"),
                                    code=response["error"].get("code"),
                                )
                            )
                        else:
                            future.set_result(response.get("result", {}))
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            self._connected = False
