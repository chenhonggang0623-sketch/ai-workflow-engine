import asyncio

from app.mcp.client import MCPClient
from app.mcp.exceptions import MCPError, MCPToolNotFoundError, MCPToolExecutionError


class ServerState:
    def __init__(self, name: str, command: str, args: list[str], env: dict | None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env
        self.client: MCPClient | None = None
        self.tools: list[dict] = []


class MCPBridge:
    def __init__(self):
        self._servers: dict[str, ServerState] = {}

    async def register_server(
        self, name: str, command: str, args: list[str] | None = None, env: dict | None = None
    ) -> None:
        if name in self._servers:
            raise ValueError(f"MCP server already registered: {name}")
        self._servers[name] = ServerState(
            name=name, command=command, args=args or [], env=env
        )

    async def start_server(self, name: str) -> None:
        state = self._get_state(name)
        if state.client and state.client.connected:
            return
        client = MCPClient(command=state.command, args=state.args, env=state.env)
        await client.connect()
        state.client = client
        tools = await client.send_request("list_tools")
        state.tools = tools if isinstance(tools, list) else []

    async def stop_server(self, name: str) -> None:
        state = self._get_state(name)
        if state.client:
            await state.client.disconnect()
            state.client = None
        state.tools = []

    async def list_tools(self) -> list[dict]:
        all_tools: list[dict] = []
        for name, state in self._servers.items():
            if state.client and state.client.connected:
                all_tools.extend(
                    {**tool, "server": name} for tool in state.tools
                )
        return all_tools

    async def call_tool(self, name: str, tool_name: str, arguments: dict) -> dict:
        state = self._get_state(name)
        if not state.client or not state.client.connected:
            raise MCPToolExecutionError(f"MCP server not running: {name}")
        try:
            result = await state.client.send_request(
                "call_tool",
                params={"name": tool_name, "arguments": arguments},
            )
            return result
        except MCPError:
            raise
        except Exception as e:
            raise MCPToolExecutionError(f"Tool execution failed: {e}") from e

    async def shutdown_all(self) -> None:
        for name in list(self._servers.keys()):
            try:
                await self.stop_server(name)
            except Exception:
                pass

    def _get_state(self, name: str) -> ServerState:
        state = self._servers.get(name)
        if not state:
            raise MCPToolNotFoundError(f"MCP server not found: {name}")
        return state
