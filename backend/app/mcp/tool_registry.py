import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Coroutine


@dataclass
class ToolDefinition:
    id: str
    name: str
    description: str
    schema: dict = field(default_factory=dict)
    handler: Callable[..., str | dict | Coroutine] | None = None


ShellCommandAllowlist = {
    "ls", "cat", "head", "tail", "wc", "echo", "pwd", "whoami",
    "date", "uname", "which", "dirname", "basename",
    "git", "npm", "node", "python3", "pip", "make",
    "curl", "wget", "grep", "find", "sort", "uniq",
}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._register_builtins()

    def register(self, tool: ToolDefinition) -> None:
        if tool.id in self._tools:
            raise ValueError(f"Tool already registered: {tool.id}")
        self._tools[tool.id] = tool

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self._tools.get(tool_id)

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    async def execute(self, tool_id: str, params: dict) -> dict:
        tool = self._tools.get(tool_id)
        if not tool:
            return {"error": f"Tool not found: {tool_id}"}

        if tool.handler is None:
            return {"error": f"Tool has no handler: {tool_id}"}

        try:
            result = tool.handler(**params)
            if hasattr(result, "__await__"):
                result = await result
            if isinstance(result, dict) and "error" in result:
                return result
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}

    def _register_builtins(self) -> None:
        self.register(ToolDefinition(
            id="shell",
            name="Shell",
            description="Execute a shell command",
            schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run"},
                },
                "required": ["command"],
            },
            handler=self._builtin_shell,
        ))
        self.register(ToolDefinition(
            id="file_read",
            name="File Read",
            description="Read file contents",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"},
                },
                "required": ["path"],
            },
            handler=self._builtin_file_read,
        ))
        self.register(ToolDefinition(
            id="file_write",
            name="File Write",
            description="Write content to a file",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
            handler=self._builtin_file_write,
        ))
        self.register(ToolDefinition(
            id="file_list",
            name="File List",
            description="List directory contents",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list"},
                },
                "required": ["path"],
            },
            handler=self._builtin_file_list,
        ))

    def _builtin_shell(self, command: str) -> dict:
        parts = command.strip().split()
        if not parts:
            return {"error": "Empty command"}
        base = parts[0]
        if base not in ShellCommandAllowlist:
            return {"error": f"Command not allowed: {base}"}
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out after 30s"}
        except Exception as e:
            return {"error": str(e)}

    def _builtin_file_read(self, path: str) -> str:
        with open(path, "r") as f:
            return f.read()

    def _builtin_file_write(self, path: str, content: str) -> dict:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return {"path": path, "size": len(content)}

    def _builtin_file_list(self, path: str) -> list[dict]:
        entries = os.listdir(path)
        result = []
        for name in sorted(entries):
            full = os.path.join(path, name)
            result.append({
                "name": name,
                "type": "directory" if os.path.isdir(full) else "file",
                "size": os.path.getsize(full) if os.path.isfile(full) else 0,
            })
        return result
