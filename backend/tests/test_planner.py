import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.planner import PlannerAgent, PlanningReview
from app.core.config import settings


FALLBACK_WORKFLOW = {
    "name": "Planned Workflow",
    "description": "Auto-generated workflow",
    "nodes": [
        {
            "id": "agent_1",
            "type": "agent",
            "label": "Process Requirement",
            "config": {
                "system_prompt": "You are a helpful assistant.",
                "timeout_seconds": 300,
            },
            "input_mapping": [{"source": "$.requirement", "target": "requirement"}],
            "output_mapping": [{"source": "output", "target": "$.result"}],
        }
    ],
    "edges": [],
}


class TestPlanningReview:
    def test_approves_good_workflow(self):
        wf = {
            "name": "test",
            "nodes": [{"id": "a", "type": "agent"}, {"id": "b", "type": "agent"}],
            "edges": [{"source": "a", "target": "b"}],
        }
        result = PlanningReview.review(wf)
        assert result["approved"] is True

    def test_warns_high_node_count(self):
        many_nodes = {
            "nodes": [{"id": f"n{i}"} for i in range(20)],
            "edges": [],
        }
        result = PlanningReview.review(many_nodes)
        assert result["approved"] is False
        assert any("Node count" in w for w in result["warnings"])

    def test_blocks_duplicate_ids(self):
        dup = {
            "nodes": [{"id": "a"}, {"id": "a"}, {"id": "b"}],
            "edges": [],
        }
        result = PlanningReview.review(dup)
        assert result["approved"] is False
        assert any("Duplicate" in w for w in result["warnings"])

    def test_blocks_cycle(self):
        cycle = {
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "edges": [
                {"source": "a", "target": "b"},
                {"source": "b", "target": "c"},
                {"source": "c", "target": "a"},
            ],
        }
        result = PlanningReview.review(cycle)
        assert result["approved"] is False
        assert any("cycle" in w.lower() for w in result["warnings"])

    def test_warns_deep_dag(self):
        deep = {
            "nodes": [{"id": f"n{i}"} for i in range(15)],
            "edges": [{"source": f"n{i}", "target": f"n{i+1}"} for i in range(14)],
        }
        result = PlanningReview.review(deep)
        assert result["approved"] is True
        assert any("depth" in w.lower() for w in result.get("warnings", []))

    def test_empty_workflow(self):
        result = PlanningReview.review({"nodes": [], "edges": []})
        assert result["approved"] is True
        assert any("fewer than 2" in s for s in result["suggestions"])


