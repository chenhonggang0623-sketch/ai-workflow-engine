from app.engine.plan_assembler import assemble_plan, render_plan_markdown


BLUEPRINT = {
    "prd": {
        "summary": "构建一个带用户认证的博客系统",
        "goals": ["支持注册登录", "支持文章发布"],
        "features": ["用户注册与登录", "文章 CRUD", "评论功能"],
        "non_functional": ["响应时间 < 2s", "支持 1000 并发"],
        "acceptance_criteria": ["注册登录流程可端到端跑通", "文章可发布并展示"],
        "assumptions": [],
        "open_questions": [],
    },
    "architecture": {
        "tech_stack": ["FastAPI", "SQLite"],
        "directory_structure": ["backend/"],
        "data_model": [],
        "api_contracts": [],
    },
    "modules": [],
    "constraints": ["所有代码必须遵循模块划分", "技术栈由执行环境决定"],
}


def test_assemble_plan_maps_blueprint_fields():
    plan = assemble_plan("我想做一个博客系统", BLUEPRINT)

    assert "构建一个带用户认证的博客系统" in plan["project_description"]
    assert "FastAPI" in plan["project_description"]
    assert plan["features"] == ["用户注册与登录", "文章 CRUD", "评论功能"]
    assert plan["requirements"][0] == "我想做一个博客系统"
    assert "支持注册登录" in plan["requirements"]
    assert plan["constraints"] == [
        "所有代码必须遵循模块划分",
        "技术栈由执行环境决定",
        "响应时间 < 2s",
        "支持 1000 并发",
    ]
    assert plan["acceptance_criteria"] == [
        "注册登录流程可端到端跑通",
        "文章可发布并展示",
    ]


def test_assemble_plan_dedupes_constraints():
    blueprint = {
        "prd": {
            "summary": "s",
            "goals": [],
            "features": [],
            "non_functional": ["同一约束"],
            "acceptance_criteria": [],
        },
        "constraints": ["同一约束"],
        "modules": [],
    }
    plan = assemble_plan("需求", blueprint)
    assert plan["constraints"] == ["同一约束"]


def test_assemble_plan_requirement_dedupes_against_goals():
    blueprint = {
        "prd": {"summary": "s", "goals": ["同一个目标"], "features": []},
        "constraints": [],
        "modules": [],
    }
    plan = assemble_plan("同一个目标", blueprint)
    assert plan["requirements"] == ["同一个目标"]


def test_assemble_plan_empty_blueprint():
    plan = assemble_plan("原始需求", None)
    assert plan["requirements"] == ["原始需求"]
    assert plan["features"] == []
    assert plan["constraints"] == []
    assert plan["acceptance_criteria"] == []


def test_render_plan_markdown_structure():
    plan = assemble_plan("需求", BLUEPRINT)
    md = render_plan_markdown(plan)

    assert "# 项目方案" in md
    assert "## 项目描述" in md
    assert "## 功能" in md
    assert "## 需求" in md
    assert "## 约束" in md
    assert "## 检验标准" in md
    assert "- 用户注册与登录" in md
    assert "- 需求" in md
    assert "- 所有代码必须遵循模块划分" in md
    assert "- 注册登录流程可端到端跑通" in md


def test_render_plan_markdown_empty_fields():
    md = render_plan_markdown({"project_description": "", "features": []})
    assert "（无）" in md