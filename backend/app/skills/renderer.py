"""Skill 渲染：SKILL.md 正文 + 业务变量 → 完整四段式 system_prompt。

输出以标准四段式（# 角色 / # 可用的输入字段 / # 输出要求 / # 约束）开头，
保证与 prompt_factory.build_node_prompt 的幂等检查（"# 角色"）兼容：
执行期 build_node_prompt 看到已渲染结果直接返回，不重复包装。
"""

from __future__ import annotations

import json

from app.skills.loader import SkillMeta

# 业务变量替换表：skill 正文中出现的 {{xxx}} 会被替换。
# 约定：skill 正文只使用这些业务变量（规划期渲染掉），
# 避免与执行期 PromptTemplate.render 的 context 变量（{{var}}）混淆。
BUSINESS_VARIABLES = (
    "module_id",
    "module_name",
    "purpose",
    "role",
    "requirement_summary",
)

# 保留占位符：渲染后仍在原文中出现的 {{var}}（非业务变量）保留原样，
# 留给执行期 PromptTemplate.render 处理。若业务变量名不在表内则不动。


def _render_business_vars(text: str, variables: dict) -> str:
    for key in BUSINESS_VARIABLES:
        if key in variables:
            text = text.replace("{{" + key + "}}", str(variables[key]))
    return text


def _schema_text(schema: dict) -> str:
    try:
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(schema)


def render_skill_prompt(
    skill: SkillMeta,
    *,
    role: str | None = None,
    purpose: str | None = None,
    input_fields: list[str] | None = None,
    output_fields: list[str] | None = None,
    output_schema: dict | None = None,
    constraints: list[str] | None = None,
    business_vars: dict | None = None,
) -> str:
    """SKILL.md → 四段式 + 工作方法 section 的完整 system_prompt。"""
    sections: list[str] = [f"# 角色\n{role or 'assistant'} —— {purpose or 'Complete the assigned task based on the provided inputs.'}"]

    inputs = input_fields or ["$.requirement"]
    inputs_block = "\n".join(f"- {f}" for f in inputs)
    sections.append(f"# 可用的输入字段\n{inputs_block}")

    outputs = output_fields or ["output"]
    outputs_block = "\n".join(f"- {f}" for f in outputs)
    if output_schema:
        sections.append(
            f"# 输出要求\n必须输出以下字段，并放入对应的输出映射键：\n{outputs_block}\n"
            "输出必须为符合下列 schema 的 JSON 结构：\n"
            f"```json\n{_schema_text(output_schema)}\n```"
        )
    else:
        sections.append(f"# 输出要求\n必须生成以下字段，并放入输出映射对应键：\n{outputs_block}")

    if constraints:
        constraints_block = "\n".join(f"- {c}" for c in constraints)
        sections.append(f"# 约束\n{constraints_block}")

    body = _render_business_vars(skill.body, business_vars or {})
    sections.append(f"## 工作方法（Skill: {skill.name}）\n{body}")

    return "\n\n".join(sections)