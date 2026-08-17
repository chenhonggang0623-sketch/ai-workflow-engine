"""Skill catalog：将 skill frontmatter 摘要（渐进披露 L1）组装为注入 PLAN_PROMPT 的文本。

只包含 name + description（每项数十 token），正文不进规划 prompt。
"""

from __future__ import annotations

from app.skills.loader import SkillMeta


def build_catalog(skills: list[SkillMeta], limit: int | None = None) -> str:
    """组装 skill 目录文本。skills 为空时返回 "None"。"""
    if not skills:
        return "None"
    lines = [f"- {m.name}: {m.description}".strip() for m in skills]
    if limit is not None:
        lines = lines[:limit]
    return "\n".join(lines)