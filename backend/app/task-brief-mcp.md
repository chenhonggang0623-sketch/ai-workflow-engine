# Task: Implement MCP Tool System

## Context
MCP (Model Context Protocol) integration allows agents to use external tools. The Tool Executor, MCP Bridge, and Skill Executor modules.

## Files to create

### 1. `backend/app/mcp/bridge.py` — MCPBridge

```python
class MCPBridge:
    """
    Manages MCP tool connections and execution.
    
    Supports two modes:
    1. Local MCP servers (subprocess managed)
    2. Remote MCP servers (HTTP/SSE)
    
    - register_server(name, command, args, env) → registers an MCP server
    - list_tools() → returns all available tools across all servers
    - call_tool(server_name, tool_name, arguments) → executes tool
    - start_server(name) / stop_server(name) → lifecycle

    Uses the official `mcp` Python package (pip: mcp).
    For MVP: implement a simple version that spawns subprocesses and communicates via stdio.
    """

    def __init__(self): ...
    async def register_server(self, name: str, command: str, args: list[str] = None,
                               env: dict = None) -> None: ...
    async def list_tools(self) -> list[dict]: ...
    async def call_tool(self, name: str, tool_name: str, arguments: dict) -> dict: ...
    async def start_server(self, name: str) -> None: ...
    async def stop_server(self, name: str) -> None: ...
```

### 2. `backend/app/mcp/client.py` — MCPClient

```python
class MCPClient:
    """
    Low-level client for communicating with an MCP server process.
    - connect(): starts subprocess, establishes stdio communication
    - send_request(method, params): sends JSON-RPC request
    - receive_response(): reads JSON-RPC response
    - disconnect(): terminates process
    - Uses asyncio subprocess with timeout
    """
```

### 3. `backend/app/mcp/tool_registry.py` — ToolRegistry

```python
class ToolRegistry:
    """
    Central registry of all available tools (MCP + Built-in).
    - register(tool_id, name, description, handler, schema)
    - get(tool_id) → ToolDefinition
    - list() → list[ToolDefinition]
    - execute(tool_id, params) → result

    Built-in tools (for MVP):
    - shell: run shell commands
    - file_read: read file contents
    - file_write: write file contents
    - file_list: list directory
    """
```

### 4. `backend/app/skill/executor.py` — SkillExecutor

```python
class SkillExecutor:
    """
    Executes registered skills (Python code snippets).
    - execute(skill_id, params) → result
    - Skills are Python functions loaded dynamically from DB or filesystem
    - Sandboxed execution with restricted builtins
    """
```

## Constraints
- MCP stdio communication: subprocess with stdin/stdout asyncio pipes
- JSON-RPC 2.0 format for MCP protocol
- Tool calls must have timeout (default 60s)
- Built-in tools should NOT require external dependencies
- Safety: shell tool should have command allowlist

## Output
- Status: DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED
- Report file: `backend/app/task-brief-mcp-report.md`
- Commits made
- Test output
