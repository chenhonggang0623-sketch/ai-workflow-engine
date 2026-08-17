import pytest

from app.skill.executor import SkillExecutor, ExecutionError


@pytest.fixture
def executor():
    return SkillExecutor()


class TestSkillExecutor:
    @pytest.mark.asyncio
    async def test_register_and_execute(self, executor):
        executor.register("add", "def add(a, b): return a + b")
        result = await executor.execute("add", {"a": 1, "b": 2})
        assert result["result"] == 3

    def test_register_and_list(self, executor):
        executor.register("add", "def add(a, b): return a + b")
        executor.register("mul", "def mul(a, b): return a * b")
        skills = executor.list()
        assert "add" in skills
        assert "mul" in skills

    def test_unregister(self, executor):
        executor.register("add", "def add(a, b): return a + b")
        executor.unregister("add")
        assert executor.list() == []

    @pytest.mark.asyncio
    async def test_unknown_skill(self, executor):
        result = await executor.execute("nonexistent", {})
        assert "error" in result

    def test_register_invalid_code(self, executor):
        with pytest.raises(ExecutionError):
            executor.register("bad", "this is not valid python @@@")

    def test_register_no_function(self, executor):
        with pytest.raises(ExecutionError, match="No function defined"):
            executor.register("no_func", "x = 42")

    @pytest.mark.asyncio
    async def test_sandbox_no_import(self, executor):
        executor.register("hacker", "def hacker(): import os; return os")
        result = await executor.execute("hacker", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_sandbox_no_file_io(self, executor):
        executor.register("hacker", "def hacker(): return open('/etc/passwd').read()")
        result = await executor.execute("hacker", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_sandbox_restricted_builtins(self, executor):
        executor.register("explore", "def explore(): return __builtins__")
        result = await executor.execute("explore", {})
        safe = result["result"]
        assert "abs" in safe
        assert "open" not in safe
        assert "__import__" not in safe
        assert "eval" not in safe
        assert "exec" not in safe

    @pytest.mark.asyncio
    async def test_execute_without_params(self, executor):
        executor.register("hello", "def hello(): return 'hello'")
        result = await executor.execute("hello", {})
        assert result["result"] == "hello"

    @pytest.mark.asyncio
    async def test_multiple_skills(self, executor):
        executor.register("add", "def add(a, b): return a + b")
        executor.register("sub", "def sub(a, b): return a - b")
        r1 = await executor.execute("add", {"a": 10, "b": 5})
        r2 = await executor.execute("sub", {"a": 10, "b": 5})
        assert r1["result"] == 15
        assert r2["result"] == 5

    @pytest.mark.asyncio
    async def test_re_register_allowed(self, executor):
        executor.register("f", "def f(): return 1")
        executor.register("f", "def f(): return 2")
        result = await executor.execute("f", {})
        assert result["result"] == 2