class TestPlannerAgent:
    @pytest.fixture
    def planner(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value={
            "content": json.dumps(FALLBACK_WORKFLOW),
            "tool_calls": [],
            "usage": {"prompt_tokens": 50, "completion_tokens": 50},
        })
        agent_registry = AsyncMock()
        agent_registry.list = AsyncMock(return_value=[])
        tool_registry = MagicMock()
        tool_registry.list = MagicMock(return_value=[])
        return PlannerAgent(llm, agent_registry, tool_registry)

    @pytest.mark.asyncio
    async def test_plan_returns_expected_structure(self, planner):
        result = await planner.plan("Build a todo app")
        assert "workflow" in result
        assert "explanation" in result
        assert "estimated_duration_seconds" in result
        assert "review" in result
        assert "nodes" in result["workflow"]
        assert "edges" in result["workflow"]
        assert result["estimated_duration_seconds"] >= 60

    @pytest.mark.asyncio
    async def test_plan_includes_workflow_name(self, planner):
        result = await planner.plan("Build a todo app")
        assert "name" in result["workflow"]

    @pytest.mark.asyncio
    async def test_plan_falls_back_on_llm_failure(self, planner):
        planner._llm.chat.side_effect = Exception("LLM down")
        result = await planner.plan("Build a todo app")
        assert result["workflow"] is not None
        assert len(result["workflow"]["nodes"]) >= 1

    @pytest.mark.asyncio
    async def test_revise_updates_explanation(self, planner):
        initial = await planner.plan("Build a todo app")
        revised = await planner.revise(initial, "Add a code review step")
        assert "Revised" in revised["explanation"]

    @pytest.mark.asyncio
    async def test_revise_handles_llm_failure(self, planner):
        planner._llm.chat.side_effect = Exception("LLM down")
        initial = await planner.plan("Build a todo app")
        planner._llm.chat = AsyncMock(side_effect=Exception("LLM still down"))
        revised = await planner.revise(initial, "Add more steps")
        assert revised["workflow"] is not None

    @pytest.mark.asyncio
    async def test_plan_invalid_json_falls_back(self, planner):
        planner._llm.chat = AsyncMock(return_value={
            "content": "this is not json",
            "tool_calls": [],
            "usage": {},
        })
        result = await planner.plan("Build a todo app")
        assert result["workflow"] is not None
        assert len(result["workflow"]["nodes"]) >= 1

    @pytest.mark.asyncio
    async def test_plan_missing_nodes_falls_back(self, planner):
        planner._llm.chat = AsyncMock(return_value={
            "content": json.dumps({"name": "bad", "edges": []}),
            "tool_calls": [],
            "usage": {},
        })
        result = await planner.plan("Build a todo app")
        assert result["workflow"] is not None
        assert len(result["workflow"]["nodes"]) >= 1

    def test_parse_llm_output_with_code_fence(self, planner):
        content = "```json\n" + json.dumps(FALLBACK_WORKFLOW) + "\n```"
        result = planner._parse_llm_output(content)
        assert "nodes" in result

    def test_parse_llm_output_bare_json(self, planner):
        content = json.dumps(FALLBACK_WORKFLOW)
        result = planner._parse_llm_output(content)
        assert "nodes" in result

    def test_parse_llm_output_no_json(self, planner):
        with pytest.raises(ValueError):
            planner._parse_llm_output("completely broken")

    @pytest.mark.asyncio
    async def test_complex_task_llm_failure_gets_multi_node_fallback(self, planner):
        planner._llm.chat.side_effect = Exception("LLM down")
        result = await planner.plan(
            "构建电商平台，微服务架构，高并发，分布式，支付集成，需要企业级生产部署"
        )
        workflow = result["workflow"]
        assert len(workflow["nodes"]) >= 3, (
            "Complex task should fall back to a multi-node DAG, got "
            f"{len(workflow['nodes'])}"
        )
        for node in workflow["nodes"]:
            assert node["config"]["provider"] == "opencode_cli"
            assert node["config"]["executor_type"] == "local_cli"
            assert node["config"].get("module_id"), "DAG nodes must reference a blueprint module"
        assert result["blueprint"]["content"]["modules"], "Blueprint modules must be present"

    @pytest.mark.asyncio
    async def test_medium_task_llm_failure_gets_multi_node_fallback(self, planner):
        planner._llm.chat.side_effect = Exception("LLM down")
        result = await planner.plan("开发一个带用户认证的博客系统，含数据库存储")
        workflow = result["workflow"]
        assert len(workflow["nodes"]) >= 2
        for node in workflow["nodes"]:
            assert node["config"]["provider"] == "opencode_cli"

    @pytest.mark.asyncio
    async def test_simple_task_llm_failure_gets_single_node_fallback(self, planner):
        planner._llm.chat.side_effect = Exception("LLM down")
        result = await planner.plan("生成一个计数器页面")
        workflow = result["workflow"]
        assert len(workflow["nodes"]) == 1
        assert workflow["nodes"][0]["config"]["provider"] == "opencode_cli"

    """所有节点无条件统一使用默认 provider（无论配置多少 key），节点间仅任务/prompt 不同；
    用户可在 DAG 编辑器中点击节点按需修改 provider。"""

    def test_single_provider_openai_with_placeholder_key_forced_to_default(self, planner, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", "sk-your-key-here")
        monkeypatch.setattr(settings, "agent_default_provider", "opencode_cli")
        workflow = {
            "nodes": [
                {"id": "n1", "type": "agent", "config": {
                    "provider": "openai", "executor_type": "llm_api"}},
                {"id": "n2", "type": "agent", "config": {
                    "provider": "openai", "executor_type": "llm_api",
                    "system_prompt": "different task"}},
            ],
            "edges": [],
        }
        planner._normalize_providers(workflow)
        for node in workflow["nodes"]:
            assert node["config"]["provider"] == "opencode_cli", node
            assert node["config"]["executor_type"] == "local_cli"
            if node["id"] == "n2":
                assert node["config"]["system_prompt"] == "different task"

    def test_single_provider_openai_with_real_key_still_defaulted(self, planner, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", "sk-real-key-123")
        monkeypatch.setattr(settings, "agent_default_provider", "opencode_cli")
        workflow = {"nodes": [
            {"id": "n1", "type": "agent", "config": {"provider": "openai", "executor_type": "llm_api"}},
        ], "edges": []}
        planner._normalize_providers(workflow)
        assert workflow["nodes"][0]["config"]["provider"] == "opencode_cli"
        assert workflow["nodes"][0]["config"]["executor_type"] == "local_cli"

    def test_single_provider_cli_provider_with_path_still_defaulted(self, planner, monkeypatch):
        monkeypatch.setattr(settings, "claude_code_path", "claude")
        monkeypatch.setattr(settings, "agent_default_provider", "opencode_cli")
        workflow = {"nodes": [
            {"id": "n1", "type": "agent", "config": {"provider": "claude_cli", "executor_type": "local_cli"}},
        ], "edges": []}
        planner._normalize_providers(workflow)
        assert workflow["nodes"][0]["config"]["provider"] == "opencode_cli"
        assert workflow["nodes"][0]["config"]["executor_type"] == "local_cli"

    def test_single_provider_missing_provider_filled_with_default(self, planner, monkeypatch):
        monkeypatch.setattr(settings, "agent_default_provider", "opencode_cli")
        workflow = {"nodes": [
            {"id": "n1", "type": "agent", "config": {}},
        ], "edges": []}
        planner._normalize_providers(workflow)
        assert workflow["nodes"][0]["config"]["provider"] == "opencode_cli"
        assert workflow["nodes"][0]["config"]["executor_type"] == "local_cli"
