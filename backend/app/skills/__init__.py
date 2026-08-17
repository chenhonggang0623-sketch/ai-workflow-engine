"""app.skills — SKILL.md 提示词流水线：加载 / 索引 / 渲染 / catalog。"""

from app.skills.loader import SkillMeta, load_skill, parse_frontmatter, scan_skills, split_frontmatter
from app.skills.registry import DEFAULT_SKILLS_ROOT, FALLBACK_SKILL_ID, SkillRegistry
from app.skills.renderer import render_skill_prompt
from app.skills.catalog import build_catalog

__all__ = [
    "SkillMeta",
    "load_skill",
    "parse_frontmatter",
    "scan_skills",
    "split_frontmatter",
    "DEFAULT_SKILLS_ROOT",
    "FALLBACK_SKILL_ID",
    "SkillRegistry",
    "render_skill_prompt",
    "build_catalog",
]