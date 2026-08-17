"""缺口修复测试：output_mapping 契约对齐 + 模块职责进 system_prompt。

对应两个验证缺陷：
1. LLM 编造 output_mapping 键名（$.module_x_1/2/3），与蓝图 output_contract 不对齐
2. 蓝图模块 description（行为要求）未进入节点 system_prompt
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine.prompt_factory import build_node_prompt
from app.planner.planner_agent import PlannerAgent
from app.skills.registry import SkillRegistry


BLUEPRINT = {
    "prd": {"summary": "Build a stats tool", "goals": [], "features": []},
    "architecture": {"tech_stack": ["python"], "data_model": [], "api_contracts": []},
    "modules": [
        {
            "id": "parser",
            "name": "Markdown Parser",
            "description": "解析 Markdown 输入，提取任务列表项与完成状态",
            "depends_on": [],
            "input_contract": ["md_text", "requirement"],
            "output_contract": ["todo_items", "line_number", "content", "completed"],
        },
        {
            "id": "stats",
            "name": "Stats Engine",
            "description": "统计任务完成率并输出汇总",
            "depends_on": ["parser"],
            "input_contract": ["todo_items", "md_text"],
            "output_contract": ["completion_rate", "total", "completed"],
        },
    ],
    "constraints": ["all code must be typed"],
}


def _llm_dag_with_hallucinated_keys():
    """复刻验证时 LLM 的编造行为：source 合规但 target 键名幻觉 + 契约外幻觉键。"""
    return {
        "name": "Planned Workflow",
        "description": "LLM-generated",
        "nodes": [
            {
                "id": "md_parser_agent",
                "type": "agent",
                "label": "Parser",
                "config": {
                    "module_id": "parser",
                    "role": "developer",
                    "purpose": "Parse the markdown",
                    "provider": "opencode_cli",
                    "executor_type": "local_cli",
                    "system_prompt": "You are a developer. Parse markdown into task items.",
                    "timeout_seconds": 900,
                },
                "input_mapping": [
                    {"source": "$.requirement", "target": "requirement"},
                ],
                "output_mapping": [
                    {"source": "todo_items", "target": "$.module_md_parser_1"},
                    {"source": "line_number", "target": "$.module_md_parser_2"},
                    {"source": "content", "target": "$.module_md_parser_3"},
                    {"source": "completed", "target": "$.module_md_parser_4"},
                    {"source": "made_up_field", "target": "$.module_md_parser_5"},
                ],
            },
            {
                "id": "stats_engine_agent",
                "type": "agent",
                "label": "Stats",
                "config": {
                    "module_id": "stats",
                    "role": "developer",
                    "purpose": "Compute stats",
                    "provider": "opencode_cli",
                    "executor_type": "local_cli",
                    "system_prompt": "You are a developer. Compute completion stats.",
                    "timeout_seconds": 900,
                },
                "input_mapping": [
                    {"source": "$.module_md_parser_1", "target": "todo_items"},
                ],
                "output_mapping": [
                    {"source": "completion_rate", "target": "$.module_stats_engine_1"},
                    {"source": "total", "target": "$.module_stats_engine_2"},
                    {"source": "completed", "target": "$.module_stats_engine_3"},
                ],
            },
        ],
        "edges": [
            {"source": "md_parser_agent", "target": "stats_engine_agent"},
        ],
    }


def _make_llm(workflow_json):
    llm = AsyncMock()
    llm.chat.return_value = {"content": json.dumps(workflow_json)}
    return llm


def _planner(llm):
    reg = SkillRegistry()
    return PlannerAgent(llm, MagicMock(), MagicMock(), skill_registry=reg)


class TestOutputMappingAlignment:
    async def test_hallucinated_targets_are_normalized(self):
        """LLM 编造的 target 键名 → 按 output_contract 重建确定性键名。"""
        llm = _make_llm(_llm_dag_with_hallucinated_keys())
        workflow = await _planner(llm).generate_dag(BLUEPRINT)

        parser = next(n for n in workflow["nodes"] if n["id"] == "md_parser_agent")
        targets = [m["target"] for m in parser["output_mapping"]]
        assert targets == [
            "$.module_parser",
            "$.module_parser_1",
            "$.module_parser_2",
            "$.module_parser_3",
        ]
        sources = [m["source"] for m in parser["output_mapping"]]
        assert sources == ["todo_items", "line_number", "content", "completed"]
        assert "made_up_field" not in sources

    async def test_upstream_input_mapping_references_aligned_keys(self):
        """下游 input source 应引用对齐后的确定性输出键。"""
        llm = _make_llm(_llm_dag_with_hallucinated_keys())
        workflow = await _planner(llm).generate_dag(BLUEPRINT)

        stats = next(n for n in workflow["nodes"] if n["id"] == "stats_engine_agent")
        sources = [m["source"] for m in stats["input_mapping"]]
        assert "$.module_parser" in sources

    async def test_input_mapping_targets_use_contract_field_names(self):
        """input target 按 input_contract 字段名对齐。"""
        llm = _make_llm(_llm_dag_with_hallucinated_keys())
        workflow = await _planner(llm).generate_dag(BLUEPRINT)

        stats = next(n for n in workflow["nodes"] if n["id"] == "stats_engine_agent")
        targets = [m["target"] for m in stats["input_mapping"]]
        assert targets == ["todo_items", "md_text"]
        assert len(stats["input_mapping"]) == len(BLUEPRINT["modules"][1]["input_contract"])

    async def test_contract_missing_mappings_filled_from_upstream(self):
        """input_mapping 少于契约字段时，用上游模块输出键补齐。"""
        dag = _llm_dag_with_hallucinated_keys()
        dag["nodes"][0]["input_mapping"] = []
        llm = _make_llm(dag)
        workflow = await _planner(llm).generate_dag(BLUEPRINT)

        parser = next(n for n in workflow["nodes"] if n["id"] == "md_parser_agent")
        targets = [m["target"] for m in parser["input_mapping"]]
        assert targets == ["md_text", "requirement"]

    async def test_fallback_workflow_stays_aligned(self):
        """LLM 失败 → fallback DAG 也经契约对齐（幂等，无副作用）。"""
        llm = AsyncMock()
        llm.chat.side_effect = RuntimeError("boom")
        workflow = await _planner(llm).generate_dag(BLUEPRINT)

        assert len(workflow["nodes"]) == 2
        for node in workflow["nodes"]:
            mid = node["config"]["module_id"]
            module = next(m for m in BLUEPRINT["modules"] if m["id"] == mid)
            expected = [
                {"source": f, "target": f"$.module_{mid}" if i == 0 else f"$.module_{mid}_{i}"}
                for i, f in enumerate(module["output_contract"])
            ]
            assert node["output_mapping"] == expected

    async def test_skill_and_aligned_keys_survive_default_provider(self):
        """统一默认 provider 后：契约对齐键进 output_mapping，skill 走通道 B。"""
        dag = _llm_dag_with_hallucinated_keys()
        dag["nodes"][0]["config"]["provider"] = "openai"
        dag["nodes"][0]["config"]["executor_type"] = "llm_api"
        dag["nodes"][0]["config"]["skill_id"] = "test-driven-development"
        llm = _make_llm(dag)
        workflow = await _planner(llm).generate_dag(BLUEPRINT)

        parser = next(n for n in workflow["nodes"] if n["id"] == "md_parser_agent")
        targets = [m["target"] for m in parser["output_mapping"]]
        assert targets == ["$.module_parser", "$.module_parser_1", "$.module_parser_2", "$.module_parser_3"]
        assert parser["config"]["provider"] == "opencode_cli"
        assert parser["config"]["skill_id"] == "test-driven-development"
        assert parser["config"]["skill_version"] == "main"
        assert "## 工作方法" not in (parser["config"].get("system_prompt") or "")


class TestModuleDescriptionInPrompt:
    async def test_module_description_appended_to_llm_system_prompt(self):
        """LLM 生成的 system_prompt 被追加模块职责段落。"""
        llm = _make_llm(_llm_dag_with_hallucinated_keys())
        workflow = await _planner(llm).generate_dag(BLUEPRINT)

        parser = next(n for n in workflow["nodes"] if n["id"] == "md_parser_agent")
        assert "解析 Markdown 输入" in parser["config"]["system_prompt"]
        assert parser["config"]["system_prompt"].startswith("You are a developer.")

    async def test_module_description_not_duplicated(self):
        """重复调用幂等：描述已存在时不重复追加。"""
        llm = _make_llm(_llm_dag_with_hallucinated_keys())
        planner = _planner(llm)
        workflow = await planner.generate_dag(BLUEPRINT)
        parser = next(n for n in workflow["nodes"] if n["id"] == "md_parser_agent")
        before = parser["config"]["system_prompt"]
        workflow = planner._align_contracts(workflow, BLUEPRINT)
        parser = next(n for n in workflow["nodes"] if n["id"] == "md_parser_agent")
        assert parser["config"]["system_prompt"] == before
        assert parser["config"]["system_prompt"].count("解析 Markdown 输入") == 1


class TestPromptFactoryModuleDescription:
    def test_description_becomes_constraint_entry(self):
        """build_node_prompt：模块描述作为「模块职责」约束条目进入提示词。"""
        node = {
            "id": "parser_agent",
            "type": "agent",
            "config": {"module_id": "parser", "role": "developer", "purpose": "Parse"},
            "input_mapping": [{"source": "$.requirement", "target": "requirement"}],
            "output_mapping": [{"source": "todo_items", "target": "$.module_parser"}],
        }
        prompt = build_node_prompt(node, BLUEPRINT)
        assert "模块职责：解析 Markdown 输入，提取任务列表项与完成状态" in prompt
        assert "all code must be typed" in prompt

    def test_description_only_injected_once(self):
        """蓝图约束与模块描述不重复注入。"""
        node = {
            "config": {"module_id": "parser", "role": "developer", "purpose": "Parse"},
            "input_mapping": [],
            "output_mapping": [],
        }
        prompt = build_node_prompt(node, BLUEPRINT)
        assert prompt.count("模块职责：解析 Markdown") == 1