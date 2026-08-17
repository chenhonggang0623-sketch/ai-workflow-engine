import copy
import os
import uuid

from app.planner.workspace import (
    slugify,
    build_project_path,
    inject_workspace,
    inject_skills,
)


def _plan():
    return {
        "name": "Blog System",
        "nodes": [
            {
                "id": "req_agent",
                "type": "agent",
                "label": "Requirement Analyst",
                "config": {
                    "provider": "openai",
                    "executor_type": "llm_api",
                    "system_prompt": "Analyze requirements.",
                },
            },
            {
                "id": "be_agent",
                "type": "agent",
                "label": "Backend Developer",
                "config": {
                    "provider": "opencode_cli",
                    "executor_type": "local_cli",
                    "system_prompt": "Implement the backend.",
                },
            },
            {
                "id": "tool_node",
                "type": "tool",
                "config": {"tool_id": "shell"},
            },
        ],
        "edges": [],
    }


def test_slugify():
    assert slugify("Blog System") == "blog-system"
    assert slugify("AI 项目!! v2") == "ai-v2"
    assert slugify("   ") == "project"
    assert slugify("a" * 100) == "a" * 40


def test_build_project_path():
    eid = uuid.uuid4()
    path = build_project_path("./generated_projects", "Blog System", eid)
    assert path == f"./generated_projects/blog-system_{str(eid).split('-')[0]}"
    assert path == build_project_path("./generated_projects/", "Blog System", eid)


def test_inject_workspace_only_coding_nodes():
    eid = uuid.uuid4()
    path = build_project_path("/tmp/projects", "Blog System", eid)
    updated = inject_workspace(_plan(), path)

    assert updated["nodes"][0]["config"]["provider"] == "openai"
    assert "working_directory" not in updated["nodes"][0]["config"]

    be_config = updated["nodes"][1]["config"]
    assert be_config["working_directory"] == path
    assert be_config["executor_config"]["working_directory"] == path
    assert be_config["executor_config"]["auto_approve"] is True
    assert path in be_config["system_prompt"]

    assert updated["nodes"][2]["type"] == "tool"
    assert "working_directory" not in updated["nodes"][2]["config"]


def test_inject_workspace_does_not_mutate_original():
    original = _plan()
    eid = uuid.uuid4()
    path = build_project_path("/tmp/projects", "Blog System", eid)
    inject_workspace(original, path)

    assert "working_directory" not in original["nodes"][1]["config"]
    assert "Working directory" not in original["nodes"][1]["config"]["system_prompt"]


def test_inject_workspace_keeps_existing_hint():
    plan = _plan()
    plan["nodes"][1]["config"]["system_prompt"] = "Implement the backend."
    eid = uuid.uuid4()
    path = build_project_path("/tmp/projects", "Blog System", eid)
    updated = inject_workspace(plan, path)
    system_prompt = updated["nodes"][1]["config"]["system_prompt"]
    assert system_prompt.count("Working directory:") == 1
    assert system_prompt.startswith("Implement the backend.")


def test_inject_workspace_claude_cli():
    plan = _plan()
    plan["nodes"][1]["config"]["provider"] = "claude_cli"
    eid = uuid.uuid4()
    path = build_project_path("/tmp/projects", "Blog System", eid)
    updated = inject_workspace(plan, path)
    assert updated["nodes"][1]["config"]["working_directory"] == path


def test_inject_workspace_empty_nodes():
    assert inject_workspace({"nodes": [], "edges": []}, "/tmp/x") == {
        "nodes": [],
        "edges": [],
    }


class TestInjectSkills:
    def test_copies_skill_into_cli_skill_dir(self, tmp_path):
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "test-driven-development"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# TDD\n")
        (skill_dir / "writing-good-tests.md").write_text("ref")

        project = tmp_path / "project"
        project.mkdir()
        injected = inject_skills(str(project), ["test-driven-development"], "opencode_cli", str(skills_root))

        assert injected == ["test-driven-development"]
        assert (project / ".opencode" / "skills" / "test-driven-development" / "SKILL.md").exists()
        assert (project / ".opencode" / "skills" / "test-driven-development" / "writing-good-tests.md").exists()

    def test_claude_cli_uses_claude_dir(self, tmp_path):
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "systematic-debugging"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Debug\n")

        project = tmp_path / "project"
        project.mkdir()
        inject_skills(str(project), ["systematic-debugging"], "claude_cli", str(skills_root))
        assert (project / ".claude" / "skills" / "systematic-debugging" / "SKILL.md").exists()

    def test_missing_skill_ignored_and_idempotent(self, tmp_path):
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "writing-plans"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Plans\n")

        project = tmp_path / "project"
        project.mkdir()
        assert inject_skills(str(project), ["missing-skill"], "opencode_cli", str(skills_root)) == []
        assert inject_skills(str(project), ["writing-plans"], "opencode_cli", str(skills_root)) == ["writing-plans"]
        assert inject_skills(str(project), ["writing-plans"], "opencode_cli", str(skills_root)) == []

    def test_non_cli_provider_returns_empty(self, tmp_path):
        assert inject_skills(str(tmp_path), ["writing-plans"], "openai", str(tmp_path)) == []


class TestInjectWorkspaceWithSkills:
    def test_local_cli_node_gets_skill_into_project(self, tmp_path):
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "subagent-driven-development"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# SDD\n")

        plan = _plan()
        plan["nodes"][1]["config"]["skill_id"] = "subagent-driven-development"
        eid = uuid.uuid4()
        path = build_project_path(str(tmp_path / "projects"), "Blog System", eid)
        updated = inject_workspace(plan, path, skills_root=str(skills_root))

        assert updated["nodes"][1]["config"]["skill_id"] == "subagent-driven-development"
        target = os.path.join(path, ".opencode", "skills", "subagent-driven-development", "SKILL.md")
        assert os.path.exists(target)
