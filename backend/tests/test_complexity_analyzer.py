import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.planner.complexity_analyzer import ComplexityAnalyzer


class TestComplexityAnalyzer:

    @pytest.fixture
    def analyzer(self):
        return ComplexityAnalyzer()

    def test_simple_calculator(self, analyzer):
        result = analyzer.analyze("生成一个计算器HTML页面")
        assert result.level == "simple"
        assert result.estimated_nodes <= 2

    def test_simple_counter(self, analyzer):
        result = analyzer.analyze("写一个计数器")
        assert result.level == "simple"
        assert result.estimated_nodes <= 2

    def test_simple_landing_page(self, analyzer):
        result = analyzer.analyze("Create a landing page with a form")
        assert result.level == "simple"

    def test_medium_blog(self, analyzer):
        result = analyzer.analyze("开发一个博客系统")
        assert result.level == "medium"
        assert result.estimated_nodes >= 3

    def test_medium_cjk_word_count_boosted(self, analyzer):
        """中文需求按字数计入词数，避免长中文需求被低估为 simple。"""
        req = (
            "生成一个日志分析命令行工具。读取访问日志，"
            "按路径聚合统计访问次数与平均响应时间，输出 top 10 报告。"
            "包含解析模块、统计模块、入口三个模块，"
            "解析模块负责读取文件，统计模块负责聚合计算，入口负责打印结果。"
        )
        result = analyzer.analyze(req)
        assert result.level in ("medium", "complex")
        assert result.estimated_nodes >= 3

    def test_medium_cjk_module_keywords(self, analyzer):
        """中文多模块关键词（模块/解析/聚合/统计）应命中 medium 及以上。"""
        result = analyzer.analyze("爬虫系统：多任务调度，支持定时执行与任务上传")
        assert result.level in ("medium", "complex")

    def test_simple_cjk_short_stays_simple(self, analyzer):
        """简短中文简单任务不应被误判为 medium。"""
        result = analyzer.analyze("写一个简单的计数器")
        assert result.level == "simple"

    def test_medium_dashboard(self, analyzer):
        result = analyzer.analyze("Build a CRM dashboard with user management")
        assert result.level == "medium"
        assert result.estimated_nodes >= 3

    def test_medium_api(self, analyzer):
        result = analyzer.analyze("Design and implement a REST API for a forum")
        assert result.level == "medium"

    def test_complex_ecommerce(self, analyzer):
        result = analyzer.analyze("开发一个企业级电商平台")
        assert result.level == "complex"
        assert result.estimated_nodes >= 5

    def test_complex_microservice(self, analyzer):
        result = analyzer.analyze("Build a scalable microservice platform for millions of users")
        assert result.level == "complex"

    def test_complex_enterprise(self, analyzer):
        result = analyzer.analyze("Enterprise-grade high-risk production system with payment integration")
        assert result.level == "complex"

    def test_complex_with_database_auth(self, analyzer):
        result = analyzer.analyze("Build a scalable e-commerce platform with database, auth, and payment")
        assert result.level == "complex"
        assert result.estimated_nodes >= 5

    def test_recommended_agents_match_complexity(self, analyzer):
        simple = analyzer.analyze("写一个计算器")
        assert len(simple.recommended_agents) == 1
        assert simple.recommended_agents[0]["role"] == "developer"

        medium = analyzer.analyze("开发一个博客系统")
        assert len(medium.recommended_agents) == 5

        complex_r = analyzer.analyze("开发一个企业级电商平台")
        assert len(complex_r.recommended_agents) == 8

    def test_to_dict(self, analyzer):
        result = analyzer.analyze("写一个计算器")
        d = result.to_dict()
        assert d["level"] == "simple"
        assert "reason" in d
        assert "recommended_agents" in d
        assert "estimated_nodes" in d


class TestPlannerAgentWithComplexity:

    @pytest.fixture
    def planner(self):
        from app.planner.planner_agent import PlannerAgent
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value={
            "content": "ignored",
            "tool_calls": [],
            "usage": {"prompt_tokens": 50, "completion_tokens": 50},
        })
        agent_registry = AsyncMock()
        agent_registry.list_agents = AsyncMock(return_value=[])
        tool_registry = MagicMock()
        tool_registry.list_tools = MagicMock(return_value=[])
        return PlannerAgent(llm, agent_registry, tool_registry)

    @pytest.mark.asyncio
    async def test_plan_includes_complexity_analysis(self, planner):
        planner._llm.chat = AsyncMock(return_value={
            "content": json.dumps({
                "name": "Calculator",
                "nodes": [{"id": "a1", "type": "agent", "label": "Dev", "config": {
                    "system_prompt": "dev",
                    "role": "developer",
                    "purpose": "build",
                }}],
                "edges": [],
            }),
            "tool_calls": [],
            "usage": {},
        })
        result = await planner.plan("生成一个计算器")
        assert "complexity_analysis" in result
        ca = result["complexity_analysis"]
        assert ca["level"] in ("simple", "medium", "complex")
        assert "reason" in ca
        assert "recommended_agents" in ca
        assert "estimated_nodes" in ca

    @pytest.mark.asyncio
    async def test_complexity_level_in_prompt(self, planner):
        planner._llm.chat = AsyncMock(return_value={
            "content": json.dumps({
                "name": "Blog",
                "nodes": [{"id": "a1", "type": "agent", "label": "Dev", "config": {
                    "system_prompt": "dev",
                    "role": "developer",
                    "purpose": "build",
                }}],
                "edges": [],
            }),
            "tool_calls": [],
            "usage": {},
        })
        await planner.plan("开发一个博客系统")
        _, kwargs = planner._llm.chat.call_args
        prompt = kwargs["messages"][1]["content"]
        assert "Task complexity:" in prompt
        assert any(level in prompt for level in ("simple", "medium", "complex"))

    @pytest.mark.asyncio
    async def test_fallback_still_works(self, planner):
        planner._llm.chat.side_effect = Exception("LLM down")
        result = await planner.plan("Build a todo app")
        assert result["workflow"] is not None
        assert len(result["workflow"]["nodes"]) >= 1
        assert "complexity_analysis" in result

    @pytest.mark.asyncio
    async def test_node_config_has_role_and_purpose(self, planner):
        planner._llm.chat = AsyncMock(return_value={
            "content": json.dumps({
                "name": "Blog",
                "nodes": [
                    {"id": "a1", "type": "agent", "label": "Dev", "config": {
                        "role": "backend_developer",
                        "purpose": "Implement backend",
                        "agent_capability": ["coding"],
                        "system_prompt": "You are a backend dev.",
                        "executor_type": "llm_api",
                    }},
                ],
                "edges": [],
            }),
            "tool_calls": [],
            "usage": {},
        })
        result = await planner.plan("开发一个博客系统")
        # 单节点 DAG 未覆盖蓝图全部模块 → 回退为模块驱动的 fallback DAG，
        # fallback 节点必须声明蓝图模块与职责信息
        node = result["workflow"]["nodes"][0]
        assert "module_id" in node["config"]
        assert "role" in node["config"]
        assert "purpose" in node["config"]
        assert result["blueprint"]["content"]["modules"]
