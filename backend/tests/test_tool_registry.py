import os
import tempfile
import pytest

from app.mcp.tool_registry import ToolRegistry, ToolDefinition, ShellCommandAllowlist


@pytest.fixture
def registry():
    return ToolRegistry()


class TestToolRegistry:
    def test_register_and_get(self, registry):
        tool = ToolDefinition(id="test", name="Test", description="A test tool")
        registry.register(tool)
        assert registry.get("test") == tool

    def test_register_duplicate_raises(self, registry):
        tool = ToolDefinition(id="test", name="Test", description="A test tool")
        registry.register(tool)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(tool)

    def test_list_builtins(self, registry):
        tools = registry.list_tools()
        ids = [t.id for t in tools]
        assert "shell" in ids
        assert "file_read" in ids
        assert "file_write" in ids
        assert "file_list" in ids

    def test_get_unknown_returns_none(self, registry):
        assert registry.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, registry):
        result = await registry.execute("nonexistent", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_execute_shell_ls(self, registry):
        result = await registry.execute("shell", {"command": "ls"})
        assert "result" in result
        assert "returncode" in result["result"]

    @pytest.mark.asyncio
    async def test_execute_shell_blocked_command(self, registry):
        result = await registry.execute("shell", {"command": "rm -rf /"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_execute_file_read(self, registry):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("hello world")
            f.flush()
            fpath = f.name
        try:
            result = await registry.execute("file_read", {"path": fpath})
            assert result["result"] == "hello world"
        finally:
            os.unlink(fpath)

    @pytest.mark.asyncio
    async def test_execute_file_read_not_found(self, registry):
        result = await registry.execute("file_read", {"path": "/tmp/nonexistent_file_xyz"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_execute_file_write(self, registry):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.txt")
            result = await registry.execute("file_write", {"path": path, "content": "test content"})
            assert result["result"]["path"] == path
            assert result["result"]["size"] == 12
            with open(path) as f:
                assert f.read() == "test content"

    @pytest.mark.asyncio
    async def test_execute_file_list(self, registry):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "a.txt"), "w").close()
            open(os.path.join(tmpdir, "b.txt"), "w").close()
            result = await registry.execute("file_list", {"path": tmpdir})
            names = [e["name"] for e in result["result"]]
            assert "a.txt" in names
            assert "b.txt" in names

    def test_shell_allowlist_contains_common_commands(self):
        assert "ls" in ShellCommandAllowlist
        assert "cat" in ShellCommandAllowlist
        assert "echo" in ShellCommandAllowlist
        assert "git" in ShellCommandAllowlist
        assert "rm" not in ShellCommandAllowlist
        assert "sudo" not in ShellCommandAllowlist

    @pytest.mark.asyncio
    async def test_custom_handler(self, registry):
        def my_handler(greeting: str) -> str:
            return f"{greeting}, world!"

        tool = ToolDefinition(
            id="greet",
            name="Greet",
            description="Greets the world",
            handler=my_handler,
            schema={"properties": {"greeting": {"type": "string"}}},
        )
        registry.register(tool)
        result = await registry.execute("greet", {"greeting": "Hello"})
        assert result["result"] == "Hello, world!"
