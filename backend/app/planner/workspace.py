import copy
import os
import re
import shutil
from uuid import UUID

from app.skills.registry import DEFAULT_SKILLS_ROOT

WORKSPACE_PROVIDERS = {"opencode_cli", "claude_cli"}

SKILL_DIRS = {
    "opencode_cli": ".opencode/skills",
    "claude_cli": ".claude/skills",
}

WORKSPACE_HINT = (
    "\n\nWorking directory: {path}\n"
    "Create all project files under this directory. "
    "Do not write files anywhere else.\n"
    "REQUIRED: the generated project MUST include two shell scripts at the "
    "project root:\n"
    "- start.sh: starts all project services (install dependencies, run DB "
    "migrations if any, start backend/frontend) and prints their URLs.\n"
    "- end.sh: stops all project services (kill processes bound to the ports "
    "used by the project).\n"
    "Both scripts must be executable (chmod +x), idempotent, and use "
    "set -euo pipefail.\n"
    "Any documentation files you generate (README, design docs, "
    "API reference, changelog, etc.) MUST be written in BOTH English "
    "and Chinese: create the primary doc plus a Chinese version\n"
    "(e.g. README.md + README.zh-CN.md), or a single doc with bilingual "
    'sections ("English" and "中文"). Code comments may stay in one language.'
)


def slugify(name: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", (name or "").strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:max_len].rstrip("-") or "project"


def build_project_path(project_root: str, workflow_name: str, execution_id: UUID) -> str:
    short_id = str(execution_id).split("-")[0]
    return f"{project_root.rstrip('/')}/{slugify(workflow_name)}_{short_id}"


def inject_skills(project_path: str, skill_ids: list[str],
                  provider: str, skills_root: str | None = None) -> list[str]:
    """把 skill 目录复制到工作区的 CLI skill 目录（渐进披露，CLI 运行时按需加载）。

    返回实际注入的 skill_id 列表。已存在的目标目录直接跳过（幂等）。
    """
    subdir = SKILL_DIRS.get(provider)
    if not subdir:
        return []
    root = skills_root or DEFAULT_SKILLS_ROOT
    target_base = os.path.join(project_path, subdir)
    injected: list[str] = []
    for skill_id in skill_ids:
        src = os.path.join(root, skill_id)
        if not os.path.isdir(src):
            continue
        target = os.path.join(target_base, skill_id)
        if os.path.exists(target):
            continue
        shutil.copytree(src, target)
        injected.append(skill_id)
    return injected


def inject_workspace(plan: dict, project_path: str, skills_root: str | None = None) -> dict:
    """Deep-copy the plan and inject the workspace into every coding agent node.

    Nodes with provider in WORKSPACE_PROVIDERS get:
    - config.working_directory = project_path
    - config.executor_config.working_directory = project_path
    - a hint appended to system_prompt so the agent writes files into the workspace.
    """
    updated = copy.deepcopy(plan)
    hint = WORKSPACE_HINT.format(path=project_path)
    for node in updated.get("nodes", []):
        if node.get("type") != "agent":
            continue
        config = node.setdefault("config", {})
        provider = config.get("provider") or config.get("agent_provider")
        if provider not in WORKSPACE_PROVIDERS:
            continue
        config["working_directory"] = project_path
        executor_config = config.setdefault("executor_config", {})
        executor_config["working_directory"] = project_path
        executor_config.setdefault("auto_approve", True)
        skill_id = config.get("skill_id")
        if skill_id:
            inject_skills(project_path, [skill_id], provider, skills_root)
        system_prompt = config.get("system_prompt") or ""
        if project_path not in system_prompt:
            config["system_prompt"] = f"{system_prompt}{hint}"
    return updated
