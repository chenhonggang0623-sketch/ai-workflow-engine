import json
from unittest.mock import AsyncMock

import pytest

from app.planner.requirement_analyzer import RequirementAnalyzer


def make_llm(content):
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value={"content": content, "tool_calls": [], "usage": {}})
    return llm


class TestRequirementAnalyzer:
    @pytest.mark.asyncio
    async def test_llm_success_returns_structured_prd(self):
        llm = make_llm(json.dumps({
            "summary": "A todo app",
            "goals": ["Manage tasks"],
            "features": ["add task", "delete task"],
            "non_functional": ["fast"],
            "acceptance_criteria": ["can add a task"],
            "assumptions": ["single user"],
            "open_questions": ["auth needed?"],
        }))
        prd = await RequirementAnalyzer(llm).analyze("Build a todo app")
        assert prd["summary"] == "A todo app"
        assert "add task" in prd["features"]
        assert prd["acceptance_criteria"] == ["can add a task"]
        assert prd["open_questions"] == ["auth needed?"]

    @pytest.mark.asyncio
    async def test_llm_broken_json_falls_back(self):
        llm = make_llm("not json at all")
        prd = await RequirementAnalyzer(llm).analyze("Build a todo app")
        assert prd["summary"]
        assert prd["features"]
        assert prd["acceptance_criteria"]

    @pytest.mark.asyncio
    async def test_llm_missing_fields_falls_back(self):
        llm = make_llm(json.dumps({"summary": "only summary"}))
        prd = await RequirementAnalyzer(llm).analyze("Build a todo app")
        # 缺少 goals/features 时走启发式回退（以需求原文为 summary）
        assert prd["summary"] == "Build a todo app"
        assert prd["features"]
        assert prd["goals"]

    @pytest.mark.asyncio
    async def test_llm_exception_falls_back(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=Exception("LLM down"))
        prd = await RequirementAnalyzer(llm).analyze("Build a todo app")
        assert prd["summary"]
        assert prd["goals"]
        assert isinstance(prd["open_questions"], list)

    @pytest.mark.asyncio
    async def test_requirement_with_braces_is_safe(self):
        # 用户需求包含 { } 时不得破坏 prompt 渲染
        llm = make_llm(json.dumps({
            "summary": "ok", "goals": [], "features": ["f"],
            "non_functional": [], "acceptance_criteria": [],
            "assumptions": [], "open_questions": [],
        }))
        prd = await RequirementAnalyzer(llm).analyze(
            "Need braces {like_this} and {nested:{x}} in requirement"
        )
        assert prd["summary"] == "ok"
