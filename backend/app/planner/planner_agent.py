import json
import logging
import re

from app.core.app_config import config_store
from app.core.config import settings
from app.planner.planning_review import PlanningReview
from app.planner.complexity_analyzer import ComplexityAnalyzer
from app.planner.requirement_analyzer import RequirementAnalyzer
from app.planner.architect import Architect
from app.engine.dag_validator import validate_dag, resolve_dag_limits
from app.engine.prompt_factory import build_node_prompt
from app.skills.registry import SkillRegistry, FALLBACK_SKILL_ID
from app.skills.catalog import build_catalog
from app.skills.loader import SkillMeta

logger = logging.getLogger(__name__)

_MODULE_SOURCE_RE = re.compile(r"^\$\.module_(.+?)(?:_\d+)?$")


def _normalize_module_source(
    source: str, dep_ids: set[str], dep_keys: list[str]
) -> str:
    """把指向上游模块输出的幻觉键改写为确定性键（$.module_{dep}）。

    例：LLM 编造的 "$.module_md_parser_1" → "$.module_md_parser"（对齐后的
    上游第一个输出键）。非模块输出键（$.requirement / 全局字段）原样保留；
    多依赖且无法按模块 id 消歧时保守保留（后续 validate_dag 会拒绝并回退）。
    """
    m = _MODULE_SOURCE_RE.match(source or "")
    if not m:
        return source
    stem = m.group(1)
    if stem in dep_ids:
        return f"$.module_{stem}"
    if len(dep_keys) == 1:
        return dep_keys[0]
    return source

PLAN_PROMPT = """You are a workflow planner. Given a system blueprint, generate a DAG workflow plan that fully respects the blueprint.

Blueprint JSON:
__BLUEPRINT_JSON__

Available node types:
- agent: AI worker with a specific role (requires system_prompt in config)
- tool: Execute a registered tool (shell, file_read, file_write, file_list)
- condition: Branching based on context evaluation (requires expression + branches)
- human: Requires human approval or input (requires prompt_message)

<provider_guide>
Every agent node runs on the SAME default provider "opencode_cli" (local
OpenCode CLI agent). Do NOT assign different providers per node — the user
adjusts providers later in the DAG editor if needed. Nodes differ by their
role / purpose / system_prompt only.
</provider_guide>

<complexity_analysis>
Task complexity: __COMPLEXITY_LEVEL__
Reason: __COMPLEXITY_REASON__
Recommended agent count: __ESTIMATED_NODES__
</complexity_analysis>

<skill_catalog>
Available skills (choose skill_id for each agent node from this catalog; each skill
is a methodology document defining how the agent should work):
__SKILL_CATALOG__
</skill_catalog>

Workflow Generation Rules:
1. Cover EVERY module in the blueprint with at least one agent node.
2. Each agent node MUST set config.module_id to the blueprint module id it implements.
3. Node input_mapping / output_mapping must use ONLY field names declared in that
   module's input_contract / output_contract. The source "$.requirement" is always allowed.
4. Respect each module's depends_on when ordering nodes and creating edges.
5. Every constraint in the blueprint.constraints must be enforceable by the DAG —
   reflect them in system_prompt of the relevant nodes.
6. Every agent node uses provider "opencode_cli" (the default). Do not vary providers.
7. Do not add modules or responsibilities that do not exist in the blueprint.
8. Do not artificially add agents. Balance simplicity and collaboration.
9. Only create a single-node DAG when the blueprint has exactly one module.
10. Each agent node's output_mapping targets MUST be "$.module_{module_id}" for the
    first output and "$.module_{module_id}_{n}" (1-based) for additional outputs,
    so downstream nodes can reference them deterministically.

Each agent node config can include:
- role: what role this agent plays
- purpose: what this agent is responsible for
- module_id: the blueprint module this node implements (REQUIRED)
- provider: always "opencode_cli" — the single default provider (user may
  change it per node in the DAG editor)
- executor_type: how to execute (llm_api, local_cli, mcp) — derived from provider
- skill_id: the methodology skill from <skill_catalog> this agent should follow
  (choose the most fitting skill for the node's responsibility; omit if none fits)
- system_prompt: the agent's instructions, including applicable blueprint constraints

Output ONLY valid JSON. No markdown, no explanation outside the JSON.

Example (single module blueprint):
{
  "name": "Calculator",
  "description": "Implement the calculator module",
  "nodes": [
    {
      "id": "core_agent",
      "type": "agent",
      "label": "Core Implementer",
      "config": {
        "module_id": "core",
        "role": "developer",
        "purpose": "Implement the core module",
        "provider": "opencode_cli",
        "executor_type": "local_cli",
        "system_prompt": "You are a developer. Implement the core module following the blueprint constraints.",
        "timeout_seconds": 900
      },
      "input_mapping": [
        {"source": "$.requirement", "target": "requirement"}
      ],
      "output_mapping": [
        {"source": "implementation", "target": "$.result"}
      ]
    }
  ],
  "edges": []
}

Rules:
1. Each node needs a unique id (alphanumeric + underscore only)
2. Agent nodes MUST have a system_prompt describing the role
3. Use input_mapping to pull data from context ($.keyName)
4. Use output_mapping to push results back to context ($.keyName)
5. Connect nodes with edges to form a valid DAG (no cycles)
6. The first node(s) with no incoming edges will start first
7. Scale node count to match the blueprint module count
8. Implementation / coding / testing / review agents use provider "opencode_cli".

Constraints: __CONSTRAINTS__"""


