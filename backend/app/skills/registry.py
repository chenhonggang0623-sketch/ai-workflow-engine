"""SkillRegistry — 文件系统 skill 库的进程内索引 + 关键词兜底匹配。

MVP 以 skills/ 目录为权威源（git 版本化），不建 DB 表。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.skills.loader import SkillMeta, load_skill, scan_skills

DEFAULT_SKILLS_ROOT = str(Path(__file__).resolve().parents[3] / "skills")

FALLBACK_SKILL_ID = "using-superpowers"

PURPOSE_MATCHERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bdebug|fix|repair|bug|error|issue|troubleshoot|diagnos\b", re.IGNORECASE), "systematic-debugging"),
    (re.compile(r"\btest|testing|qa|unit|integration\b", re.IGNORECASE), "test-driven-development"),
    (re.compile(r"\breview|audit|inspect|refactor\b", re.IGNORECASE), "requesting-code-review"),
    (re.compile(r"\bplan|design|architect|blueprint|spec\b", re.IGNORECASE), "writing-plans"),
    (re.compile(r"\brequirement|clarif|analy|understand\b", re.IGNORECASE), "brainstorming"),
    (re.compile(r"\bverify|acceptance|accept|ship|release|finish|final|deliver\b", re.IGNORECASE), "verification-before-completion"),
    (re.compile(r"\bimplement|build|develop|code|create|module\b", re.IGNORECASE), "subagent-driven-development"),
]


class SkillRegistry:
    def __init__(self, skills_root: str | None = None):
        self._root = skills_root or DEFAULT_SKILLS_ROOT
        self._cache: dict[str, SkillMeta] | None = None

    def _load_all(self) -> dict[str, SkillMeta]:
        if self._cache is None:
            self._cache = {m.name: m for m in scan_skills(self._root)}
        return self._cache

    def refresh(self) -> None:
        self._cache = None

    def list_active(self) -> list[SkillMeta]:
        return sorted(self._load_all().values(), key=lambda m: m.name)

    def get(self, skill_id: str) -> SkillMeta | None:
        return self._load_all().get(skill_id)

    def has(self, skill_id: str) -> bool:
        return skill_id in self._load_all()

    def match_by_purpose(self, purpose: str) -> SkillMeta | None:
        """按节点 purpose 关键词映射默认 skill；映射不到兜底 using-superpowers。"""
        if not purpose:
            return self.get(FALLBACK_SKILL_ID)
        for pattern, skill_id in PURPOSE_MATCHERS:
            if pattern.search(purpose):
                meta = self.get(skill_id)
                if meta is not None:
                    return meta
        return self.get(FALLBACK_SKILL_ID)

    def resolve(self, skill_id: str | None, purpose: str | None = None) -> SkillMeta | None:
        """解析节点应使用的 skill：显式 id 优先（校验存在），否则关键词兜底。"""
        if skill_id:
            meta = self.get(skill_id)
            if meta is not None:
                return meta
        return self.match_by_purpose(purpose or "")