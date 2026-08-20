"""方案文档组装：需求 + PRD/蓝图 → 结构化方案（零 LLM、无外部依赖）。

方案节点（type=planner）在执行期调用本模块，把规划期产物组装为
工作节点的主输入，并渲染为可落盘的 markdown 文档。
"""

import json


def _as_list(value, default=None) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    return list(default or [])


def _compact_text(value) -> str:
    text = str(value or "").strip()
    return " ".join(text.split())


def assemble_plan(requirement: str, blueprint: dict | None) -> dict:
    """需求 + 蓝图 → 方案文档。

    蓝图字段映射：
    - project_description  ← PRD.summary + 蓝图 architecture 摘要
    - features            ← PRD.features
    - requirements        ← 原始需求原文 + PRD.goals
    - constraints         ← 蓝图 constraints + PRD.non_functional
    - acceptance_criteria ← PRD.acceptance_criteria

    蓝图为空（None）时各字段退化为空列表，requirements 始终含需求原文。
    """
    blueprint = blueprint or {}
    prd = blueprint.get("prd") or {}

    summary = _compact_text(prd.get("summary"))
    architecture = blueprint.get("architecture") or {}
    tech_stack = _as_list(architecture.get("tech_stack"))
    description_parts = [p for p in [summary] if p]
    if tech_stack:
        description_parts.append("技术栈：" + "、".join(tech_stack))
    project_description = "；".join(description_parts)

    goals = _as_list(prd.get("goals"))
    requirements = []
    raw = _compact_text(requirement)
    if raw:
        requirements.append(raw)
    requirements.extend(g for g in goals if g and g not in requirements)

    constraints = list(_as_list(blueprint.get("constraints")))
    for nf in _as_list(prd.get("non_functional")):
        if nf and nf not in constraints:
            constraints.append(nf)

    return {
        "project_description": project_description,
        "features": _as_list(prd.get("features")),
        "requirements": requirements,
        "constraints": constraints,
        "acceptance_criteria": _as_list(prd.get("acceptance_criteria")),
    }


def _render_section(title: str, items: list[str]) -> str:
    if not items:
        return f"## {title}\n\n（无）\n"
    lines = "\n".join(f"- {item}" for item in items)
    return f"## {title}\n\n{lines}\n"


def render_plan_markdown(plan: dict) -> str:
    """方案文档 → markdown（供写入工作区 PLAN.md）。"""
    plan = plan or {}
    title = "项目方案 (Project Plan)"
    description = plan.get("project_description") or "（无）"

    sections = [
        f"# {title}\n",
        "## 项目描述 (Project Description)\n",
        description,
        "\n",
        _render_section("功能 (Features)", plan.get("features") or []),
        _render_section("需求 (Requirements)", plan.get("requirements") or []),
        _render_section("约束 (Constraints)", plan.get("constraints") or []),
        _render_section("检验标准 (Acceptance Criteria)", plan.get("acceptance_criteria") or []),
    ]
    return "\n".join(sections)


def plan_to_json(plan: dict) -> str:
    """方案文档 → JSON 字符串（紧凑，供 context 注入时使用）。"""
    return json.dumps(plan, ensure_ascii=False)