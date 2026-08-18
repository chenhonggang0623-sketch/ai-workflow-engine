"""SKILL.md 文件系统加载：扫描 skills 目录、解析 frontmatter。

纯函数模块，不依赖 DB / LLM。skills 目录结构（superpowers 兼容）：

    <skills_root>/
      <skill_id>/
        SKILL.md          # frontmatter(name, description) + markdown 正文
        references/...    # 渐进披露附属文件（可选）
        scripts/...       # 可执行脚本（可选）
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

SKILL_MD_NAME = "SKILL.md"


class SkillParseError(Exception):
    pass


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    body: str
    directory: str
    files: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return (
            f"---\nname: {self.name}\ndescription: {self.description}\n---\n\n{self.body}"
        )


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_FIELD_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", re.MULTILINE)


def parse_frontmatter(text: str) -> dict:
    """手写解析 YAML frontmatter（仅 name/description 等简单标量字段）。

    superpowers 的 frontmatter 只含标量字段，无需引入 PyYAML。
    兼容带引号的值（'xxx' / "xxx"）。
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for key, raw in _FIELD_RE.findall(match.group(1)):
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        fields[key] = value
    return fields


def split_frontmatter(text: str) -> tuple[dict, str]:
    """返回 (frontmatter dict, markdown 正文)。无 frontmatter 时返回 ({}, 原文)。"""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    body = text[match.end():].strip()
    return parse_frontmatter(text), body


def scan_skills(skills_root: str) -> list[SkillMeta]:
    """扫描 <skills_root>/*/SKILL.md，返回全部 skill 元数据。"""
    if not os.path.isdir(skills_root):
        return []
    results: list[SkillMeta] = []
    for entry in sorted(os.listdir(skills_root)):
        skill_dir = os.path.join(skills_root, entry)
        md_path = os.path.join(skill_dir, SKILL_MD_NAME)
        if not os.path.isdir(skill_dir) or not os.path.isfile(md_path):
            continue
        meta = load_skill(skills_root, entry)
        if meta is not None:
            results.append(meta)
    return results


def load_skill(skills_root: str, skill_id: str) -> SkillMeta | None:
    """加载单个 skill；目录不存在或 SKILL.md 无法解析时返回 None。"""
    skill_dir = os.path.join(skills_root, skill_id)
    md_path = os.path.join(skill_dir, SKILL_MD_NAME)
    if not os.path.isfile(md_path):
        return None
    try:
        with open(md_path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None

    frontmatter, body = split_frontmatter(text)
    name = frontmatter.get("name") or skill_id
    description = frontmatter.get("description") or ""

    files: list[str] = []
    for root, _dirs, names in os.walk(skill_dir):
        for n in sorted(names):
            if n == SKILL_MD_NAME and root == skill_dir:
                continue
            rel = os.path.relpath(os.path.join(root, n), skill_dir)
            files.append(rel.replace("\\", "/"))

    return SkillMeta(
        name=name,
        description=description,
        body=body,
        directory=skill_dir,
        files=files,
    )