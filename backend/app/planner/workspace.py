import copy
import os
import re
import shutil
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import Execution, Workflow
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


def format_generation_ts(ts: datetime | None = None) -> str:
    """生成目录的时间戳：本地时间 YYYYMMDD-HHMM，例如 20260820-1041。"""
    dt = ts or datetime.now()
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.strftime("%Y%m%d-%H%M")


def build_project_path(
    project_root: str, workflow_name: str, version: int,
    ts: datetime | None = None,
) -> str:
    """项目目录：{slug}_v{版本号}_{本地时间}，如 blog-system_v2_20260820-1041。

    version 是同名项目「第几次生成」的序号，时间戳用于肉眼分辨先后。
    """
    stamp = format_generation_ts(ts)
    return f"{project_root.rstrip('/')}/{slugify(workflow_name)}_v{version}_{stamp}"


async def next_generation_version(db: AsyncSession, workflow_name: str) -> int:
    """返回同名项目下一次生成的版本号（已有执行数 + 1）。

    跨同名 workflow 计数：页面每生成一次会新建 workflow，重新执行
    同一 workflow 也会新增 execution，两者都算一次「生成」。
    """
    result = await db.execute(
        select(func.count())
        .select_from(Execution)
        .join(Workflow, Workflow.id == Execution.workflow_id)
        .where(Workflow.name == workflow_name)
    )
    return (result.scalar_one() or 0) + 1


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


def strip_workspace(plan: dict) -> dict:
    """Deep-copy the plan and remove previously injected workspace config.

    清理 agent 节点上由 inject_workspace 写入的 working_directory / 路径提示，
    使同一 workflow 的多次执行能各自注入独立工作目录（见 EXECUTION_PROBLEMS.md
    P1-2），并兼容历史数据（旧 definition 里已烘焙第一次执行的项目路径）。
    """
    updated = copy.deepcopy(plan)
    for node in updated.get("nodes", []):
        if node.get("type") != "agent":
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        config.pop("working_directory", None)
        ec = config.get("executor_config")
        if isinstance(ec, dict):
            ec.pop("working_directory", None)
        system_prompt = config.get("system_prompt")
        if isinstance(system_prompt, str) and "\n\nWorking directory: " in system_prompt:
            idx = system_prompt.find("\n\nWorking directory: ")
            config["system_prompt"] = system_prompt[:idx]
    return updated


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
