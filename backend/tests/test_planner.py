import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.planner import PlannerAgent, PlanningReview
from app.agent.providers import availability
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
        agent_registry.list_agents = AsyncMock(return_value=[])
        tool_registry = MagicMock()
        tool_registry.list_tools = MagicMock(return_value=[])
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

    @pytest.mark.asyncio
    async def test_plan_llm_output_without_plan_node_gets_plan_node_prepended(self, planner):
        """LLM 输出忘记方案节点时，_ensure_plan_node 必须前置插入并连边。"""
        planner._llm.chat = AsyncMock(return_value={
            "content": json.dumps({
                "name": "no-plan",
                "nodes": [
                    {
                        "id": "impl_agent",
                        "type": "agent",
                        "label": "Impl",
                        "config": {
                            "module_id": "core",
                            "role": "developer",
                            "purpose": "implement",
                            "provider": "opencode_cli",
                            "executor_type": "local_cli",
                            "system_prompt": "impl",
                        },
                        "input_mapping": [{"source": "$.requirement", "target": "requirement"}],
                        "output_mapping": [{"source": "output", "target": "$.module_core"}],
                    }
                ],
                "edges": [],
            }),
            "tool_calls": [],
            "usage": {},
        })
        result = await planner.plan("Build a todo app")
        workflow = result["workflow"]
        assert workflow["nodes"][0]["type"] == "planner"
        assert workflow["nodes"][0]["id"] == "plan_node"
        edge_pairs = {(e["source"], e["target"]) for e in workflow["edges"]}
        assert ("plan_node", "impl_agent") in edge_pairs
        impl = next(n for n in workflow["nodes"] if n["id"] == "impl_agent")
        assert any(m["source"] == "$.plan" and m["target"] == "plan"
                   for m in impl["input_mapping"])

    def test_ensure_plan_node_idempotent_when_exists(self, planner):
        workflow = {
            "nodes": [
                {
                    "id": "plan_node",
                    "type": "planner",
                    "label": "方案制定",
                    "config": {},
                    "input_mapping": [],
                    "output_mapping": [],
                },
                {"id": "a", "type": "agent", "config": {}, "input_mapping": [], "output_mapping": []},
            ],
            "edges": [{"source": "plan_node", "target": "a"}],
        }
        result = planner._ensure_plan_node(workflow)
        assert len(result["nodes"]) == 2
        assert result["nodes"][0]["input_mapping"] == [
            {"source": "$.requirement", "target": "requirement"}
        ]
        assert result["nodes"][0]["output_mapping"] == [{"source": "plan", "target": "$.plan"}]
        assert len(result["edges"]) == 1

    def test_ensure_plan_node_prepends_to_empty_graph(self, planner):
        workflow = {"nodes": [], "edges": []}
        result = planner._ensure_plan_node(workflow)
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["type"] == "planner"
        assert result["edges"] == []

    def test_inject_plan_mapping_adds_plan_input_to_agent_nodes(self, planner):
        workflow = {
            "nodes": [
                {"id": "p", "type": "planner", "config": {}, "input_mapping": [], "output_mapping": []},
                {
                    "id": "a",
                    "type": "agent",
                    "config": {},
                    "input_mapping": [{"source": "$.requirement", "target": "requirement"}],
                    "output_mapping": [],
                },
                {"id": "t", "type": "tool", "config": {}, "input_mapping": [], "output_mapping": []},
            ],
            "edges": [],
        }
        result = planner._inject_plan_mapping(workflow)
        agent = next(n for n in result["nodes"] if n["id"] == "a")
        assert agent["input_mapping"] == [
            {"source": "$.plan", "target": "plan"},
            {"source": "$.requirement", "target": "requirement"},
        ]
        planner_node = next(n for n in result["nodes"] if n["id"] == "p")
        assert planner_node["input_mapping"] == []
        tool = next(n for n in result["nodes"] if n["id"] == "t")
        assert tool["input_mapping"] == []

    def test_inject_plan_mapping_idempotent(self, planner):
        workflow = {
            "nodes": [
                {
                    "id": "a",
                    "type": "agent",
                    "config": {},
                    "input_mapping": [{"source": "$.plan", "target": "plan"}],
                    "output_mapping": [],
                }
            ],
            "edges": [],
        }
        result = planner._inject_plan_mapping(workflow)
        assert len(result["nodes"][0]["input_mapping"]) == 1

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
        assert workflow["nodes"][0]["type"] == "planner", (
            "DAG must start with the plan node"
        )
        agent_nodes = [n for n in workflow["nodes"] if n["type"] != "planner"]
        assert len(agent_nodes) >= 3, (
            "Complex task should fall back to a multi-node DAG, got "
            f"{len(workflow['nodes'])}"
        )
        for node in agent_nodes:
            assert node["config"]["provider"] == "opencode_cli"
            assert node["config"]["executor_type"] == "local_cli"
            assert node["config"].get("module_id"), "DAG nodes must reference a blueprint module"
            assert any(m["source"] == "$.plan" for m in node["input_mapping"]), (
                "Work nodes must read the plan"
            )
        assert result["blueprint"]["content"]["modules"], "Blueprint modules must be present"

    @pytest.mark.asyncio
    async def test_medium_task_llm_failure_gets_multi_node_fallback(self, planner):
        planner._llm.chat.side_effect = Exception("LLM down")
        result = await planner.plan("开发一个带用户认证的博客系统，含数据库存储")
        workflow = result["workflow"]
        assert len(workflow["nodes"]) >= 2
        assert workflow["nodes"][0]["type"] == "planner"
        for node in workflow["nodes"]:
            if node["type"] == "planner":
                continue
            assert node["config"]["provider"] == "opencode_cli"

    @pytest.mark.asyncio
    async def test_simple_task_llm_failure_gets_single_node_fallback(self, planner):
        planner._llm.chat.side_effect = Exception("LLM down")
        result = await planner.plan("生成一个计数器页面")
        workflow = result["workflow"]
        assert workflow["nodes"][0]["type"] == "planner"
        assert len(workflow["nodes"]) == 2
        assert workflow["nodes"][1]["config"]["provider"] == "opencode_cli"

    """节点 provider 按可用列表匹配：指定可用→保留；不可用→落默认；缺失→默认；
    替换时 executor_type 强同步。"""

    def test_single_provider_openai_with_placeholder_key_forced_to_default(self, planner, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", "sk-your-key-here")
        monkeypatch.setattr(settings, "agent_default_provider", "opencode_cli")
        monkeypatch.setattr(availability, "available_provider_names", lambda: ["opencode_cli"])
        monkeypatch.setattr(availability, "resolve_effective_default", lambda: "opencode_cli")
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

    def test_single_provider_openai_with_real_key_preserved(self, planner, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", "sk-real-key-123")
        monkeypatch.setattr(settings, "agent_default_provider", "opencode_cli")
        monkeypatch.setattr(availability, "available_provider_names", lambda: ["openai", "opencode_cli"])
        monkeypatch.setattr(availability, "resolve_effective_default", lambda: "opencode_cli")
        workflow = {"nodes": [
            {"id": "n1", "type": "agent", "config": {"provider": "openai", "executor_type": "llm_api"}},
        ], "edges": []}
        planner._normalize_providers(workflow)
        assert workflow["nodes"][0]["config"]["provider"] == "openai"
        assert workflow["nodes"][0]["config"]["executor_type"] == "llm_api"

    def test_single_provider_cli_provider_with_path_preserved(self, planner, monkeypatch):
        monkeypatch.setattr(settings, "claude_code_path", "claude")
        monkeypatch.setattr(settings, "agent_default_provider", "opencode_cli")
        monkeypatch.setattr(availability, "available_provider_names", lambda: ["claude_cli", "opencode_cli"])
        monkeypatch.setattr(availability, "resolve_effective_default", lambda: "opencode_cli")
        workflow = {"nodes": [
            {"id": "n1", "type": "agent", "config": {"provider": "claude_cli", "executor_type": "local_cli"}},
        ], "edges": []}
        planner._normalize_providers(workflow)
        assert workflow["nodes"][0]["config"]["provider"] == "claude_cli"
        assert workflow["nodes"][0]["config"]["executor_type"] == "local_cli"

    def test_single_provider_missing_provider_filled_with_default(self, planner, monkeypatch):
        monkeypatch.setattr(settings, "agent_default_provider", "opencode_cli")
        workflow = {"nodes": [
            {"id": "n1", "type": "agent", "config": {}},
        ], "edges": []}
        planner._normalize_providers(workflow)
        assert workflow["nodes"][0]["config"]["provider"] == "opencode_cli"
        assert workflow["nodes"][0]["config"]["executor_type"] == "local_cli"

    def test_fallback_modules_chain_serial_pipeline(self, planner):
        """fallback 模块 DAG 必须按流水线串行：悬空依赖不产生并行启动。

        无有效依赖的模块依次串联（前一个完成后一个才启动），
        保证 prd → 架构 → 开发 → 验证 的顺序执行。
        """
        modules = [
            {"id": "pm", "name": "PRD", "depends_on": ["feasibility", "scope"],
             "input_contract": ["requirement"], "output_contract": ["prd"]},
            {"id": "architecture", "name": "Arch", "depends_on": ["scope_definition"],
             "input_contract": ["prd"], "output_contract": ["design"]},
            {"id": "backend", "name": "Backend", "depends_on": ["architecture_design", "db_schema"],
             "input_contract": ["design"], "output_contract": ["api"]},
            {"id": "qa", "name": "QA", "depends_on": ["backend"],
             "input_contract": ["api"], "output_contract": ["report"]},
        ]
        wf = planner._build_from_modules(modules, {"modules": modules, "constraints": []})
        node_ids = [n["id"] for n in wf["nodes"]]
        assert node_ids == ["plan_node", "pm_agent", "architecture_agent", "backend_agent", "qa_agent"]
        assert wf["nodes"][0]["type"] == "planner"
        edge_pairs = {(e["source"], e["target"]) for e in wf["edges"]}
        assert edge_pairs == {
            ("plan_node", "pm_agent"),
            ("pm_agent", "architecture_agent"),
            ("architecture_agent", "backend_agent"),
            ("backend_agent", "qa_agent"),
        }
        in_degree = {nid: sum(1 for e in wf["edges"] if e["target"] == nid) for nid in node_ids}
        assert in_degree["plan_node"] == 0
        assert all(in_degree[nid] == 1 for nid in node_ids[1:])
