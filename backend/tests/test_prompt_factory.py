from app.engine.prompt_factory import build_system_prompt, build_node_prompt
from app.skills.loader import SkillMeta


def _skill(name="impl-skill"):
    return SkillMeta(
        name=name,
        description="does implementation work",
        body="# Implementation\n\nUse {{module_name}} steps.",
        directory="/tmp/skills/" + name,
        files=[],
    )


class TestBuildSystemPrompt:
    def test_four_sections_structure(self):
        prompt = build_system_prompt(
            role="developer",
            purpose="Implement module core",
            input_fields=["$.requirement", "$.design"],
            output_fields=["$.module_core"],
            constraints=["Code must be typed"],
        )
        assert "# 角色" in prompt
        assert "# 可用的输入字段" in prompt
        assert "# 输出要求" in prompt
        assert "# 约束" in prompt
        assert "developer —— Implement module core" in prompt
        assert "- $.design" in prompt
        assert "- Code must be typed" in prompt

    def test_schema_section_present_when_given(self):
        prompt = build_system_prompt(
            role="r", purpose="p",
            output_fields=["$.result"],
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        )
        assert "# 输出要求" in prompt
        assert "JSON" in prompt
        assert '"properties"' in prompt

    def test_default_input_and_output(self):
        prompt = build_system_prompt(role="r", purpose="p")
        assert "- $.requirement" in prompt
        assert "- output" in prompt

    def test_base_prompt_appended(self):
        prompt = build_system_prompt(
            role="r", purpose="p",
            base_prompt="Use UK English.",
        )
        assert prompt.endswith("Use UK English.")

    def test_no_constraints_section_when_empty(self):
        prompt = build_system_prompt(role="r", purpose="p", constraints=[])
        assert "# 约束" not in prompt


class TestBuildNodePrompt:
    BLUEPRINT = {
        "modules": [
            {
                "id": "core",
                "name": "Core",
                "constraints": ["module core must not touch ui/"],
            }
        ],
        "constraints": ["all code must be typed."],
    }

    def test_uses_module_constraints_from_blueprint(self):
        node = {
            "id": "core_agent",
            "type": "agent",
            "config": {
                "module_id": "core",
                "role": "developer",
                "purpose": "Implement core",
            },
            "input_mapping": [{"source": "$.requirement", "target": "requirement"}],
            "output_mapping": [{"source": "impl", "target": "$.module_core"}],
        }
        prompt = build_node_prompt(node, self.BLUEPRINT)
        assert "module core must not touch ui/" in prompt
        assert "must be typed" in prompt
        assert "$.module_core" in prompt

    def test_idempotent_when_already_structured(self):
        node = {
            "config": {"role": "r", "purpose": "p"},
            "input_mapping": [],
            "output_mapping": [],
        }
        base = "# 角色\ndev\n\n# 可用的输入字段\n- $.requirement"
        node["config"]["system_prompt"] = base
        assert build_node_prompt(node) == base

    def test_requirement_input_fallback(self):
        node = {
            "config": {"role": "r", "purpose": "p"},
            "input_mapping": [],
            "output_mapping": [],
        }
        prompt = build_node_prompt(node)
        assert "# 可用的输入字段" in prompt
        assert "- $.requirement" in prompt

    def test_base_prompt_preserved(self):
        node = {
            "config": {"role": "dev", "purpose": "p",
                       "system_prompt": "You must be cautious."},
            "input_mapping": [{"source": "$.requirement", "target": "requirement"}],
            "output_mapping": [{"source": "out", "target": "$.res"}],
        }
        prompt = build_node_prompt(node)
        assert "You must be cautious." in prompt

    def test_output_schema_in_node_config(self):
        node = {
            "config": {
                "module_id": "core",
                "role": "dev", "purpose": "p",
                "output_schema": {"type": "object"},
            },
            "input_mapping": [],
            "output_mapping": [{"source": "o", "target": "$.r"}],
        }
        prompt = build_node_prompt(node, self.BLUEPRINT)
        assert "JSON" in prompt


class TestBuildNodePromptWithSkill:
    BLUEPRINT = {
        "modules": [
            {
                "id": "core",
                "name": "Core Module",
                "constraints": ["module core must not touch ui/"],
            }
        ],
        "constraints": ["all code must be typed."],
    }

    def _node(self, **config_overrides):
        config = {
            "module_id": "core",
            "role": "developer",
            "purpose": "Implement core",
        }
        config.update(config_overrides)
        return {
            "id": "core_agent",
            "type": "agent",
            "config": config,
            "input_mapping": [{"source": "$.requirement", "target": "requirement"}],
            "output_mapping": [{"source": "impl", "target": "$.module_core"}],
        }

    def test_skill_body_rendered_with_business_vars(self):
        prompt = build_node_prompt(self._node(), self.BLUEPRINT, skill=_skill())
        assert "## 工作方法（Skill: impl-skill）" in prompt
        assert "# Implementation" in prompt
        assert "Use Core Module steps." in prompt

    def test_skill_prompt_keeps_contract_sections(self):
        prompt = build_node_prompt(self._node(), self.BLUEPRINT, skill=_skill())
        assert "# 角色" in prompt
        assert "# 可用的输入字段" in prompt
        assert "# 输出要求" in prompt
        assert "# 约束" in prompt
        assert "module core must not touch ui/" in prompt
        assert "$.module_core" in prompt

    def test_existing_structured_prompt_wins_over_skill(self):
        node = self._node(system_prompt="# 角色\ncustom prompt\n\n# 可用的输入字段\n- x")
        assert build_node_prompt(node, self.BLUEPRINT, skill=_skill()) == node["config"]["system_prompt"]