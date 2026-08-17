"""节点提示词工厂：契约驱动的四段式 system_prompt 生成。

模板结构（见 OPTIMIZATION_PLAN.md 第 3 章）：
    # 角色 / 可用的输入字段 / 输出要求 / 约束

纯函数模块，不依赖 LLM；供 planner fallback 与 NodeRunner 执行前兜底使用。

Skill 集成（见 docs/SKILL_PROMPT_PIPELINE.md）：传入 SkillMeta 时输出
skill 渲染结果（render_skill_prompt），否则回退本模块四段式模板。
"""

DEFAULT_ROLE = "assistant"
DEFAULT_PURPOSE = "Complete the assigned task based on the provided inputs."


def build_system_prompt(
    role: str | None = None,
    purpose: str | None = None,
    input_fields: list[str] | None = None,
    output_fields: list[str] | None = None,
    output_schema: dict | None = None,
    constraints: list[str] | None = None,
    base_prompt: str | None = None,
) -> str:
    """四段式组装节点 system_prompt。

    - input_fields: 节点可读取的输入字段名（含 $.requirement 等全局字段）
    - output_fields: 节点输出映射目标（语义：产出哪些键）
    - output_schema: 输出 JSON schema（默认 None → 不强制 JSON）
    - constraints: 蓝图约束/模块约束条目
    - base_prompt: 用户/LLM 自定义部分，追加在约束之后
    """
    role = role or DEFAULT_ROLE
    purpose = purpose or DEFAULT_PURPOSE

    sections: list[str] = [f"# 角色\n{role} —— {purpose}"]

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

    if base_prompt and base_prompt.strip():
        sections.append(base_prompt.strip())

    return "\n\n".join(sections)


def build_node_prompt(node: dict, blueprint: dict | None = None, skill=None) -> str:
    """从节点配置 + 蓝图生成 system_prompt（执行前兜底/planner fallback 共用）。

    node: workflow 节点 dict（含 config/input_mapping/output_mapping）
    skill: SkillMeta 可选。存在时输出 skill 渲染 prompt（含四段式头部，
        幂等兼容）；无 skill 时回退四段式模板。
    """
    config = node.get("config") or {}
    module_id = config.get("module_id")
    module = None
    if blueprint and module_id:
        for m in blueprint.get("modules") or []:
            if m.get("id") == module_id:
                module = m
                break

    input_fields = ["$.requirement"]
    for m in node.get("input_mapping") or []:
        src = m.get("source")
        if src and src not in input_fields:
            input_fields.append(src)

    output_fields = []
    for m in node.get("output_mapping") or []:
        tgt = m.get("target")
        if tgt and tgt not in output_fields:
            output_fields.append(tgt)

    constraints = list(config.get("constraints") or [])
    for c in (blueprint or {}).get("constraints") or []:
        if c not in constraints:
            constraints.append(c)
    if module:
        desc = module.get("description")
        if desc:
            desc_entry = f"模块职责：{desc}"
            if desc_entry not in constraints:
                constraints.insert(0, desc_entry)
        for c in module.get("constraints") or []:
            if c not in constraints:
                constraints.append(c)

    role = config.get("role")
    purpose = config.get("purpose")
    base_prompt = config.get("system_prompt")

    # 若已有完整四段式 prompt，不重复包装（幂等）
    if base_prompt and "# 角色" in base_prompt:
        return base_prompt

    if skill is not None:
        from app.skills.renderer import render_skill_prompt

        return render_skill_prompt(
            skill,
            role=role,
            purpose=purpose,
            input_fields=input_fields,
            output_fields=output_fields,
            output_schema=config.get("output_schema"),
            constraints=constraints,
            business_vars={
                "module_id": module_id,
                "module_name": module.get("name") if module else None,
                "purpose": purpose,
                "role": role,
            },
        )

    return build_system_prompt(
        role=role,
        purpose=purpose,
        input_fields=input_fields,
        output_fields=output_fields,
        output_schema=config.get("output_schema"),
        constraints=constraints,
        base_prompt=base_prompt,
    )


def _schema_text(schema: dict) -> str:
    import json

    try:
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(schema)