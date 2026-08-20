import copy
import os
import uuid

from app.planner.workspace import (
    slugify,
    build_project_path,
    inject_workspace,
    strip_workspace,
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
    from datetime import datetime

    path = build_project_path("./generated_projects", "Blog System", 1,
                              ts=datetime(2026, 8, 20, 10, 41))
    assert path == "./generated_projects/blog-system_v1_20260820-1041"
    assert path == build_project_path(
        "./generated_projects/", "Blog System", 1,
        ts=datetime(2026, 8, 20, 10, 41),
    )
    assert build_project_path(
        "/tmp/projects", "Blog System", 3, ts=datetime(2026, 8, 20, 10, 41)
    ) == "/tmp/projects/blog-system_v3_20260820-1041"
    assert build_project_path(
        "/tmp/projects", "Blog System", 2, ts=datetime(2026, 8, 20, 10, 45)
    ) == "/tmp/projects/blog-system_v2_20260820-1045"


def test_inject_workspace_only_coding_nodes():
    eid = uuid.uuid4()
    path = build_project_path("/tmp/projects", "Blog System", 1)
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
    path = build_project_path("/tmp/projects", "Blog System", 1)
    inject_workspace(original, path)

    assert "working_directory" not in original["nodes"][1]["config"]
    assert "Working directory" not in original["nodes"][1]["config"]["system_prompt"]


def test_inject_workspace_keeps_existing_hint():
    plan = _plan()
    plan["nodes"][1]["config"]["system_prompt"] = "Implement the backend."
    eid = uuid.uuid4()
    path = build_project_path("/tmp/projects", "Blog System", 1)
    updated = inject_workspace(plan, path)
    system_prompt = updated["nodes"][1]["config"]["system_prompt"]
    assert system_prompt.count("Working directory:") == 1
    assert system_prompt.startswith("Implement the backend.")


def test_inject_workspace_claude_cli():
    plan = _plan()
    plan["nodes"][1]["config"]["provider"] = "claude_cli"
    eid = uuid.uuid4()
    path = build_project_path("/tmp/projects", "Blog System", 1)
    updated = inject_workspace(plan, path)
    assert updated["nodes"][1]["config"]["working_directory"] == path


def test_inject_workspace_empty_nodes():
    assert inject_workspace({"nodes": [], "edges": []}, "/tmp/x") == {
        "nodes": [],
        "edges": [],
    }


def test_strip_workspace_removes_injected_paths():
    eid = uuid.uuid4()
    path1 = build_project_path("/tmp/projects", "Blog System", 1)
    injected = inject_workspace(_plan(), path1)

    eid2 = uuid.uuid4()
    path2 = build_project_path("/tmp/projects", "Blog System", 2)
    stripped = strip_workspace(injected)
    plan = inject_workspace(stripped, path2)

    be_config = plan["nodes"][1]["config"]
    assert be_config["working_directory"] == path2
    assert be_config["executor_config"]["working_directory"] == path2
    assert path1 not in be_config["system_prompt"]
    assert path2 in be_config["system_prompt"]
    assert be_config["system_prompt"].count("Working directory:") == 1


def test_strip_workspace_keeps_other_config():
    plan = _plan()
    eid = uuid.uuid4()
    path = build_project_path("/tmp/projects", "Blog System", 1)
    injected = inject_workspace(plan, path)
    stripped = strip_workspace(injected)

    assert "working_directory" not in stripped["nodes"][1]["config"]
    assert "Working directory" not in stripped["nodes"][1]["config"]["system_prompt"]
    assert stripped["nodes"][1]["config"]["provider"] == "opencode_cli"
    assert "executor_type" in stripped["nodes"][1]["config"]
    assert stripped["nodes"][0]["config"]["system_prompt"] == "Analyze requirements."


def test_strip_workspace_does_not_mutate_original():
    eid = uuid.uuid4()
    path = build_project_path("/tmp/projects", "Blog System", 1)
    injected = inject_workspace(_plan(), path)
    strip_workspace(injected)
    assert injected["nodes"][1]["config"]["working_directory"] == path


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
        path = build_project_path(str(tmp_path / "projects"), "Blog System", 1)
        updated = inject_workspace(plan, path, skills_root=str(skills_root))

        assert updated["nodes"][1]["config"]["skill_id"] == "subagent-driven-development"
        target = os.path.join(path, ".opencode", "skills", "subagent-driven-development", "SKILL.md")
        assert os.path.exists(target)