REVISE_PROMPT = """Revise this workflow plan based on the feedback below.

Current workflow JSON:
__WORKFLOW_JSON__

Feedback: __FEEDBACK__

Output the complete updated workflow JSON (same format as before)."""


PROVIDER_TO_EXECUTOR_TYPE = {
    "openai": "llm_api",
    "opencode_cli": "local_cli",
    "claude_cli": "local_cli",
    "local_model": "local_model",
}


class PlannerAgent:
    def __init__(self, llm_gateway, agent_registry, tool_registry, skill_registry=None):
        self._llm = llm_gateway
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._complexity_analyzer = ComplexityAnalyzer()
        self._requirement_analyzer = RequirementAnalyzer(llm_gateway)
        self._architect = Architect(llm_gateway)
        self._skills = skill_registry or SkillRegistry()

    def _model_config(self) -> dict:
        return {
            "model": config_store.get("default_llm_model", settings.default_llm_model),
            "provider": config_store.get("default_llm_provider", settings.default_llm_provider),
            "base_url": config_store.get("openai_base_url", settings.openai_base_url),
            "temperature": 0.3,
            "max_tokens": 4096,
        }

    async def plan(self, requirement: str, constraints: dict | None = None) -> dict:
        """三段式流水线：需求 → PRD → 蓝图 → DAG。

        返回 {workflow, blueprint, explanation, estimated_duration_seconds,
              review, complexity_analysis}
        """
        constraints = constraints or {}
        constraints_str = json.dumps(constraints, ensure_ascii=False) if constraints else "None"

        complexity = self._complexity_analyzer.analyze(requirement)

        prd = await self._requirement_analyzer.analyze(requirement)
        blueprint = await self._architect.design(prd, requirement)

        workflow_data = await self.generate_dag(blueprint, complexity, constraints_str)

        duration = self._estimate_duration(workflow_data)
        explanation = self._build_explanation(workflow_data, complexity)

        return {
            "workflow": workflow_data,
            "blueprint": {"content": blueprint},
            "explanation": explanation,
            "estimated_duration_seconds": duration,
            "review": {"approved": True, "warnings": [], "suggestions": []},
            "complexity_analysis": complexity.to_dict(),
        }

    async def generate_dag(
        self,
        blueprint: dict,
        complexity=None,
        constraints_str: str = "None",
    ) -> dict:
        """蓝图 → DAG。LLM 生成，失败或校验不过时回退到模块驱动的 fallback DAG。"""
        if complexity is None:
            summary = str(blueprint.get("prd", {}).get("summary", ""))
            complexity = self._complexity_analyzer.analyze(summary)

        try:
            catalog = build_catalog(self._skills.list_active())
            result = await self._llm.chat(
                model_config=self._model_config(),
                messages=[
                    {"role": "system", "content": "You are a workflow planner that outputs valid JSON."},
                    {"role": "user", "content": PLAN_PROMPT
                        .replace("__BLUEPRINT_JSON__", json.dumps(blueprint, ensure_ascii=False))
                        .replace("__CONSTRAINTS__", constraints_str)
                        .replace("__SKILL_CATALOG__", catalog)
                        .replace("__COMPLEXITY_LEVEL__", complexity.level)
                        .replace("__COMPLEXITY_REASON__", complexity.reason)
                        .replace("__ESTIMATED_NODES__", str(complexity.estimated_nodes))},
                ],
            )
            content = result.get("content", "")
            workflow_data = self._parse_llm_output(content)
        except Exception as e:
            logger.warning("LLM DAG generation failed: %s. Using fallback.", e)
            workflow_data = self._build_fallback_workflow(complexity, blueprint)

        workflow_data = self._normalize_providers(workflow_data)
        workflow_data = self._align_contracts(workflow_data, blueprint)
        workflow_data = self._apply_skills(workflow_data, blueprint)

        review = PlanningReview.review(workflow_data)
        blueprint_review = PlanningReview.review_against_blueprint(workflow_data, blueprint)
        dag_report = validate_dag(workflow_data, limits=resolve_dag_limits(config_store))
        if (
            not review["approved"]
            or not blueprint_review["approved"]
            or not dag_report.approved
        ):
            logger.warning(
                "Plan failed review: %s; blueprint: %s; dag: %s",
                review["warnings"], blueprint_review["warnings"],
                [e.message for e in dag_report.errors],
            )
            workflow_data = self._normalize_providers(
                self._build_fallback_workflow(complexity, blueprint)
            )
            workflow_data = self._align_contracts(workflow_data, blueprint)
            workflow_data = self._apply_skills(workflow_data, blueprint)

        return workflow_data

    async def revise(self, plan: dict, feedback: str) -> dict:
        workflow_data = plan.get("workflow", {})
        try:
            result = await self._llm.chat(
                model_config=self._model_config(),
                messages=[
                    {"role": "system", "content": "You are a workflow planner that outputs valid JSON."},
                    {"role": "user", "content": REVISE_PROMPT
                        .replace("__WORKFLOW_JSON__", json.dumps(workflow_data, indent=2))
                        .replace("__FEEDBACK__", feedback)},
                ],
            )
            content = result.get("content", "")
            revised_workflow = self._parse_llm_output(content)
        except Exception as e:
            logger.warning("LLM revision failed: %s. Keeping original plan.", e)
            revised_workflow = dict(workflow_data)

        revised_workflow = self._normalize_providers(revised_workflow)

        review = PlanningReview.review(revised_workflow)
        if not review["approved"]:
            logger.warning("Revised plan failed review, returning original plan")
            revised_workflow = dict(workflow_data)

        duration = self._estimate_duration(revised_workflow)
        explanation = plan.get("explanation", "")
        explanation += f"\n\nRevised based on feedback: {feedback}"

        return {
            "workflow": revised_workflow,
            "explanation": explanation,
            "estimated_duration_seconds": duration,
            "review": review,
        }

    def _build_fallback_workflow(self, complexity, blueprint: dict | None = None) -> dict:
        """复杂度/蓝图驱动的回退 DAG。

        优先按蓝图模块生成（每模块一个节点，按 depends_on 排边）；
        无蓝图时退化为按复杂度推荐团队生成。
        """
        modules = (blueprint or {}).get("modules") or []
        if modules:
            return self._build_from_modules(modules, blueprint or {})

        return self._build_from_agents(complexity)

    def _build_from_modules(self, modules: list[dict], blueprint: dict | None = None) -> dict:
        provider = settings.agent_default_provider
        executor_type = PROVIDER_TO_EXECUTOR_TYPE.get(provider, "local_cli")

        by_id = {m.get("id"): m for m in modules}
        placed: set[str] = set()
        nodes = []
        edges = []
        prev_outputs: dict[str, str] = {}

        for module in modules:
            mid = module.get("id", "module")
            deps = [d for d in module.get("depends_on", []) if d in by_id]

            def _deps_ready(mid: str, placed: set[str]) -> bool:
                return all(d in placed for d in (by_id.get(mid, {}).get("depends_on", []) if by_id.get(mid) else []))

            if deps and not _deps_ready(mid, placed):
                # 拓扑兜底：依赖未就绪时跳过本轮，交给下一轮
                continue

            output_key = f"$.module_{mid}"
            node_id = f"{mid}_agent"

            input_sources = ["$.requirement"]
            for d in module.get("depends_on", []):
                if d in prev_outputs:
                    input_sources.append(prev_outputs[d])
            input_targets = module.get("input_contract") or ["requirement"]
            if len(input_targets) < len(input_sources):
                input_targets = input_targets + ["requirement"] * (len(input_sources) - len(input_targets))

            output_targets = module.get("output_contract") or ["output"]
            if not output_targets:
                output_targets = ["output"]

            nodes.append({
                "id": node_id,
                "type": "agent",
                "label": module.get("name", mid),
                "config": {
                    "module_id": mid,
                    "provider": provider,
                    "executor_type": executor_type,
                    "role": "developer",
                    "purpose": f"Implement the {module.get('name', mid)} module",
                    "system_prompt": build_node_prompt({
                        "config": {
                            "module_id": mid,
                            "role": "developer",
                            "purpose": f"Implement the {module.get('name', mid)} module",
                            "constraints": blueprint.get("constraints") or [],
                        },
                        "input_mapping": [
                            {"source": src, "target": tgt}
                            for src, tgt in zip(input_sources, input_targets)
                        ],
                        "output_mapping": [
                            {"source": out, "target": output_key if i == 0 else f"{output_key}_{i}"}
                            for i, out in enumerate(output_targets)
                        ],
                    }, blueprint),
                    "timeout_seconds": 1200 if len(modules) > 4 else 900,
                },
                "input_mapping": [
                    {"source": src, "target": tgt}
                    for src, tgt in zip(input_sources, input_targets)
                ],
                "output_mapping": [
                    {"source": out, "target": output_key if i == 0 else f"{output_key}_{i}"}
                    for i, out in enumerate(output_targets)
                ],
            })
            for d in module.get("depends_on", []):
                if d in prev_outputs:
                    edges.append({"source": f"{d}_agent", "target": node_id})
            placed.add(mid)
            prev_outputs[mid] = output_key

        # 处理未排入的模块（依赖环兜底）：串在队尾
        remaining = [m for m in modules if m.get("id") not in placed]
        prev_id = None
        for module in remaining:
            mid = module.get("id", "module")
            node_id = f"{mid}_agent"
            nodes.append({
                "id": node_id,
                "type": "agent",
                "label": module.get("name", mid),
                "config": {
                    "module_id": mid,
                    "provider": provider,
                    "executor_type": executor_type,
                    "role": "developer",
                    "purpose": f"Implement the {module.get('name', mid)} module",
                    "system_prompt": build_node_prompt({
                        "config": {
                            "module_id": mid,
                            "role": "developer",
                            "purpose": f"Implement the {module.get('name', mid)} module",
                            "constraints": (blueprint or {}).get("constraints") or [],
                        },
                        "input_mapping": [{"source": "$.requirement", "target": "requirement"}],
                        "output_mapping": [{"source": "output", "target": f"$.module_{mid}"}],
                    }, blueprint),
                    "timeout_seconds": 900,
                },
                "input_mapping": [{"source": "$.requirement", "target": "requirement"}],
                "output_mapping": [{"source": "output", "target": f"$.module_{mid}"}],
            })
            if prev_id:
                edges.append({"source": prev_id, "target": node_id})
            prev_id = node_id

        return {
            "name": "Planned Workflow",
            "description": "Blueprint-driven workflow",
            "nodes": nodes,
            "edges": edges,
        }

    def _build_from_agents(self, complexity) -> dict:
        """无蓝图时的旧回退：按复杂度推荐团队生成。"""
        agents = complexity.recommended_agents
        provider = settings.agent_default_provider
        executor_type = PROVIDER_TO_EXECUTOR_TYPE.get(provider, "local_cli")
        timeout = 1200 if complexity.level == "complex" else 900

        nodes = []
        edges = []
        prev_node_id = None
        for i, agent in enumerate(agents):
            node_id = f"{agent['role']}_{i + 1}"
            output_key = f"$.step_{agent['role']}_{i + 1}"
            if prev_node_id is None:
                input_source = "$.requirement"
            else:
                input_source = f"$.step_{agents[i - 1]['role']}_{i}"

            nodes.append({
                "id": node_id,
                "type": "agent",
                "label": agent["label"],
                "config": {
                    "provider": provider,
                    "executor_type": executor_type,
                    "role": agent["role"],
                    "purpose": f"Handle the {agent['role']} responsibility for the requirement",
                    "system_prompt": agent["system_prompt"],
                    "timeout_seconds": timeout,
                },
                "input_mapping": [{"source": input_source, "target": "input"}],
                "output_mapping": [{"source": "output", "target": output_key}],
            })
            if prev_node_id is not None:
                edges.append({"source": prev_node_id, "target": node_id})
            prev_node_id = node_id

        return {
            "name": "Planned Workflow",
            "description": "Auto-generated workflow",
            "nodes": nodes,
            "edges": edges,
        }

    def _apply_skills(self, workflow: dict, blueprint: dict | None = None) -> dict:
        """为每个 agent 节点解析并应用 skill。

        1. LLM 显式给出 skill_id → 校验存在，不存在则关键词兜底
        2. 无 skill_id → 按 purpose 关键词兜底映射
        3. 通道 A（llm_api）：skill 正文渲染进 system_prompt（烙进 DAG）
        4. 通道 B（local_cli）：config 保留 skill_id，正文不烙进（工作区注入）
        """
        from app.engine.prompt_factory import build_node_prompt

        for node in workflow.get("nodes", []):
            if node.get("type") != "agent":
                continue
            config = node.setdefault("config", {})
            provider = config.get("provider") or config.get("agent_provider")
            purpose = config.get("purpose") or ""
            role = config.get("role")

            skill = self._skills.resolve(config.get("skill_id"), purpose)
            if skill is None:
                config.pop("skill_id", None)
                continue

            config["skill_id"] = skill.name
            if provider == "openai":
                config["system_prompt"] = build_node_prompt(node, blueprint, skill=skill)
            else:
                config.setdefault("skill_version", "main")
        return workflow

    def _align_contracts(self, workflow: dict, blueprint: dict | None = None) -> dict:
        """把节点 input/output_mapping 与蓝图模块契约对齐，并注入模块职责。

        覆盖 LLM 生成路径的确定性缺口（LLM 会编造 output_mapping 键名）：
        - output_mapping.source 重置为模块 output_contract 字段（全量、按序），
          target 用确定性键名 $.module_{mid} / $.module_{mid}_{n}
        - input_mapping 按 input_contract 对齐 target（保留 source，超出契约的丢弃），
          契约字段多于 mapping 时用上游模块输出键（或 $.requirement）补齐
        - 模块 description 作为「模块职责」追加进节点 system_prompt（LLM 路径）

        幂等：fallback 生成的 mapping 已符合契约，重复调用无副作用；
        描述文本已存在于 system_prompt 时不重复追加。
        """
        if not blueprint:
            return workflow
        modules = {m.get("id"): m for m in blueprint.get("modules") or []}
        node_by_module: dict[str, str] = {}
        for node in workflow.get("nodes", []):
            if node.get("type") != "agent":
                continue
            mid = (node.get("config") or {}).get("module_id")
            if mid and mid in modules:
                node_by_module[mid] = node.get("id", "")

        for node in workflow.get("nodes", []):
            if node.get("type") != "agent":
                continue
            config = node.get("config") or {}
            mid = config.get("module_id")
            module = modules.get(mid)
            if not module:
                continue

            out_key = f"$.module_{mid}"
            out_contract = module.get("output_contract") or []
            if out_contract:
                node["output_mapping"] = [
                    {"source": field, "target": out_key if i == 0 else f"{out_key}_{i}"}
                    for i, field in enumerate(out_contract)
                ]

            in_contract = module.get("input_contract") or []
            if in_contract:
                existing = node.get("input_mapping") or []
                dep_ids = {
                    d for d in module.get("depends_on") or [] if d in node_by_module
                }
                upstream_keys = [
                    f"$.module_{d}" for d in module.get("depends_on") or []
                    if d in node_by_module
                ]
                input_mapping = []
                for i, m in enumerate(existing[: len(in_contract)]):
                    input_mapping.append(
                        {
                            "source": _normalize_module_source(
                                m.get("source") or "$.requirement",
                                dep_ids,
                                upstream_keys,
                            ),
                            "target": in_contract[i],
                        }
                    )
                for i in range(len(input_mapping), len(in_contract)):
                    src = (
                        upstream_keys[i - len(existing)]
                        if (i - len(existing)) < len(upstream_keys)
                        else "$.requirement"
                    )
                    input_mapping.append({"source": src, "target": in_contract[i]})
                node["input_mapping"] = input_mapping

            description = module.get("description")
            if description:
                system_prompt = config.get("system_prompt") or ""
                if description not in system_prompt:
                    marker = f"# 模块职责\n{description}"
                    config["system_prompt"] = (
                        system_prompt.rstrip() + "\n\n" + marker if system_prompt else marker
                    )
        return workflow

    def _normalize_providers(self, workflow: dict) -> dict:
        """Every agent node runs on the single default provider.

        Provider choice is not part of planning: all nodes use
        AGENT_DEFAULT_PROVIDER (default "opencode_cli") regardless of how many
        API keys are configured. Nodes differ only by task/purpose/system_prompt.
        The user adjusts a node's provider later in the DAG editor.

        Also keeps executor_type consistent with the chosen provider.
        """
        nodes = workflow.get("nodes", [])
        for node in nodes:
            if node.get("type") != "agent":
                continue
            config = node.setdefault("config", {})
            provider = settings.agent_default_provider
            config["provider"] = provider
            executor_type = config.get("executor_type")
            derived = PROVIDER_TO_EXECUTOR_TYPE.get(provider)
            if derived and (not executor_type or executor_type == "llm_api" and provider != "openai"):
                config["executor_type"] = derived
        return workflow

    def _parse_llm_output(self, content: str) -> dict:
        content = content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        content = content.strip()

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            brace_start = content.find("{")
            brace_end = content.rfind("}")
            if brace_start != -1 and brace_end > brace_start:
                content = content[brace_start : brace_end + 1]
                data = json.loads(content)
            else:
                logger.warning("No valid JSON found in LLM output")
                raise ValueError("No valid JSON found in LLM output")

        if "nodes" not in data or not isinstance(data["nodes"], list):
            logger.warning("LLM output missing nodes array")
            raise ValueError("LLM output missing nodes array")

        if "edges" not in data or not isinstance(data["edges"], list):
            data["edges"] = []

        if "name" not in data:
            data["name"] = "Planned Workflow"

        return data

    def _estimate_duration(self, workflow: dict) -> int:
        nodes = workflow.get("nodes", [])
        if not nodes:
            return 60
        timeouts = []
        for n in nodes:
            cfg = n.get("config", {}) or {}
            timeouts.append(cfg.get("timeout_seconds", 900))
        base = sum(timeouts)
        parallel = max(len(nodes) // 3, 1)
        return max(base // parallel, 60)

    def _build_explanation(self, workflow: dict, complexity=None) -> str:
        nodes = workflow.get("nodes", [])
        edges = workflow.get("edges", [])
        parts = [
            f"Workflow: {workflow.get('name', 'Unnamed')}",
            f"Nodes: {len(nodes)} | Edges: {len(edges)}",
            f"Estimated duration: {self._estimate_duration(workflow)}s",
        ]
        if complexity:
            parts.append(f"Complexity: {complexity.level} ({complexity.reason})")
        return "\n".join(parts)
