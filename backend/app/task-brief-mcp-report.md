# MCP Tool System — Implementation Report

## Status: DONE

## Files Created

| File | Description |
|------|-------------|
| `app/mcp/__init__.py` | Module exports |
| `app/mcp/exceptions.py` | MCP error hierarchy (MCPError, MCPTimeoutError, MCPConnectionError, MCPToolNotFoundError, MCPToolExecutionError) |
| `app/mcp/client.py` | `MCPClient` — low-level JSON-RPC 2.0 over asyncio subprocess stdio pipes |
| `app/mcp/bridge.py` | `MCPBridge` — manages MCP server lifecycle (register, start, stop, list_tools, call_tool) |
| `app/mcp/tool_registry.py` | `ToolRegistry` + `ToolDefinition` — central registry with 4 built-in tools (shell, file_read, file_write, file_list) |
| `app/skill/__init__.py` | Module exports |
| `app/skill/executor.py` | `SkillExecutor` — dynamic Python code execution with restricted builtins sandbox |
| `tests/test_tool_registry.py` | 13 tests for ToolRegistry (registration, builtins, shell allowlist, file ops, custom handlers) |
| `tests/test_skill_executor.py` | 12 tests for SkillExecutor (register, execute, list, unregister, sandbox, re-register) |

## Key Implementation Details

### MCPClient (`app/mcp/client.py`)
- Async subprocess with stdin/stdout pipes
- JSON-RPC 2.0 request/response with incremental IDs
- Background `_read_loop` dispatches responses to pending futures by ID
- Configurable connect/request timeouts (default 60s)
- Clean disconnect: cancels read task, kills process, drains pending futures

### MCPBridge (`app/mcp/bridge.py`)
- Maps server names to `ServerState` (command, args, env, client, tool list)
- `start_server` spawns an MCPClient and calls `list_tools` to cache available tools
- `list_tools` aggregates tools across all connected servers with `server` metadata
- `call_tool` delegates to the matching server via JSON-RPC

### ToolRegistry (`app/mcp/tool_registry.py`)
- Built-in tools need NO external dependencies
- Shell tool has a command allowlist (ls, cat, git, npm, etc.) — dangerous commands (rm, sudo) blocked
- Dict results with `"error"` key propagate as top-level errors (consistent across built-in and custom handlers)
- Handler supports both sync and async functions

### SkillExecutor (`app/skill/executor.py`)
- `register(skill_id, code)` → compiles code via `exec()` with restricted builtins
- Restricted builtins: basic operations only (abs, len, str, list, sorted, etc.) — no `open`, `__import__`, `eval`, `exec`
- Auto-detects the first function defined in the code snippet
- `execute` supports both sync and async handlers

## Test Results

```
25 passed in 0.03s
```

ToolRegistry: 13 tests (registration, get/list, built-in execution, shell allowlist, file ops, custom handlers, error handling)
SkillExecutor: 12 tests (register/list/unregister, execution, sandbox: no imports, no file I/O, restricted builtins, re-register)

## Concerns / Limitations (MVP)

1. **MCPBridge + MCPClient not tested end-to-end** — requires a real MCP server subprocess. Integration tests would need `mcp` package installed with a test server fixture. Only unit tests for ToolRegistry and SkillExecutor were run.
2. **Sandbox is best-effort** — `exec()` with restricted builtins is not a true sandbox. A determined attacker could bypass via `().__class__.__bases__[0].__subclasses__()`. True sandboxing would need a dedicated subprocess or container isolation.
3. **Shell allowlist is static** — defined as a module-level set. In production this should be configurable via `app/core/config.py` Settings.
4. **MCPClient has no stderr logging** — stderr from subprocess is captured but not logged. Add a reader task for stderr in production.
