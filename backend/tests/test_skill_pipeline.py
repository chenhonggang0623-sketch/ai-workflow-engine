"""PlannerAgent skill 集成测试：catalog 注入、skill 选择、兜底映射。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.planner.planner_agent import PlannerAgent, PLAN_PROMPT
from app.skills.registry import SkillRegistry


BLUEPRINT = {
    "prd": {"summary": "Build a blog system", "goals": [], "features": []},
    "architecture": {"tech_stack": ["python"], "data_model": [], "api_contracts": []},
    "modules": [
        {"id": "core", "name": "Core", "depends_on": [],
         "input_contract": ["requirement"], "output_contract": ["impl"]},
        {"id": "tests", "name": "Tests", "depends_on": ["core"],
         "input_contract": ["impl"], "output_contract": ["report"]},
    ],
    "constraints": ["code must be typed"],
}


def _dag_with_skill_ids(*skill_ids):
    nodes = []
    for i, sid in enumerate(skill_ids):
        is_core = i == 0
        node = {
            "id": f"agent_{i + 1}",
            "type": "agent",
            "label": f"Agent {i + 1}",
            "config": {
                "module_id": "core" if is_core else "tests",
                "role": "developer",
                "purpose": "Implement the module" if is_core else "Write tests for the module",
                "provider": "openai",
                "executor_type": "llm_api",
                "timeout_seconds": 900,
            },
            "input_mapping": (
                [{"source": "$.requirement", "target": "requirement"}]
                if is_core
                else [{"source": "$.module_core", "target": "impl"}]
            ),
            "output_mapping": [
                {"source": "impl" if is_core else "report", "target": f"$.result_{i}"}
            ],
        }
        if sid is not None:
            node["config"]["skill_id"] = sid
        nodes.append(node)
    return {"name": "Test WF", "description": "d", "nodes": nodes, "edges": [{"source": "agent_1", "target": "agent_2"}]}


def _make_llm(workflow_json: str):
    llm = AsyncMock()
    llm.chat.return_value = {"content": json.dumps(workflow_json)}
    return llm


def _planner(llm):
    reg = SkillRegistry()
    agent_registry = MagicMock()
    tool_registry = MagicMock()
    return PlannerAgent(llm, agent_registry, tool_registry, skill_registry=reg)


class TestCatalogInPrompt:
    async def test_skill_catalog_injected(self):
        llm = _make_llm(_dag_with_skill_ids("test-driven-development"))
        planner = _planner(llm)
        await planner.generate_dag(BLUEPRINT)
        user_content = llm.chat.call_args.kwargs["messages"][1]["content"]
        assert "<skill_catalog>" in user_content
        assert "test-driven-development:" in user_content
        assert "subagent-driven-development:" in user_content


class TestApplySkills:
    async def test_explicit_skill_kept_in_config_for_local_cli(self):
        """所有节点统一默认 provider（opencode_cli）→ 通道 B：skill_id 记入 config，
        正文不烙进 system_prompt（执行时由工作区注入）。"""
        llm = _make_llm(_dag_with_skill_ids("test-driven-development", "requesting-code-review"))
        workflow = await _planner(llm).generate_dag(BLUEPRINT)

        node1 = workflow["nodes"][0]
        assert node1["config"]["provider"] == "opencode_cli"
        assert node1["config"]["skill_id"] == "test-driven-development"
        assert "## 工作方法（Skill: test-driven-development）" not in (node1["config"].get("system_prompt") or "")
        assert node1["config"]["skill_version"] == "main"

    async def test_openai_node_still_defaulted_after_normalization(self):
        """即使节点声明 openai（LLM 输出），归一化后统一为默认 provider，skill 走通道 B。"""
        llm = _make_llm(_dag_with_skill_ids("test-driven-development", "requesting-code-review"))
        workflow = await _planner(llm).generate_dag(BLUEPRINT)

        node1 = workflow["nodes"][0]
        assert node1["config"]["provider"] == "opencode_cli"
        assert node1["config"]["executor_type"] == "local_cli"
        assert node1["config"]["skill_id"] == "test-driven-development"
        assert node1["config"]["skill_version"] == "main"
        assert "## 工作方法" not in (node1["config"].get("system_prompt") or "")

    async def test_missing_skill_id_falls_back_by_purpose(self):
        llm = _make_llm(_dag_with_skill_ids(None, None))
        workflow = await _planner(llm).generate_dag(BLUEPRINT)

        node1 = workflow["nodes"][0]
        assert node1["config"]["skill_id"] == "subagent-driven-development"
        node2 = workflow["nodes"][1]
        assert node2["config"]["skill_id"] == "test-driven-development"

    async def test_invalid_skill_id_falls_back(self):
        llm = _make_llm(_dag_with_skill_ids("no-such-skill", "test-driven-development"))
        workflow = await _planner(llm).generate_dag(BLUEPRINT)
        node1 = workflow["nodes"][0]
        assert node1["config"]["skill_id"] == "subagent-driven-development"

    async def test_local_cli_keeps_skill_id_without_body(self):
        dag = _dag_with_skill_ids("subagent-driven-development")
        dag["nodes"][0]["config"]["provider"] = "opencode_cli"
        dag["nodes"][0]["config"]["executor_type"] = "local_cli"
        llm = _make_llm(dag)
        workflow = await _planner(llm).generate_dag(BLUEPRINT)
        config = workflow["nodes"][0]["config"]
        assert config["skill_id"] == "subagent-driven-development"
        assert "## 工作方法" not in (config.get("system_prompt") or "")
        assert config["skill_version"] == "main"


class TestFallbackPath:
    async def test_fallback_workflow_gets_skills(self):
        """LLM 失败 → fallback workflow 也应用 skill 兜底映射。

        fallback 节点 provider 默认 opencode_cli（通道 B）：skill_id 记入 config，
        正文不烙进（由工作区注入），system_prompt 保持四段式。
        """
        llm = AsyncMock()
        llm.chat.side_effect = RuntimeError("boom")
        workflow = await _planner(llm).generate_dag(BLUEPRINT)
        assert workflow["nodes"], "fallback workflow should have nodes"
        for node in workflow["nodes"]:
            assert node["config"]["skill_id"]
            assert node["config"]["skill_version"] == "main"
            assert "# 角色" in node["config"]["system_prompt"]