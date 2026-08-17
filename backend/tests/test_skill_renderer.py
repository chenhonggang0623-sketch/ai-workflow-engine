import os
import shutil

import pytest

from app.skills.loader import SkillMeta
from app.skills.renderer import render_skill_prompt, BUSINESS_VARIABLES
from app.skills.catalog import build_catalog
from app.skills.registry import SkillRegistry, FALLBACK_SKILL_ID


def _skill(name="impl-skill", body=None):
    return SkillMeta(
        name=name,
        description="does implementation work",
        body=body or "# Implementation\n\nFollow these steps.\n\nUse {{module_name}}.",
        directory="/tmp/skills/" + name,
        files=[],
    )


class TestRenderSkillPrompt:
    def test_four_sections_plus_skill_body(self):
        prompt = render_skill_prompt(
            _skill(),
            role="developer",
            purpose="Implement module core",
            input_fields=["$.requirement"],
            output_fields=["$.module_core"],
            constraints=["Code must be typed"],
        )
        assert "# 角色" in prompt
        assert "# 可用的输入字段" in prompt
        assert "# 输出要求" in prompt
        assert "# 约束" in prompt
        assert "## 工作方法（Skill: impl-skill）" in prompt
        assert "# Implementation" in prompt
        assert "- Code must be typed" in prompt

    def test_business_vars_rendered(self):
        prompt = render_skill_prompt(
            _skill(),
            business_vars={"module_name": "Core"},
        )
        assert "Use Core." in prompt

    def test_idempotent_compatible_with_prompt_factory(self):
        """渲染结果含 '# 角色'，prompt_factory 幂等检查会直接返回不重复包装。"""
        assert "# 角色" in render_skill_prompt(_skill())

    def test_output_schema_embedded(self):
        prompt = render_skill_prompt(
            _skill(body="# s"),
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        )
        assert "JSON" in prompt
        assert '"properties"' in prompt

    def test_business_variables_constants(self):
        assert "module_name" in BUSINESS_VARIABLES
        assert "module_id" in BUSINESS_VARIABLES


class TestBuildCatalog:
    def test_builds_name_and_description(self):
        skills = [_skill("a", "# x"), _skill("b", "# y")]
        catalog = build_catalog(skills)
        assert "- a:" in catalog
        assert "- b:" in catalog
        assert "does implementation work" in catalog
        assert "# Implementation" not in catalog  # 正文不进 catalog

    def test_empty(self):
        assert build_catalog([]) == "None"

    def test_limit(self):
        skills = [_skill(f"s{i}", "# x") for i in range(3)]
        catalog = build_catalog(skills, limit=2)
        assert catalog.count("\n") == 1


class TestSkillRegistry:
    def _real_skills_root(self):
        root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "skills",
        )
        if not os.path.isdir(root):
            pytest.skip("superpowers skills dir not present")
        return root

    def test_matches_purpose_to_skill(self, tmp_path):
        # 复制真实 superpowers skill 到临时目录验证真实解析
        real_root = self._real_skills_root()
        for name in ("subagent-driven-development", "test-driven-development",
                     "systematic-debugging", "requesting-code-review",
                     "writing-plans", "verification-before-completion",
                     "using-superpowers"):
            src = os.path.join(real_root, name)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(tmp_path, name))
        reg = SkillRegistry(str(tmp_path))

        assert reg.match_by_purpose("Implement the core module").name == "subagent-driven-development"
        assert reg.match_by_purpose("Write tests for the module").name == "test-driven-development"
        assert reg.match_by_purpose("Debug the failing test").name == "systematic-debugging"
        assert reg.match_by_purpose("Review the pull request").name == "requesting-code-review"
        assert reg.match_by_purpose("Plan the implementation").name == "writing-plans"
        assert reg.match_by_purpose("Accept the delivery").name == "verification-before-completion"
        assert reg.match_by_purpose("").name == FALLBACK_SKILL_ID
        assert reg.match_by_purpose("zzz unknown words").name == FALLBACK_SKILL_ID

    def test_resolve_explicit_id_preferred(self):
        reg = SkillRegistry(self._real_skills_root())
        # 显式合法 id 优先
        assert reg.resolve("test-driven-development", "Implement stuff").name == "test-driven-development"
        # 显式非法 id -> 关键词兜底
        assert reg.resolve("no-such-skill", "Implement stuff").name == "subagent-driven-development"

    def test_has_and_get(self):
        reg = SkillRegistry(self._real_skills_root())
        assert reg.has("test-driven-development")
        assert not reg.has("nope")
        assert reg.get("test-driven-development") is not None
        assert reg.get("nope") is None